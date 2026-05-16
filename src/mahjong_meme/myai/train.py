"""Behavioral-cloning trainer for MyAI.

Reads the per-seat JSON dumps under a data root (default
``demo/parsed/``), encodes each record into a multi-head supervised
sample, and minimizes per-head cross-entropy. Checkpoints land under
``artifacts/myai/`` (gitignored).

The training loop is intentionally compact and dependency-light; use
mortal or external frameworks for serious experimentation.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from .dataset import (
    HEAD_TO_ID, ReplayDataset, compute_class_weights, discover_replays,
    split_replays,
)
from .model import MyAI, count_parameters


HEAD_ID_TO_NAME = {v: k for k, v in HEAD_TO_ID.items()}


def _move_batch(batch, device):
    planes, scalars, head_id, label, weight = batch
    return (planes.to(device, non_blocking=True),
            scalars.to(device, non_blocking=True),
            head_id.to(device, non_blocking=True),
            label.to(device, non_blocking=True),
            weight.to(device, non_blocking=True))


def _per_head_loss(
    logits: dict[str, torch.Tensor],
    head_id: torch.Tensor,
    label: torch.Tensor,
    weight: torch.Tensor,
) -> tuple[torch.Tensor, dict[str, dict]]:
    """Sum of per-head cross-entropies, computed only on samples whose
    ``head_id`` matches each head. Returns total loss + per-head stats."""
    total = torch.zeros((), device=label.device, dtype=torch.float32)
    stats: dict[str, dict] = {}
    for name, lg in logits.items():
        hid = HEAD_TO_ID[name]
        mask = head_id == hid
        if not mask.any():
            stats[name] = {"n": 0, "loss": 0.0, "acc": 0.0}
            continue
        sub_logits = lg[mask]
        sub_labels = label[mask]
        sub_weights = weight[mask]
        ce = F.cross_entropy(sub_logits, sub_labels, reduction="none")
        loss = (ce * sub_weights).mean()
        total = total + loss
        with torch.no_grad():
            pred = sub_logits.argmax(dim=-1)
            acc = (pred == sub_labels).float().mean().item()
        stats[name] = {"n": int(mask.sum().item()),
                       "loss": float(loss.item()), "acc": acc}
    return total, stats


def _aggregate(stats_list: list[dict[str, dict]]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"n": 0, "loss": 0.0, "acc": 0.0})
    for s in stats_list:
        for name, v in s.items():
            n = v["n"]
            if n == 0:
                continue
            out[name]["n"] += n
            out[name]["loss"] += v["loss"] * n
            out[name]["acc"] += v["acc"] * n
    for name, v in out.items():
        if v["n"] > 0:
            v["loss"] /= v["n"]
            v["acc"] /= v["n"]
    return dict(out)


def _fmt_stats(stats: dict[str, dict]) -> str:
    parts = []
    for name in ("discard", "call", "kan", "riichi", "win"):
        v = stats.get(name)
        if not v or v["n"] == 0:
            continue
        parts.append(f"{name}: n={v['n']} loss={v['loss']:.3f} acc={v['acc']:.3f}")
    return " | ".join(parts) or "<no samples>"


def train(args: argparse.Namespace) -> int:
    data_root = Path(args.data)
    replays = discover_replays(data_root)
    if not replays:
        print(f"error: no replays found in {data_root}", file=sys.stderr)
        return 2

    train_dirs, val_dirs = split_replays(replays, val_fraction=args.val_fraction,
                                          seed=args.seed)
    print(f"train replays: {len(train_dirs)}  val replays: {len(val_dirs)}")

    if not args.no_class_weights:
        print("Computing class weights …")
        class_weights = compute_class_weights(
            train_dirs, max_records=args.weight_max_records
        )
        for h, w in class_weights.items():
            print(f"  {h}: {np.round(w, 3).tolist()}")
    else:
        class_weights = None

    train_ds = ReplayDataset(train_dirs, seed=args.seed,
                              class_weights=class_weights)
    val_ds = ReplayDataset(val_dirs, shuffle_replays=False, seed=args.seed,
                            class_weights=None)
    train_loader = DataLoader(train_ds, batch_size=args.batch,
                              num_workers=args.workers, drop_last=True,
                              persistent_workers=args.workers > 0)
    val_loader = DataLoader(val_ds, batch_size=args.batch,
                            num_workers=max(0, args.workers // 2),
                            persistent_workers=args.workers > 0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MyAI(channels=args.channels, num_blocks=args.blocks).to(device)
    print(f"model params: {count_parameters(model):,}  device: {device}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr,
                                  weight_decay=args.weight_decay)
    total_steps = max(1, args.max_steps)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lr_lambda=lambda step: 0.5 * (1.0 + math.cos(math.pi * min(1.0,
                                                                    step / total_steps))),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    ckpt_dir = Path(args.out_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    step = 0
    best_val = math.inf
    epoch = 0
    train_stats_buffer: list[dict] = []
    t_start = time.time()
    while step < total_steps:
        epoch += 1
        for batch in train_loader:
            planes, scalars, head_id, label, weight = _move_batch(batch, device)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                logits = model(planes, scalars)
                loss, stats = _per_head_loss(logits, head_id, label, weight)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()

            train_stats_buffer.append(stats)
            step += 1
            if step % args.log_every == 0:
                agg = _aggregate(train_stats_buffer)
                train_stats_buffer = []
                elapsed = time.time() - t_start
                lr = optimizer.param_groups[0]["lr"]
                print(f"[step {step:6d}  epoch {epoch}  lr={lr:.2e}  "
                      f"{elapsed:.0f}s]  {_fmt_stats(agg)}")

            if step % args.eval_every == 0 or step >= total_steps:
                val_stats = _evaluate(model, val_loader, device)
                val_loss = sum(v["loss"] * v["n"] for v in val_stats.values())
                val_n = sum(v["n"] for v in val_stats.values()) or 1
                val_loss /= val_n
                print(f"[eval @ {step}]  loss={val_loss:.3f}  "
                      f"{_fmt_stats(val_stats)}")
                _save_checkpoint(ckpt_dir / "last.pt", model, step,
                                  optimizer, args)
                if val_loss < best_val:
                    best_val = val_loss
                    _save_checkpoint(ckpt_dir / "best.pt", model, step,
                                      optimizer, args)
                    print(f"  -> new best (loss={val_loss:.3f}); "
                          f"saved best.pt")
            if step >= total_steps:
                break

    print(f"done. best val loss: {best_val:.3f}")
    return 0


def _evaluate(model, loader, device) -> dict[str, dict]:
    model.eval()
    stats_list: list[dict] = []
    with torch.no_grad():
        for batch in loader:
            planes, scalars, head_id, label, weight = _move_batch(batch, device)
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                logits = model(planes, scalars)
            _, stats = _per_head_loss(logits, head_id, label, weight)
            stats_list.append(stats)
    model.train()
    return _aggregate(stats_list)


def _save_checkpoint(path: Path, model, step: int, optimizer, args):
    payload = {
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "step": step,
        "config": {
            "channels": args.channels,
            "blocks":   args.blocks,
        },
    }
    torch.save(payload, path)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="demo/parsed",
                   help="Root dir of per-seat JSON dumps.")
    p.add_argument("--out-dir", default="artifacts/myai",
                   help="Where to save checkpoints.")
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--channels", type=int, default=128)
    p.add_argument("--blocks", type=int, default=10)
    p.add_argument("--max-steps", type=int, default=20000)
    p.add_argument("--log-every", type=int, default=100)
    p.add_argument("--eval-every", type=int, default=1000)
    p.add_argument("--val-fraction", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-class-weights", action="store_true")
    p.add_argument("--weight-max-records", type=int, default=200_000,
                   help="Cap on records sampled for class-weight estimation.")
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_argparser()
    args = p.parse_args(argv)
    return train(args)


if __name__ == "__main__":
    sys.exit(main())
