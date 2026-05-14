"""Stateless turn-evaluation entry point.

The surface mahjong_meme calls when the user has a discard decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .evaluations import evaluate_best_discard, evaluate_discard_safety
from .shanten import (
    calculate_chiitoitsu_shanten,
    calculate_kokushi_shanten,
    calculate_minimum_shanten,
    calculate_standard_shanten,
)
from .tiles import (
    ALL_TILES_REMAINING,
    HAND_SIZE,
    dora_from_indicator,
    format_tile,
    merge_red_fives,
    parse_tile,
)
from .ukeire import calculate_discard_ukeire, calculate_ukeire


@dataclass
class OpponentInfo:
    """One opponent's public information used for safety analysis."""

    discards: list[str] = field(default_factory=list)
    riichi_tile: str | None = None
    tiles_after_riichi: list[str] = field(default_factory=list)


@dataclass
class TileEval:
    """Evaluation of discarding one specific tile from hand."""

    tile: str
    index: int
    ukeire_count: int
    ukeire_tiles: list[str]
    safety_per_opponent: list[int] = field(default_factory=list)
    is_recommended: bool = False


@dataclass
class TurnEvaluation:
    """Full evaluation result for one decision point."""

    shanten: int
    shanten_standard: int
    shanten_chiitoi: int
    shanten_kokushi: int
    current_ukeire: int
    discards: list[TileEval]
    recommended_discard: str | None
    dora_tiles: list[str]
    visible_tile_total: int


def _counts_from_strings(strings: Iterable[str]) -> list[int]:
    counts = [0] * HAND_SIZE
    for t in strings:
        counts[parse_tile(t)] += 1
    return counts


def _format_normal(index: int) -> str:
    return format_tile(index, red_marker=False)


def _normalize_red(idx: int) -> int:
    if idx in (0, 10, 20):
        return idx + 5
    return idx


def evaluate_turn(
    hand: Sequence[str],
    *,
    visible_tiles: Sequence[str] = (),
    my_melds: Sequence[Sequence[str]] = (),
    dora_indicators: Sequence[str] = (),
    opponents: Sequence[OpponentInfo] = (),
) -> TurnEvaluation:
    """Evaluate one decision point.

    Parameters
    ----------
    hand
        The player's CONCEALED hand tile strings. Sizes by state:
            no melds:  13 between turns, 14 on your discard turn
            1 meld:    10 between turns, 11 on your discard turn
            2 melds:    7 between turns,  8 on your discard turn
            3 melds:    4 between turns,  5 on your discard turn
            4 melds:    1 between turns,  2 on your discard turn
        Red fives carry a trailing '*' (e.g. '5m*').
    visible_tiles
        All tile faces visible besides the concealed hand and your own
        called melds (which `my_melds` already covers). Typically:
        own discards + opponents' discards + opponents' called melds.
    my_melds
        Your own called sets (pon / chi / kan). Each is a list of tile
        strings. Affects two things: their tiles are added to visibility,
        and each meld is treated as one locked complete set when computing
        shanten (via Riichi-Trainer's East-wind padding trick). Chiitoitsu
        and kokushi shanten are disabled when any meld is present.
    dora_indicators
        Dora indicator tiles. Used for visibility AND for the
        recommended-discard tie-break (avoid discarding the dora).
    opponents
        Per-opponent public info for safety analysis. Order preserved.
    """
    if not hand:
        raise ValueError("hand is empty")

    n_called = len(my_melds)
    expected_pre = 13 - 3 * n_called
    expected_post = 14 - 3 * n_called
    if len(hand) not in (expected_pre, expected_post):
        raise ValueError(
            f"hand has {len(hand)} tiles with {n_called} called set(s); "
            f"expected {expected_pre} (between turns) or "
            f"{expected_post} (your discard turn)"
        )
    must_discard = len(hand) == expected_post

    hand_counts = _counts_from_strings(hand)
    merged_hand = merge_red_fives(hand_counts)

    # Visibility accumulator.
    visible_counts = [0] * HAND_SIZE
    visible_total = 0

    def add(strings: Iterable[str]) -> None:
        nonlocal visible_total
        for s in strings:
            visible_counts[parse_tile(s)] += 1
            visible_total += 1

    add(visible_tiles)
    for m in my_melds:
        add(m)
    add(dora_indicators)
    for i, c in enumerate(hand_counts):
        visible_counts[i] += c

    merged_visible = merge_red_fives(visible_counts)
    remaining = [
        max(0, ALL_TILES_REMAINING[i] - merged_visible[i]) for i in range(HAND_SIZE)
    ]

    # East-wind padding for shanten when melds are present. Each called set
    # adds 3 tiles to slot 31 (1z); the shanten algorithm then treats those
    # as a free pung. We track the padding separately so we can filter it
    # back out of the per-discard results.
    merged_padded = list(merged_hand)
    merged_padded[31] += 3 * n_called

    if n_called > 0:
        # Chiitoi/kokushi are invalid for open hands.
        shanten_standard = calculate_standard_shanten(merged_padded)
        shanten_chiitoi = 99
        shanten_kokushi = 99
        shanten_min = shanten_standard
        shanten_fn = calculate_standard_shanten
    else:
        shanten_standard = calculate_standard_shanten(merged_hand)
        shanten_chiitoi = calculate_chiitoitsu_shanten(merged_hand)
        shanten_kokushi = calculate_kokushi_shanten(merged_hand)
        shanten_min = min(shanten_standard, shanten_chiitoi, shanten_kokushi)
        shanten_fn = calculate_minimum_shanten

    dora_indices = [dora_from_indicator(parse_tile(t)) for t in dora_indicators]
    dora_tiles = [_format_normal(d) for d in dora_indices]
    primary_dora = dora_indices[0] if dora_indices else -1

    opp_inputs: list[tuple[list[int], list[int], int]] = []
    for opp in opponents:
        ds = [_normalize_red(parse_tile(t)) for t in opp.discards]
        ar = [_normalize_red(parse_tile(t)) for t in opp.tiles_after_riichi]
        rt = -1
        if opp.riichi_tile is not None:
            rt = _normalize_red(parse_tile(opp.riichi_tile))
        opp_inputs.append((ds, ar, rt))

    discards: list[TileEval] = []
    recommended: str | None = None
    current_ukeire = 0

    def _safety_for_tile(tile_idx: int) -> list[int]:
        out: list[int] = []
        any_in_riichi = any(rt >= 0 for _, _, rt in opp_inputs)
        if not any_in_riichi:
            return out
        for ds, ar, rt in opp_inputs:
            if rt < 0:
                out.append(-1)
                continue
            single = [0] * HAND_SIZE
            single[tile_idx] = 1
            ranks = evaluate_discard_safety(single, ds, remaining, ar, rt)
            out.append(ranks[tile_idx])
        return out

    if must_discard:
        per_discard = calculate_discard_ukeire(
            merged_padded, remaining, shanten_fn, base_shanten=shanten_min
        )
        # Filter: only consider slots that hold a REAL hand tile. With
        # padding present, slot 31 may exceed the real 1z count, so we
        # check against `merged_hand` (pre-padding).
        ukeire_values_for_best = [
            r.value if merged_hand[i] > 0 else -1 for i, r in enumerate(per_discard)
        ]
        best_idx = evaluate_best_discard(ukeire_values_for_best, dora=primary_dora)
        if best_idx >= 0 and merged_hand[best_idx] > 0:
            recommended = _format_normal(best_idx)
            current_ukeire = per_discard[best_idx].value
        else:
            best_idx = -1

        for idx in range(HAND_SIZE):
            if merged_hand[idx] == 0:
                continue
            result = per_discard[idx]
            entry = TileEval(
                tile=_format_normal(idx),
                index=idx,
                ukeire_count=result.value,
                ukeire_tiles=[_format_normal(t) for t in result.tiles],
                safety_per_opponent=_safety_for_tile(idx),
                is_recommended=(idx == best_idx),
            )
            discards.append(entry)

        def _sort_key(e: TileEval):
            min_safety = min((s for s in e.safety_per_opponent if s >= 0), default=99)
            return (-e.ukeire_count, -min_safety, e.index)

        discards.sort(key=_sort_key)
    else:
        ukeire = calculate_ukeire(
            merged_padded, remaining, shanten_fn, base_shanten=shanten_min
        )
        current_ukeire = ukeire.value

    return TurnEvaluation(
        shanten=shanten_min,
        shanten_standard=shanten_standard,
        shanten_chiitoi=shanten_chiitoi,
        shanten_kokushi=shanten_kokushi,
        current_ukeire=current_ukeire,
        discards=discards,
        recommended_discard=recommended,
        dora_tiles=dora_tiles,
        visible_tile_total=visible_total,
    )
