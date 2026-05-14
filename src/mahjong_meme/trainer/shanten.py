"""Shanten calculator — port of Riichi-Trainer's ShantenCalculator.js."""
from __future__ import annotations

from typing import Callable, Sequence

from .tiles import HAND_SIZE, merge_red_fives

ShantenFunction = Callable[..., int]


def calculate_chiitoitsu_shanten(hand: Sequence[int]) -> int:
    """Shanten to a seven-pairs hand."""
    merged = merge_red_fives(hand)
    pair_count = 0
    unique_tiles = 0
    for i in range(1, HAND_SIZE):
        if merged[i] == 0:
            continue
        unique_tiles += 1
        if merged[i] >= 2:
            pair_count += 1
    shanten = 6 - pair_count
    if unique_tiles < 7:
        shanten += 7 - unique_tiles
    return shanten


def calculate_kokushi_shanten(hand: Sequence[int]) -> int:
    """Shanten to a thirteen-orphans hand."""
    unique_tiles = 0
    has_pair = 0
    for i in range(1, HAND_SIZE):
        if i == 30:
            continue
        is_term_msp = i < 30 and (i % 10 == 1 or i % 10 == 9)
        is_honor = i > 30
        if not (is_term_msp or is_honor):
            continue
        if hand[i] != 0:
            unique_tiles += 1
            if hand[i] >= 2:
                has_pair = 1
    return 13 - unique_tiles - has_pair


class _StandardShantenState:
    __slots__ = (
        "hand",
        "complete_sets",
        "pair",
        "partial_sets",
        "best_shanten",
        "minimum_shanten",
        "has_given_minimum",
    )

    def __init__(self, hand: list[int], minimum_shanten: int, has_given_minimum: bool):
        self.hand = hand
        self.complete_sets = 0
        self.pair = 0
        self.partial_sets = 0
        self.best_shanten = 8
        self.minimum_shanten = minimum_shanten
        self.has_given_minimum = has_given_minimum


def _remove_completed_sets(state: _StandardShantenState, i: int) -> None:
    if state.best_shanten <= state.minimum_shanten:
        return
    h = state.hand
    while i < HAND_SIZE and h[i] == 0:
        i += 1
    if i >= HAND_SIZE:
        _remove_potential_sets(state, 1)
        return
    if h[i] >= 3:
        state.complete_sets += 1
        h[i] -= 3
        _remove_completed_sets(state, i)
        h[i] += 3
        state.complete_sets -= 1
    if i < 30 and h[i + 1] != 0 and h[i + 2] != 0:
        state.complete_sets += 1
        h[i] -= 1
        h[i + 1] -= 1
        h[i + 2] -= 1
        _remove_completed_sets(state, i)
        h[i] += 1
        h[i + 1] += 1
        h[i + 2] += 1
        state.complete_sets -= 1
    _remove_completed_sets(state, i + 1)


def _remove_potential_sets(state: _StandardShantenState, i: int) -> None:
    if state.best_shanten <= state.minimum_shanten:
        return
    if state.has_given_minimum and state.complete_sets < 3 - state.minimum_shanten:
        return
    h = state.hand
    while i < HAND_SIZE and h[i] == 0:
        i += 1
    if i >= HAND_SIZE:
        current = 8 - state.complete_sets * 2 - state.partial_sets - state.pair
        if current < state.best_shanten:
            state.best_shanten = current
        return
    if state.complete_sets + state.partial_sets < 4:
        if h[i] == 2:
            state.partial_sets += 1
            h[i] -= 2
            _remove_potential_sets(state, i)
            h[i] += 2
            state.partial_sets -= 1
        if i < 30 and h[i + 1] != 0:
            state.partial_sets += 1
            h[i] -= 1
            h[i + 1] -= 1
            _remove_potential_sets(state, i)
            h[i] += 1
            h[i + 1] += 1
            state.partial_sets -= 1
        if i < 30 and i % 10 <= 8 and h[i + 2] != 0:
            state.partial_sets += 1
            h[i] -= 1
            h[i + 2] -= 1
            _remove_potential_sets(state, i)
            h[i] += 1
            h[i + 2] += 1
            state.partial_sets -= 1
    _remove_potential_sets(state, i + 1)


def calculate_standard_shanten(hand: Sequence[int], minimum_shanten: int = -2) -> int:
    has_given_minimum = True
    if minimum_shanten == -2:
        has_given_minimum = False
        minimum_shanten = -1

    h = merge_red_fives(hand)
    state = _StandardShantenState(h, minimum_shanten, has_given_minimum)

    for i in range(1, HAND_SIZE):
        if h[i] >= 2:
            state.pair += 1
            h[i] -= 2
            _remove_completed_sets(state, 1)
            h[i] += 2
            state.pair -= 1
    _remove_completed_sets(state, 1)

    return state.best_shanten


def calculate_minimum_shanten(hand: Sequence[int], minimum_shanten: int = -2) -> int:
    chiitoi = calculate_chiitoitsu_shanten(hand)
    if chiitoi < 0:
        return chiitoi
    kokushi = calculate_kokushi_shanten(hand)
    if kokushi < 3:
        return kokushi
    standard = calculate_standard_shanten(hand, minimum_shanten)
    return min(standard, chiitoi, kokushi)
