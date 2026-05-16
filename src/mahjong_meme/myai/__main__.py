"""CLI entry point: ``python -m mahjong_meme.myai <subcommand>``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _cmd_train(argv: list[str]) -> int:
    from .train import main as train_main
    return train_main(argv)


def _cmd_eval(argv: list[str]) -> int:
    """Evaluate a checkpoint against the val split of a data root."""
    import torch
    from torch.utils.data import DataLoader
    from .dataset import ReplayDataset, discover_replays, split_replays
    from .train import _aggregate, _evaluate, _move_batch

    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--data", default="demo/parsed")
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--val-fraction", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    from .model import MyAI
    ckpt = torch.load(args.checkpoint, map_location="cpu")
    config = ckpt.get("config") or {}
    model = MyAI(channels=config.get("channels", 128),
                 num_blocks=config.get("blocks", 10))
    model.load_state_dict(ckpt["model_state"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    replays = discover_replays(args.data)
    _, val_dirs = split_replays(replays, val_fraction=args.val_fraction,
                                  seed=args.seed)
    ds = ReplayDataset(val_dirs, shuffle_replays=False, seed=args.seed)
    loader = DataLoader(ds, batch_size=args.batch, num_workers=args.workers)
    stats = _evaluate(model, loader, device)
    print(json.dumps(stats, indent=2))
    return 0


def _cmd_predict(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--state", required=True,
                   help="Path to a JSON file containing one observer state dict.")
    p.add_argument("--topk", type=int, default=3)
    args = p.parse_args(argv)

    from .predict import MyAIPredictor
    predictor = MyAIPredictor(args.checkpoint)
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    # Allow the user to pass either a raw state dict or a full record
    # ({state: ..., choice: ..., ...}).
    if "state" in state and isinstance(state["state"], dict):
        state = state["state"]
    out = predictor.recommend(state, topk=args.topk)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


_COMMANDS = {
    "train":   _cmd_train,
    "eval":    _cmd_eval,
    "predict": _cmd_predict,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m mahjong_meme.myai {train|eval|predict} [args]")
        return 0 if argv else 2
    cmd = argv[0]
    rest = argv[1:]
    if cmd not in _COMMANDS:
        print(f"unknown subcommand: {cmd}", file=sys.stderr)
        return 2
    return _COMMANDS[cmd](rest)


if __name__ == "__main__":
    sys.exit(main())
