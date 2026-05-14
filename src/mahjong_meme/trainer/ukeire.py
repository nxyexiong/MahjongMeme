"""Ukeire calculator — port of Riichi-Trainer's UkeireCalculator.js."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .evaluations import evaluate_best_discard
from .shanten import ShantenFunction
from .tiles import HAND_SIZE, merge_red_fives


@dataclass
class UkeireResult:
    value: int = 0
    tiles: list[int] = field(default_factory=list)


@dataclass
class UpgradeTile:
    tile: int
    discard: int
    count: int
    resulting_ukeire: int


@dataclass
class UpgradeResult:
    value: int = 0
    tiles: list[UpgradeTile] = field(default_factory=list)


def calculate_ukeire(
    hand: Sequence[int],
    remaining_tiles: Sequence[int],
    shanten_function: ShantenFunction,
    base_shanten: int = -2,
) -> UkeireResult:
    converted_hand = merge_red_fives(hand)
    converted_tiles = merge_red_fives(remaining_tiles)

    if base_shanten == -2:
        base_shanten = shanten_function(converted_hand)

    value = 0
    tiles: list[int] = []

    for added in range(1, HAND_SIZE):
        if added == 30:
            continue
        if added % 10 == 0:
            continue
        if remaining_tiles[added] == 0:
            continue
        converted_hand[added] += 1
        if shanten_function(converted_hand, base_shanten - 1) < base_shanten:
            value += converted_tiles[added]
            tiles.append(added)
        converted_hand[added] -= 1

    return UkeireResult(value=value, tiles=tiles)


def calculate_discard_ukeire(
    hand: Sequence[int],
    remaining_tiles: Sequence[int],
    shanten_function: ShantenFunction,
    base_shanten: int = -2,
) -> list[UkeireResult]:
    results: list[UkeireResult] = [UkeireResult() for _ in range(HAND_SIZE)]
    converted_hand = merge_red_fives(hand)

    if base_shanten == -2:
        base_shanten = shanten_function(converted_hand)

    for hand_index in range(HAND_SIZE):
        if converted_hand[hand_index] == 0:
            results[hand_index] = UkeireResult(value=0, tiles=[])
            continue
        converted_hand[hand_index] -= 1
        ukeire = calculate_ukeire(
            converted_hand, remaining_tiles, shanten_function, base_shanten
        )
        converted_hand[hand_index] += 1
        results[hand_index] = ukeire

    return results


def calculate_ukeire_upgrades(
    hand: Sequence[int],
    remaining_tiles: Sequence[int],
    shanten_function: ShantenFunction,
    base_shanten: int = -2,
    base_ukeire: int = -1,
) -> UpgradeResult:
    converted_hand = merge_red_fives(hand)
    converted_tiles = merge_red_fives(remaining_tiles)
    remaining = list(remaining_tiles)

    if base_shanten == -2:
        base_shanten = shanten_function(converted_hand)

    if base_ukeire == -1:
        base_ukeire = calculate_ukeire(
            converted_hand, remaining_tiles, shanten_function, base_shanten
        ).value

    value = 0
    tiles: list[UpgradeTile] = []

    for added in range(1, HAND_SIZE):
        if added == 30:
            continue
        if added % 10 == 0:
            continue
        if remaining[added] == 0:
            continue

        converted_hand[added] += 1
        remaining[added] -= 1

        if (
            shanten_function(converted_hand, base_shanten - 1) == base_shanten
            and calculate_ukeire(
                converted_hand, remaining, shanten_function, base_shanten
            ).value
            > base_ukeire
        ):
            discards = calculate_discard_ukeire(
                converted_hand, remaining, shanten_function, base_shanten
            )
            best_discard = evaluate_best_discard([d.value for d in discards])

            if added != best_discard and best_discard >= 0:
                converted_hand[best_discard] -= 1
                new_ukeire = calculate_ukeire(
                    converted_hand, remaining, shanten_function, base_shanten
                ).value
                if new_ukeire > base_ukeire:
                    value += converted_tiles[added]
                    tiles.append(
                        UpgradeTile(
                            tile=added,
                            discard=best_discard,
                            count=converted_tiles[added],
                            resulting_ukeire=new_ukeire,
                        )
                    )
                converted_hand[best_discard] += 1

        converted_hand[added] -= 1
        remaining[added] += 1

    return UpgradeResult(value=value, tiles=tiles)


def calculate_ukeire_from_only_hand(
    hand: Sequence[int],
    existing_tiles: Sequence[int],
    shanten_function: ShantenFunction,
) -> UkeireResult:
    converted_hand = merge_red_fives(hand)
    remaining = merge_red_fives(existing_tiles)
    for i in range(HAND_SIZE):
        remaining[i] = max(0, remaining[i] - converted_hand[i])
    return calculate_ukeire(converted_hand, remaining, shanten_function)
