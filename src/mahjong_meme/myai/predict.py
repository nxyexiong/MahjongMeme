"""Inference adapter — turns a loaded MyAI checkpoint into a single
``recommend(state)`` call returning the recommended action plus top-k
alternatives.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F

from .actions import CALL_CLASSES
from .features import (
    NUM_PLANES, NUM_SCALARS, encode_state, index_34_to_tile, tile_to_index_34,
)
from .model import MyAI


class MyAIPredictor:
    """Stateless inference adapter."""

    def __init__(
        self,
        checkpoint_path: str | Path,
        *,
        device: str | None = None,
    ):
        ckpt = torch.load(Path(checkpoint_path), map_location="cpu")
        config = ckpt.get("config") or {}
        self.model = MyAI(channels=config.get("channels", 128),
                          num_blocks=config.get("blocks", 10))
        self.model.load_state_dict(ckpt["model_state"])
        self.model.eval()
        self.device = torch.device(device or (
            "cuda" if torch.cuda.is_available() else "cpu"))
        self.model.to(self.device)

    @torch.no_grad()
    def recommend(self, state: dict, *, trainer_eval=None, topk: int = 3) -> dict:
        """Return ``{"head", "action", "prob", "topk"}`` for ``state``.

        - Picks the active head from ``state.actionable.options[]``;
          returns ``{"head": None, "action": {"action": "skip"}, ...}``
          when there's nothing to decide.
        - Masks illegal actions via the legal-options list before
          softmax so the model never recommends an impossible move.
        """
        enc = encode_state(state, trainer_eval=trainer_eval)
        active_head = _pick_active_head(enc["mask"], state)
        if active_head is None:
            return {"head": None,
                    "action": {"action": "skip"},
                    "prob": 1.0,
                    "topk": []}

        planes = torch.from_numpy(enc["planes"]).unsqueeze(0).to(self.device)
        scalars = torch.from_numpy(enc["scalars"]).unsqueeze(0).to(self.device)
        logits = self.model(planes, scalars)
        head_logits = logits[active_head].squeeze(0)        # (head_size,)

        legal_mask = _legal_mask_for_head(active_head, state)
        head_logits = head_logits.masked_fill(~legal_mask, -1e9)
        probs = F.softmax(head_logits, dim=-1).cpu().numpy()

        k = min(topk, int(legal_mask.sum().item()) or 1)
        order = np.argsort(-probs)[:k]
        topk_actions = [(_decode_action(active_head, int(i), state),
                         float(probs[i])) for i in order if probs[i] > 0]

        best_idx = int(order[0])
        return {
            "head":   active_head,
            "action": _decode_action(active_head, best_idx, state),
            "prob":   float(probs[best_idx]),
            "topk":   topk_actions,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pick_active_head(mask: dict[str, bool], state: dict) -> Optional[str]:
    """Priority same as the trainer: win > call > kan > riichi > discard."""
    for head in ("win", "call", "kan", "riichi", "discard"):
        if mask.get(head):
            return head
    return None


def _legal_mask_for_head(head: str, state: dict) -> torch.Tensor:
    """Boolean tensor marking which class indices are LEGAL right now."""
    options = ((state.get("actionable") or {}).get("options") or [])
    if head == "discard":
        m = torch.zeros(34, dtype=torch.bool)
        for opt in options:
            if (opt or {}).get("action") == "discard":
                tile = opt.get("tile")
                try:
                    # Red fives collapse to the normal five cell so the
                    # head outputs a single logit per tile-type.
                    norm = tile[:-1] if tile and tile.endswith("*") else tile
                    m[tile_to_index_34(norm)] = True
                except (ValueError, TypeError):
                    continue
        return m
    if head == "call":
        m = torch.zeros(5, dtype=torch.bool)
        last = (state.get("match") or {}).get("last_discard") or {}
        for opt in options:
            a = (opt or {}).get("action")
            if a == "pon":
                m[CALL_CLASSES.index("pon")] = True
            elif a == "chi":
                pos = _chi_label_for_option(opt, last)
                if pos is not None:
                    m[pos] = True
        m[CALL_CLASSES.index("pass")] = True
        return m
    if head == "kan":
        m = torch.zeros(2, dtype=torch.bool)
        if any((o or {}).get("action") == "kan" for o in options):
            m[0] = True
        m[1] = True
        return m
    if head == "riichi":
        m = torch.zeros(2, dtype=torch.bool)
        if any((o or {}).get("action") == "lizhi" for o in options):
            m[0] = True
        m[1] = True
        return m
    if head == "win":
        m = torch.zeros(2, dtype=torch.bool)
        if any((o or {}).get("action") in ("hu", "zimo") for o in options):
            m[0] = True
        m[1] = True
        return m
    raise ValueError(head)


def _chi_label_for_option(opt: dict, last_discard: dict) -> Optional[int]:
    """Map a single chi option onto the chi_low/mid/high label."""
    extras = (opt or {}).get("extra") or {}
    partners = extras.get("partner_tiles") or []
    tile = (last_discard or {}).get("tile")
    if not (partners and tile):
        return None
    def _rank(t):
        t = t[:-1] if t.endswith("*") else t
        if len(t) != 2 or t[1] not in "mps":
            return None
        try:
            return int(t[0])
        except ValueError:
            return None
    called_r = _rank(tile)
    if called_r is None:
        return None
    ranks = sorted([r for r in (_rank(p) for p in partners) if r is not None]
                   + [called_r])
    if called_r == ranks[0]:
        return CALL_CLASSES.index("chi_low")
    if called_r == ranks[-1]:
        return CALL_CLASSES.index("chi_high")
    return CALL_CLASSES.index("chi_mid")


def _decode_action(head: str, idx: int, state: dict) -> dict:
    options = ((state.get("actionable") or {}).get("options") or [])
    if head == "discard":
        tile = index_34_to_tile(idx)
        # Prefer the actual slot-bearing option if present. Red fives
        # collapse to their normal-five cell in head logits, so when
        # picking index 4/13/22 we also accept the '5m*'/'5p*'/'5s*'
        # option if the normal copy isn't in the hand.
        for opt in options:
            if (opt or {}).get("action") == "discard" and opt.get("tile") == tile:
                return {"action": "discard", "tile": tile,
                        "slot": opt.get("slot")}
        # Fall back to the red variant when the normal is unavailable.
        red_tile = tile + "*" if tile in ("5m", "5p", "5s") else None
        if red_tile:
            for opt in options:
                if (opt or {}).get("action") == "discard" and opt.get("tile") == red_tile:
                    return {"action": "discard", "tile": red_tile,
                            "slot": opt.get("slot")}
        return {"action": "discard", "tile": tile}
    if head == "call":
        cls = CALL_CLASSES[idx]
        if cls == "pass":
            return {"action": "skip"}
        if cls == "pon":
            return {"action": "pon"}
        # chi_{low,mid,high}
        return {"action": "chi", "extra": {"position": cls}}
    if head == "kan":
        return {"action": "kan"} if idx == 0 else {"action": "skip"}
    if head == "riichi":
        return {"action": "lizhi"} if idx == 0 else {"action": "skip"}
    if head == "win":
        return {"action": "hu"} if idx == 0 else {"action": "skip"}
    return {"action": "skip"}
