"""Riichi-Trainer evaluation engine, ported to Python.

Stateless API — call `evaluate_turn(hand, visible_tiles=…, …)` and get a
full discard analysis.

Example:

    from mahjong_meme.trainer import evaluate_turn, OpponentInfo

    result = evaluate_turn(
        hand=['1m','2m','3m','4p','5p','6p','7s','8s','9s','1z','1z','5m','5m*','5m'],
        visible_tiles=['3p'],
        dora_indicators=['1m'],
        opponents=[OpponentInfo(discards=['1z','9p'])],
    )
    print(result.shanten, result.recommended_discard)
    for d in result.discards:
        print(d.tile, d.ukeire_count, d.ukeire_tiles, d.safety_per_opponent)
"""
from .engine import OpponentInfo, TileEval, TurnEvaluation, evaluate_turn
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
    tile_counts,
)
from .ukeire import (
    UkeireResult,
    UpgradeResult,
    UpgradeTile,
    calculate_discard_ukeire,
    calculate_ukeire,
    calculate_ukeire_from_only_hand,
    calculate_ukeire_upgrades,
)

__all__ = [
    "evaluate_turn",
    "OpponentInfo",
    "TileEval",
    "TurnEvaluation",
    "calculate_minimum_shanten",
    "calculate_standard_shanten",
    "calculate_chiitoitsu_shanten",
    "calculate_kokushi_shanten",
    "calculate_ukeire",
    "calculate_discard_ukeire",
    "calculate_ukeire_upgrades",
    "calculate_ukeire_from_only_hand",
    "UkeireResult",
    "UpgradeResult",
    "UpgradeTile",
    "evaluate_best_discard",
    "evaluate_discard_safety",
    "HAND_SIZE",
    "ALL_TILES_REMAINING",
    "parse_tile",
    "format_tile",
    "tile_counts",
    "merge_red_fives",
    "dora_from_indicator",
]
