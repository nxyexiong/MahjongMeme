"""Evaluation helpers — port of Riichi-Trainer's Evaluations.js."""
from __future__ import annotations

import random
from typing import Sequence

from .tiles import HAND_SIZE

_PREFER_ORDER_HONORS: tuple[int, ...] = (32, 33, 34, 31, 35, 36, 37)


def evaluate_best_discard(ukeire_values: Sequence[int], dora: int = -1) -> int:
    """Pick the best tile-index to discard given the ukeire per slot.

    Returns the chosen index, or -1 if no discard is available. Ties are
    broken by preferring honors → terminals → 2/8s → random 3..7.
    """
    if not ukeire_values:
        return -1
    best_ukeire = max(ukeire_values)
    bests = [i for i, v in enumerate(ukeire_values) if v == best_ukeire]
    if not bests:
        return -1
    if len(bests) == 1:
        return bests[0]

    if dora in bests:
        bests = [b for b in bests if b != dora]
        if not bests:
            return dora
        if len(bests) == 1:
            return bests[0]

    for honor in _PREFER_ORDER_HONORS:
        if honor in bests:
            return honor

    for offset in (1, 9):
        for suit_base in (0, 10, 20):
            t = suit_base + offset
            if t in bests:
                return t

    for offset in (2, 8):
        for suit_base in (0, 10, 20):
            t = suit_base + offset
            if t in bests:
                return t

    return random.choice(bests)


def evaluate_discard_safety(
    hand: Sequence[int],
    opponent_discards: Sequence[int],
    remaining_tiles: Sequence[int],
    tiles_discarded_after_riichi: Sequence[int],
    riichi_tile: int = -1,
) -> list[int]:
    """Return a 38-element list of safety ranks (0..15) for each tile in hand."""
    safety = [0] * HAND_SIZE
    op_set = set(opponent_discards)
    riichi_set = set(tiles_discarded_after_riichi)

    for i in range(HAND_SIZE):
        if hand[i] <= 0:
            continue

        if i in op_set or i in riichi_set:
            safety[i] = 15
            continue

        if i < 30 and i % 10 in (1, 9):
            if _check_is_suji(i, op_set, remaining_tiles, riichi_tile):
                rem = remaining_tiles[i] if 0 <= i < len(remaining_tiles) else 0
                safety[i] = 14 - rem
            else:
                safety[i] = 5
            continue

        if i > 30:
            rem = remaining_tiles[i] if 0 <= i < len(remaining_tiles) else 0
            if rem == 0:
                safety[i] = 14
            elif rem == 1:
                safety[i] = 13
            elif rem == 2:
                safety[i] = 10
            else:
                safety[i] = 6
            continue

        if _check_is_suji(i, op_set, remaining_tiles, riichi_tile):
            v = i % 10
            if v in (4, 5, 6):
                safety[i] = 9
            elif v in (2, 8):
                safety[i] = 8
            else:
                safety[i] = 7
        else:
            v = i % 10
            if v in (4, 5, 6):
                safety[i] = 1
            elif v in (2, 8):
                safety[i] = 3
            else:
                safety[i] = 2

    return safety


def _check_is_suji(
    tile: int,
    opponent_discards: set[int],
    remaining_tiles: Sequence[int],
    riichi_tile: int,
) -> bool:
    suji_a = tile - 3
    suji_b = tile + 3
    suji_a_passed = False
    suji_b_passed = False

    if suji_a % 10 == 0 or (suji_a // 10) != (tile // 10):
        suji_a_passed = True
    else:
        if suji_a == riichi_tile:
            return False
        suji_a_passed = (
            suji_a in opponent_discards
            or remaining_tiles[suji_a + 1] == 0
            or remaining_tiles[suji_a + 2] == 0
        )

    if suji_b % 10 == 0 or (suji_b // 10) != (tile // 10):
        suji_b_passed = True
    else:
        if suji_b == riichi_tile:
            return False
        suji_b_passed = (
            suji_b in opponent_discards
            or remaining_tiles[suji_b - 1] == 0
            or remaining_tiles[suji_b - 2] == 0
        )

    return suji_a_passed and suji_b_passed
