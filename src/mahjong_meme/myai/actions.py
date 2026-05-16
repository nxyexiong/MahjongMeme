"""Action / label encoder for the 5 model heads."""
from __future__ import annotations

from typing import Optional

from .features import tile_to_index_34


HEAD_DISCARD = "discard"
HEAD_CALL = "call"
HEAD_KAN = "kan"
HEAD_RIICHI = "riichi"
HEAD_WIN = "win"

CALL_CLASSES = ("chi_low", "chi_mid", "chi_high", "pon", "pass")
CALL_CLASS_INDEX = {c: i for i, c in enumerate(CALL_CLASSES)}


def _norm_red(s: str) -> str:
    return s[:-1] if s and s.endswith("*") else s


def _rank_of(tile: str) -> Optional[int]:
    """1..9 for numbered tiles; None for honors / invalid."""
    t = _norm_red(tile)
    if len(t) != 2 or t[1] not in ("m", "p", "s"):
        return None
    try:
        return int(t[0])
    except ValueError:
        return None


def _chi_position(choice: dict, last_discard: Optional[dict]) -> int:
    """chi_low / chi_mid / chi_high label, based on where in the run the
    called tile sits."""
    extras = (choice or {}).get("extra") or {}
    tiles = extras.get("tiles") or []
    if not tiles or not isinstance(last_discard, dict):
        return CALL_CLASS_INDEX["chi_mid"]
    called = last_discard.get("tile")
    if not called:
        return CALL_CLASS_INDEX["chi_mid"]
    called_rank = _rank_of(called)
    if called_rank is None:
        return CALL_CLASS_INDEX["chi_mid"]
    ranks: list[int] = []
    for t in tiles:
        r = _rank_of(t)
        if r is None:
            return CALL_CLASS_INDEX["chi_mid"]
        ranks.append(r)
    ranks.sort()
    if called_rank == ranks[0]:
        return CALL_CLASS_INDEX["chi_low"]
    if called_rank == ranks[2]:
        return CALL_CLASS_INDEX["chi_high"]
    return CALL_CLASS_INDEX["chi_mid"]


def encode_choice(record: dict) -> Optional[tuple[str, int]]:
    """Return ``(head_name, label_int)`` for a replay record, or None.

    None means this record has no supervised signal (drop from training).
    """
    if not isinstance(record, dict):
        return None
    choice = record.get("choice") or {}
    state = record.get("state") or {}
    actionable = state.get("actionable") or {}
    options = actionable.get("options") or []
    action = choice.get("action")
    last_discard = (state.get("match") or {}).get("last_discard")

    if action == "discard":
        tile = choice.get("tile")
        if not tile:
            return None
        try:
            return (HEAD_DISCARD, tile_to_index_34(tile))
        except ValueError:
            return None
    if action == "chi":
        return (HEAD_CALL, _chi_position(choice, last_discard))
    if action == "pon":
        return (HEAD_CALL, CALL_CLASS_INDEX["pon"])
    if action == "kan":
        return (HEAD_KAN, 0)
    if action == "lizhi":
        return (HEAD_RIICHI, 0)
    if action in ("hu", "zimo"):
        return (HEAD_WIN, 0)

    if action == "skip":
        head = _head_from_options(options)
        if head is None:
            return None
        if head == HEAD_DISCARD:
            # T-event post-draw observer record; the real choice is at
            # the NEXT event. Drop to avoid double-counting.
            return None
        if head == HEAD_CALL:
            return (HEAD_CALL, CALL_CLASS_INDEX["pass"])
        if head == HEAD_KAN:
            return (HEAD_KAN, 1)
        if head == HEAD_RIICHI:
            return (HEAD_RIICHI, 1)
        if head == HEAD_WIN:
            return (HEAD_WIN, 1)

    return None


def _head_from_options(options: list[dict]) -> Optional[str]:
    """Decide which head the options correspond to. Priority follows the
    live state-machine: win > call > kan > riichi > discard."""
    if any((o or {}).get("action") in ("hu", "zimo") for o in options):
        return HEAD_WIN
    if any((o or {}).get("action") in ("chi", "pon") for o in options):
        return HEAD_CALL
    if any((o or {}).get("action") == "kan" for o in options):
        return HEAD_KAN
    if any((o or {}).get("action") == "lizhi" for o in options):
        return HEAD_RIICHI
    if any((o or {}).get("action") == "discard" for o in options):
        return HEAD_DISCARD
    return None
