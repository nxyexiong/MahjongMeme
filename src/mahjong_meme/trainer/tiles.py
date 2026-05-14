"""Tile encoding for the trainer.

The encoding is identical to Riichi-Trainer's (third_party/Riichi-Trainer/
src/Constants.js + TileConversions.js):

- 38-slot array. Indices:
    0       = red 5m
    1..9    = 1m..9m
    10      = red 5p
    11..19  = 1p..9p
    20      = red 5s
    21..29  = 1s..9s
    30      = unused buffer
    31..37  = 1z..7z (E, S, W, N, 白, 發, 中)

String tile names accepted/produced:
    'Nm', 'Np', 'Ns'         — number tiles (N = 1..9)
    'Nz'                     — honors (1z..7z)
    Trailing '*' on a 5      — red five (e.g. '5m*', '5p*', '5s*')
"""
from __future__ import annotations

from typing import Iterable, Sequence

HAND_SIZE = 38

NORMAL_TILE_INDICES: tuple[int, ...] = tuple(
    i for i in range(1, HAND_SIZE) if i != 30 and i % 10 != 0
)

ALL_TILES_REMAINING: tuple[int, ...] = (
    0, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    0, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    0, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    0, 4, 4, 4, 4, 4, 4, 4,
)

_SUIT_BASE = {"m": 0, "p": 10, "s": 20, "z": 30}
_SUIT_FOR_BASE = {0: "m", 10: "p", 20: "s", 30: "z"}


def parse_tile(name: str) -> int:
    """Parse a tile string like '5m', '5m*', '3z' into a 38-slot index."""
    s = name.strip()
    if len(s) < 2:
        raise ValueError(f"invalid tile name {name!r}")
    red = s.endswith("*")
    if red:
        s = s[:-1]
    if len(s) != 2:
        raise ValueError(f"invalid tile name {name!r}")
    v_str, suit = s[0], s[1]
    if suit not in _SUIT_BASE:
        raise ValueError(f"invalid tile suit in {name!r}")
    try:
        v = int(v_str)
    except ValueError as e:
        raise ValueError(f"invalid tile value in {name!r}") from e
    if suit == "z":
        if not 1 <= v <= 7:
            raise ValueError(f"honor out of range in {name!r}")
        if red:
            raise ValueError(f"honor cannot be a red five: {name!r}")
        return 30 + v
    if not 1 <= v <= 9:
        raise ValueError(f"number tile out of range in {name!r}")
    if red:
        if v != 5:
            raise ValueError(f"only 5 may be red, got {name!r}")
        return _SUIT_BASE[suit]
    return _SUIT_BASE[suit] + v


def format_tile(index: int, *, red_marker: bool = True) -> str:
    """Render a 38-slot index as a string. Red fives get the '*' marker."""
    if not 0 <= index < HAND_SIZE:
        raise ValueError(f"tile index {index} out of range")
    if index == 30:
        raise ValueError("index 30 is the buffer slot, not a tile")
    if index in (0, 10, 20):
        suit = _SUIT_FOR_BASE[index]
        return "5" + suit + ("*" if red_marker else "")
    base = (index // 10) * 10
    v = index % 10
    suit = _SUIT_FOR_BASE[base]
    return f"{v}{suit}"


def tile_counts(tiles: Iterable[str]) -> list[int]:
    """Build a 38-slot count vector from an iterable of tile strings."""
    counts = [0] * HAND_SIZE
    for t in tiles:
        idx = parse_tile(t)
        counts[idx] += 1
    return counts


def merge_red_fives(counts: Sequence[int]) -> list[int]:
    """Return a copy of `counts` with reds folded into the normal-five slot."""
    if len(counts) != HAND_SIZE:
        raise ValueError(f"expected {HAND_SIZE}-slot counts, got {len(counts)}")
    out = list(counts)
    for i in (0, 10, 20):
        if out[i]:
            out[i + 5] += out[i]
            out[i] = 0
    return out


def is_terminal_or_honor(index: int) -> bool:
    if index >= 31:
        return True
    if index in (0, 10, 20, 30):
        return False
    v = index % 10
    return v == 1 or v == 9


def dora_from_indicator(indicator: int) -> int:
    """Convert a dora indicator tile to the actual dora tile."""
    if indicator in (0, 10, 20):
        indicator += 5
    if indicator == 30:
        raise ValueError("buffer slot is not a valid dora indicator")
    if indicator < 30:
        base = (indicator // 10) * 10
        v = indicator % 10
        return base + (1 if v == 9 else v + 1)
    if 31 <= indicator <= 34:
        return 31 + ((indicator - 31 + 1) % 4)
    if 35 <= indicator <= 37:
        return 35 + ((indicator - 35 + 1) % 3)
    raise ValueError(f"invalid indicator {indicator}")
