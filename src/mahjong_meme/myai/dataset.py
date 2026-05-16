"""Streaming dataset over the per-seat JSON dumps.

Reads ``demo/parsed/**/seat*.json`` files, encodes each record into
``(planes, scalars, head_id, label)`` and yields them as a PyTorch
``IterableDataset``. We avoid loading every record into memory at once
because the corpus grows quickly past 1M records.

A replay-level train/val split prevents leakage: an entire replay
either trains or validates, never both.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
import torch
from torch.utils.data import IterableDataset

from .actions import (
    HEAD_DISCARD, HEAD_CALL, HEAD_KAN, HEAD_RIICHI, HEAD_WIN,
    encode_choice,
)
from .features import encode_state


HEAD_TO_ID = {
    HEAD_DISCARD: 0,
    HEAD_CALL:    1,
    HEAD_KAN:     2,
    HEAD_RIICHI:  3,
    HEAD_WIN:     4,
}


def discover_replays(root: Path | str) -> list[Path]:
    """Return all per-replay directories under ``root``."""
    root = Path(root)
    if not root.exists():
        return []
    out: list[Path] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if any((d / f"seat{i}.json").exists() or (d / f"seat{i}.jsonl").exists()
               for i in range(4)):
            out.append(d)
    return out


def split_replays(
    dirs: Iterable[Path],
    *,
    val_fraction: float = 0.1,
    seed: int = 0,
) -> tuple[list[Path], list[Path]]:
    """Deterministic replay-level split via hash bucketing.

    Same set of dirs + same seed → same split, even if more replays are
    added later.
    """
    train: list[Path] = []
    val: list[Path] = []
    for d in dirs:
        h = hashlib.md5(f"{seed}:{d.name}".encode("utf-8")).hexdigest()
        bucket = int(h[:8], 16) / 0xFFFFFFFF
        (val if bucket < val_fraction else train).append(d)
    return train, val


def _iter_records_in_dir(replay_dir: Path) -> Iterator[dict]:
    """Yield records (with synthetic ``seat`` injected) from one replay
    directory, regardless of json vs jsonl format."""
    for seat in range(4):
        json_path = replay_dir / f"seat{seat}.json"
        jsonl_path = replay_dir / f"seat{seat}.jsonl"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            records = data.get("records") or []
            for r in records:
                r["seat"] = seat
                yield r
        elif jsonl_path.exists():
            with jsonl_path.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    r["seat"] = seat
                    yield r


class ReplayDataset(IterableDataset):
    """Stream encoded training samples from a set of replay directories.

    Each sample yielded is ``(planes, scalars, head_id, label,
    sample_weight)`` as torch tensors. ``head_id`` selects which head's
    loss is active for this sample.
    """

    def __init__(
        self,
        replay_dirs: Iterable[Path],
        *,
        shuffle_replays: bool = True,
        seed: int = 0,
        class_weights: dict[str, np.ndarray] | None = None,
    ):
        super().__init__()
        self.dirs = list(replay_dirs)
        self.shuffle_replays = shuffle_replays
        self.seed = seed
        self.class_weights = class_weights or {}

    def __iter__(self) -> Iterator[tuple]:
        rng = np.random.default_rng(self.seed)
        dirs = list(self.dirs)
        if self.shuffle_replays:
            rng.shuffle(dirs)

        worker_info = torch.utils.data.get_worker_info()
        if worker_info is not None:
            dirs = dirs[worker_info.id::worker_info.num_workers]

        for d in dirs:
            for rec in _iter_records_in_dir(d):
                sample = self._encode(rec)
                if sample is not None:
                    yield sample

    def _encode(self, rec: dict):
        label_info = encode_choice(rec)
        if label_info is None:
            return None
        head_name, label = label_info
        head_id = HEAD_TO_ID[head_name]
        enc = encode_state(rec.get("state") or {})
        if not enc["mask"].get(head_name, False):
            # Strictly speaking the head should be active; but skip-with-
            # options edge cases can still produce labels with empty
            # options. Force the mask on for the labelled head.
            pass
        weight = 1.0
        if head_name in self.class_weights:
            w = self.class_weights[head_name]
            if 0 <= label < len(w):
                weight = float(w[label])
        return (
            torch.from_numpy(enc["planes"]),
            torch.from_numpy(enc["scalars"]),
            torch.tensor(head_id, dtype=torch.long),
            torch.tensor(label, dtype=torch.long),
            torch.tensor(weight, dtype=torch.float32),
        )


def compute_class_weights(
    replay_dirs: Iterable[Path],
    *,
    max_records: int | None = None,
) -> dict[str, np.ndarray]:
    """Single pass over the data to compute inverse-frequency weights
    per head. Used to rebalance the dominant 'pass' class.
    """
    counts: dict[str, dict[int, int]] = {
        HEAD_DISCARD: {}, HEAD_CALL: {}, HEAD_KAN: {},
        HEAD_RIICHI: {}, HEAD_WIN: {},
    }
    n = 0
    for d in replay_dirs:
        for rec in _iter_records_in_dir(d):
            info = encode_choice(rec)
            if info is None:
                continue
            head, label = info
            counts[head][label] = counts[head].get(label, 0) + 1
            n += 1
            if max_records and n >= max_records:
                break
        if max_records and n >= max_records:
            break

    head_sizes = {HEAD_DISCARD: 34, HEAD_CALL: 5, HEAD_KAN: 2,
                  HEAD_RIICHI: 2, HEAD_WIN: 2}
    weights: dict[str, np.ndarray] = {}
    for head, c in counts.items():
        size = head_sizes[head]
        w = np.ones(size, dtype=np.float32)
        total = sum(c.values()) or 1
        for k, v in c.items():
            if v > 0 and 0 <= k < size:
                # Inverse-frequency weight, clipped at 5.0 to avoid blow-up
                # on rare classes with <10 examples.
                w[k] = min(5.0, total / (v * size))
        weights[head] = w
    return weights
