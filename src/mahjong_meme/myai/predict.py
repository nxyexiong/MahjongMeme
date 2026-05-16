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
    def recommend(self, state: dict, *, trainer_eval=None, topk: int = 5) -> dict:
        """Return ranked candidates across all applicable heads for ``state``.

        For each legal action we compute a score and surface the top-K
        across heads in one unified list. Cross-head probabilities use a
        Bayesian-style joint formulation:

            P(riichi+tile)  = P(riichi) * P(tile | discard-head)
            P(discard+tile) = P(pass-on-riichi) * P(tile | discard-head)
              (when riichi is also legal — i.e. the state has both heads)

        This eliminates the inconsistency where the riichi head's
        near-50/50 binary flip would swing the entire recommendation
        between "skip" and "riichi". Now the same input always yields
        the same ordering, and the riichi suggestion always carries the
        companion tile to declare on.

        Returns
        -------
        dict with keys:
            head : str | None
                Active head of the #1 candidate (for backward compat).
            action : dict
                Top-1 action dict.
            prob : float
                Top-1 joint probability.
            topk : list[(action, prob)]
                Up to ``topk`` candidates, sorted by descending prob.
        """
        enc = encode_state(state, trainer_eval=trainer_eval)
        applicable = _applicable_heads(enc["mask"])
        if not applicable:
            return {"head": None,
                    "action": {"action": "skip"},
                    "prob": 1.0,
                    "topk": []}

        planes = torch.from_numpy(enc["planes"]).unsqueeze(0).to(self.device)
        scalars = torch.from_numpy(enc["scalars"]).unsqueeze(0).to(self.device)
        logits = self.model(planes, scalars)

        # Probabilities per head (masked to legal classes).
        probs_by_head: dict[str, np.ndarray] = {}
        for head in applicable:
            head_logits = logits[head].squeeze(0)
            legal_mask = _legal_mask_for_head(head, state).to(head_logits.device)
            head_logits = head_logits.masked_fill(~legal_mask, -1e9)
            probs_by_head[head] = F.softmax(head_logits, dim=-1).cpu().numpy()

        candidates = _build_candidates(probs_by_head, state)
        if not candidates:
            return {"head": None,
                    "action": {"action": "skip"},
                    "prob": 1.0,
                    "topk": []}

        # Sort by joint probability, take top-K.
        candidates.sort(key=lambda c: c["prob"], reverse=True)
        k = max(1, int(topk))
        top = candidates[:k]
        best = top[0]
        return {
            "head":   best["head"],
            "action": best["action"],
            "prob":   best["prob"],
            "topk":   [(c["action"], c["prob"]) for c in top],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _applicable_heads(mask: dict[str, bool]) -> list[str]:
    """Heads with at least one legal action in this state."""
    return [h for h in ("discard", "call", "kan", "riichi", "win") if mask.get(h)]


def _build_candidates(
    probs_by_head: dict[str, np.ndarray],
    state: dict,
) -> list[dict]:
    """Build the unified candidate list combining all applicable heads.

    When riichi is legal alongside discard, we collapse them into joint
    "riichi+tile" / "discard+tile" candidates so each candidate fully
    specifies what to do (riichi requires picking a tile to declare on).
    """
    candidates: list[dict] = []
    options = ((state.get("actionable") or {}).get("options") or [])

    discard_probs = probs_by_head.get("discard")
    riichi_probs = probs_by_head.get("riichi")
    call_probs = probs_by_head.get("call")
    kan_probs = probs_by_head.get("kan")
    win_probs = probs_by_head.get("win")

    # --- Win / call / kan are mutually exclusive of discard at the
    # same decision point in normal play, so we surface each head's
    # legal classes directly.

    if win_probs is not None:
        for idx, p in _ranked(win_probs):
            if idx == 0:  # win
                candidates.append({"head": "win", "prob": float(p),
                                    "action": _decode_action("win", 0, state)})
            else:         # pass
                candidates.append({"head": "win", "prob": float(p),
                                    "action": _decode_action("win", 1, state)})

    if call_probs is not None:
        for idx, p in _ranked(call_probs):
            if p <= 0:
                continue
            candidates.append({"head": "call", "prob": float(p),
                                "action": _decode_action("call", int(idx), state)})

    if kan_probs is not None:
        # Per-tile expansion: a "kan yes" decision needs to specify WHICH
        # tile. We read the legal kan options from state.actionable.options
        # so the candidates carry the real tile/subtype the game expects.
        kan_options = _kan_options_from_state(state)
        p_kan = float(kan_probs[0])
        p_no_kan = float(kan_probs[1])
        if kan_options:
            # Distribute P(kan) across the legal kan options. If multiple
            # ankan tiles are available, weight equally — the model
            # doesn't have a per-tile kan head, so this is the best we
            # can do without retraining with a richer head.
            n = len(kan_options)
            for opt in kan_options:
                candidates.append({
                    "head": "kan",
                    "prob": p_kan / n,
                    "action": opt,
                })
        else:
            # No specific options surfaced (shouldn't happen) — emit the
            # binary head as-is for diagnostics.
            for idx, p in _ranked(kan_probs):
                candidates.append({"head": "kan", "prob": float(p),
                                    "action": _decode_action("kan", int(idx), state)})
        # Always include the "no kan" candidate so the panel can show
        # passing on a kan as an alternative.
        if kan_options:
            candidates.append({
                "head": "kan",
                "prob": p_no_kan,
                "action": {"action": "skip"},
            })

    # --- Discard + riichi share the same decision moment ---------------
    # If riichi is legal: each candidate is (riichi-yes/no) × (discard tile).
    # If riichi is NOT legal: each candidate is just a discard tile.
    # If discard is NOT legal but riichi IS (the riichi confirmation
    # event with options=['lizhi','pass']): surface the binary head as-is.

    if discard_probs is not None:
        ranked_tiles = [(int(i), float(p)) for i, p in _ranked(discard_probs)
                        if p > 0]
        if riichi_probs is not None:
            p_riichi = float(riichi_probs[0])
            p_pass   = float(riichi_probs[1])
            for tile_idx, p_tile in ranked_tiles:
                discard_action = _decode_action("discard", tile_idx, state)
                tile = discard_action.get("tile", index_34_to_tile(tile_idx))
                # Riichi-on-this-tile candidate.
                candidates.append({
                    "head": "riichi",
                    "prob": p_riichi * p_tile,
                    "action": {"action": "lizhi", "tile": tile,
                                "slot": discard_action.get("slot"),
                                "extra": {"declare_on": tile}},
                })
                # Plain-discard-this-tile candidate.
                candidates.append({
                    "head": "discard",
                    "prob": p_pass * p_tile,
                    "action": discard_action,
                })
        else:
            for tile_idx, p_tile in ranked_tiles:
                candidates.append({
                    "head": "discard",
                    "prob": p_tile,
                    "action": _decode_action("discard", tile_idx, state),
                })
    elif riichi_probs is not None:
        # Riichi-confirmation event (options=['lizhi','pass']): no tile to
        # pick here — emit the binary head directly.
        for idx, p in _ranked(riichi_probs):
            candidates.append({"head": "riichi", "prob": float(p),
                                "action": _decode_action("riichi", int(idx), state)})

    return candidates


def _partners_for_position(position: str, hand: list[str],
                            called: str) -> list[str]:
    """Find the actual 2 partner tiles in ``hand`` for a chi position.

    Mirrors the inverse of ``_chi_positions_from_hand``. Returns the
    canonical (non-red) partner pair, or [] when not derivable.
    """
    if not called or not hand:
        return []
    raw = called[:-1] if called.endswith("*") else called
    if len(raw) != 2 or raw[1] not in "mps":
        return []
    try:
        v = int(raw[0])
    except ValueError:
        return []
    suit = raw[1]
    if position == "chi_low" and v + 2 <= 9:
        return [f"{v + 1}{suit}", f"{v + 2}{suit}"]
    if position == "chi_mid" and 1 <= v - 1 and v + 1 <= 9:
        return [f"{v - 1}{suit}", f"{v + 1}{suit}"]
    if position == "chi_high" and v - 2 >= 1:
        return [f"{v - 2}{suit}", f"{v - 1}{suit}"]
    return []


def _kan_options_from_state(state: dict) -> list[dict]:
    """Extract legal kan options from state.actionable.options as fully-
    specified action dicts (with tile + subtype). Returns [] if no kan
    options or if the options lack the needed tile info.
    """
    out: list[dict] = []
    options = ((state.get("actionable") or {}).get("options") or [])
    for opt in options:
        if (opt or {}).get("action") != "kan":
            continue
        extras = opt.get("extra") or {}
        subtype = extras.get("subtype")
        # Tile detection: prefer top-level "tile", fall back to first of
        # extra.tiles or extra.tile.
        tile = opt.get("tile") or extras.get("tile")
        if not tile:
            tiles = extras.get("tiles") or []
            if tiles:
                tile = tiles[0]
                if isinstance(tile, str) and tile.endswith("*"):
                    tile = tile[:-1]
        action: dict = {"action": "kan"}
        if tile:
            action["tile"] = tile
        if subtype or tile:
            action["extra"] = {k: v for k, v in
                                {"subtype": subtype, "tile": tile}.items()
                                if v is not None}
        out.append(action)
    return out


def _ranked(probs: np.ndarray):
    """Yield (idx, prob) pairs sorted by descending prob, skipping <=0."""
    order = np.argsort(-probs)
    for i in order:
        yield int(i), float(probs[int(i)])


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
        hand = (state.get("match") or {}).get("hand") or []
        for opt in options:
            a = (opt or {}).get("action")
            if a == "pon":
                m[CALL_CLASSES.index("pon")] = True
            elif a == "chi":
                pos = _chi_label_for_option(opt, last)
                if pos is not None:
                    m[pos] = True
                else:
                    # Live state doesn't carry explicit partner_tiles —
                    # infer all chi positions reachable from the hand.
                    for p in _chi_positions_from_hand(hand, last.get("tile") or ""):
                        m[p] = True
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


def _chi_label_for_option(opt: dict, last_discard: dict,
                          hand: list[str] | None = None) -> Optional[int]:
    """Map a single chi option onto the chi_low/mid/high label.

    Tries explicit ``extra.partner_tiles`` first (replay-parser format),
    then falls back to inferring partners from ``hand`` + the called
    tile (live-game format, where the JS side doesn't pre-compute
    partners and just emits {action: "chi"}).

    Returns a single label int when only one chi position is possible.
    When multiple chi positions are simultaneously legal (e.g. holding
    2m-3m-5m-6m and called 4m → low/mid/high all valid), we return None
    here and let the caller unmask all reachable positions via
    ``_chi_positions_from_hand``.
    """
    extras = (opt or {}).get("extra") or {}
    partners = extras.get("partner_tiles") or []
    tile = (last_discard or {}).get("tile")
    if not tile:
        return None

    def _rank(t):
        t = t[:-1] if isinstance(t, str) and t.endswith("*") else t
        if not isinstance(t, str) or len(t) != 2 or t[1] not in "mps":
            return None
        try:
            return int(t[0])
        except ValueError:
            return None

    called_r = _rank(tile)
    if called_r is None:
        return None

    if partners:
        ranks = sorted([r for r in (_rank(p) for p in partners) if r is not None]
                       + [called_r])
        if len(ranks) < 3:
            return None
        if called_r == ranks[0]:
            return CALL_CLASSES.index("chi_low")
        if called_r == ranks[-1]:
            return CALL_CLASSES.index("chi_high")
        return CALL_CLASSES.index("chi_mid")

    # No explicit partner_tiles — caller should use the multi-position
    # helper to enumerate all chi positions reachable from `hand`.
    return None


def _chi_positions_from_hand(hand: list[str],
                              called_tile: str) -> list[int]:
    """Return all chi position labels (chi_low/mid/high) legal given
    ``hand`` and the called tile. Used when the live state's chi option
    doesn't carry explicit partner tiles.

    A position is reachable when the hand contains the two partner
    tiles required (allowing red-five substitutes).
    """
    if not called_tile or not hand:
        return []
    raw = called_tile[:-1] if called_tile.endswith("*") else called_tile
    if len(raw) != 2 or raw[1] not in "mps":
        return []
    try:
        v = int(raw[0])
    except ValueError:
        return []
    suit = raw[1]

    def _norm(t):
        return t[:-1] if isinstance(t, str) and t.endswith("*") else t
    hand_norm = [_norm(t) for t in hand]

    out: list[int] = []
    # chi_low: called is the lowest → partners are (v+1, v+2).
    if v + 2 <= 9:
        a, b = f"{v + 1}{suit}", f"{v + 2}{suit}"
        if a in hand_norm and b in hand_norm:
            out.append(CALL_CLASSES.index("chi_low"))
    # chi_mid: called is the middle → partners are (v-1, v+1).
    if 1 <= v - 1 and v + 1 <= 9:
        a, b = f"{v - 1}{suit}", f"{v + 1}{suit}"
        if a in hand_norm and b in hand_norm:
            out.append(CALL_CLASSES.index("chi_mid"))
    # chi_high: called is the highest → partners are (v-2, v-1).
    if v - 2 >= 1:
        a, b = f"{v - 2}{suit}", f"{v - 1}{suit}"
        if a in hand_norm and b in hand_norm:
            out.append(CALL_CLASSES.index("chi_high"))
    return out


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
        # chi_{low,mid,high}: include the position so the live observer
        # can disambiguate when Mahjong Soul shows multiple chi buttons.
        # Also surface partner tiles for clarity in the panel.
        last = (state.get("match") or {}).get("last_discard") or {}
        hand = (state.get("match") or {}).get("hand") or []
        called = last.get("tile") or ""
        partners = _partners_for_position(cls, hand, called)
        extra: dict = {"position": cls}
        if partners:
            extra["partner_tiles"] = partners
        return {"action": "chi", "extra": extra}
    if head == "kan":
        return {"action": "kan"} if idx == 0 else {"action": "skip"}
    if head == "riichi":
        return {"action": "lizhi"} if idx == 0 else {"action": "skip"}
    if head == "win":
        return {"action": "hu"} if idx == 0 else {"action": "skip"}
    return {"action": "skip"}
