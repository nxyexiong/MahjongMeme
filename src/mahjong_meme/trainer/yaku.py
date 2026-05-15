"""Yaku / han calculation — thin wrapper over the production-grade
`mahjong` PyPI package (https://github.com/MahjongRepository/mahjong).

That library was validated against 26+ million tenhou.net phoenix replays,
so it produces results equivalent to tenhou.net. We adapt the I/O to use
our 38-slot tile encoding and a friendlier dataclass shape.

Public surface (also re-exported from `mahjong_meme.trainer`):
    calculate_han(...)  -> HanResult
    HanError            -> IntEnum of error codes
    HanResult           -> dataclass
    Meld                -> dataclass for called sets
    make_meld(...)      -> convenience builder

Tile encoding (input):
    Tile strings as elsewhere in the trainer:
        'Nm' / 'Np' / 'Ns' (1..9) and 'Nz' (1..7), with '5m*'/'5p*'/'5s*'
        for red fives. See `tiles.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable, Literal, Sequence

from mahjong.constants import EAST, NORTH, SOUTH, WEST
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.meld import Meld as _MJMeld
from mahjong.tile import TilesConverter

from .tiles import parse_tile

# Single shared calculator (it's stateless; safe to reuse).
_CALC = HandCalculator()


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class HanError(IntEnum):
    """Why a hand failed to receive a han count."""

    NONE = 0
    NOT_COMPLETE = 1
    """The hand isn't a valid winning shape."""

    NO_YAKU = 2
    """The hand is complete but has no yaku (dora alone doesn't count)."""

    INVALID_INPUT = 3
    """Tile count wrong, win_tile not in hand, malformed meld, etc."""


MeldType = Literal["chi", "pon", "kan_open", "kan_closed", "kan_added"]


@dataclass
class Meld:
    """A called or concealed-kan meld already locked in front of the player.

    `tiles` is a list of tile STRINGS (e.g. '5m', '5m*', '3z'), red fives
    included. Three tiles for chi/pon, four for any kan.
    """

    type: MeldType
    tiles: list[str]


@dataclass
class HanResult:
    """Result of `calculate_han`.

    On success: `han > 0`, `error == HanError.NONE`, `yaku` lists triggered
    yaku names, `yakuman > 0` if any yakuman fired, `cost` carries the
    point payout dict from the upstream library.

    On failure: `han == -1`, `error` indicates why.
    """

    han: int
    fu: int
    yakuman: int
    yaku: list[str] = field(default_factory=list)
    dora: int = 0
    cost: dict | None = None
    error: HanError = HanError.NONE
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# Tile-encoding adapter
# ---------------------------------------------------------------------------


# Mapping from our 38-slot index to the upstream 0..33 index.
# Upstream layout:  0..8 = man(1..9), 9..17 = pin(1..9), 18..26 = sou(1..9),
#                   27..33 = honors (E,S,W,N,白,發,中).
def _to_34(idx: int) -> int:
    if idx in (0, 10, 20):  # red fives → normal 5 of suit
        idx += 5
    if 1 <= idx <= 9:
        return idx - 1
    if 11 <= idx <= 19:
        return idx - 11 + 9
    if 21 <= idx <= 29:
        return idx - 21 + 18
    if 31 <= idx <= 37:
        return idx - 31 + 27
    raise ValueError(f"tile index {idx} cannot be converted to 34-array")


def _136_for_normal(idx34: int, used: list[int], *, is_red_5: bool = False) -> int:
    """Return a 136-array tile id for `idx34` that's NOT yet in `used`.

    The upstream library treats the FIRST copy of 5m/5p/5s (tile ids 16/52/88)
    as the canonical aka-dora. So when `is_red_5` is True we MUST return that
    canonical id; otherwise (for normal 5m/5p/5s) we skip n=0 and return one
    of copies 1..3. If a 4th copy of 5m/5p/5s is requested (only 3 normal +
    1 red exist), fall back to the red id.
    """
    if is_red_5:
        return idx34 * 4 + 0
    start = 0
    if idx34 in (4, 13, 22):  # 5m / 5p / 5s
        start = 1
    for n in range(start, 4):
        cand = idx34 * 4 + n
        if cand not in used:
            return cand
    # All non-red copies of a 5m/5p/5s used → fall back to red copy.
    if idx34 in (4, 13, 22):
        cand = idx34 * 4 + 0
        if cand not in used:
            return cand
    raise ValueError(f"5th copy requested for tile-34 {idx34}")


def _is_red(tile_string: str) -> bool:
    return tile_string.endswith("*")


def _hand_to_136(tile_strings: Sequence[str], used: list[int] | None = None) -> list[int]:
    """Convert a list of tile strings to 136-array IDs.

    Optionally pass an existing `used` list — the function will avoid
    re-using those ids AND append the newly chosen ids to it.
    """
    if used is None:
        used = []
    out: list[int] = []
    for s in tile_strings:
        idx = parse_tile(s)
        red = _is_red(s)
        idx34 = _to_34(idx)
        tile136 = _136_for_normal(idx34, used, is_red_5=red)
        used.append(tile136)
        out.append(tile136)
    return out


# ---------------------------------------------------------------------------
# Wind translation
# ---------------------------------------------------------------------------


_WIND_TO_136 = {1: EAST, 2: SOUTH, 3: WEST, 4: NORTH}


def _wind_to_const(w: int) -> int:
    if w not in _WIND_TO_136:
        raise ValueError(f"wind must be 1..4, got {w}")
    return _WIND_TO_136[w]


# ---------------------------------------------------------------------------
# Meld translation
# ---------------------------------------------------------------------------


_MELD_TYPE_MAP = {
    "chi": _MJMeld.CHI,
    "pon": _MJMeld.PON,
    "kan_open": _MJMeld.KAN,
    "kan_closed": _MJMeld.KAN,
    "kan_added": _MJMeld.SHOUMINKAN,
}


def _meld_to_upstream(m: Meld, used: list[int]) -> _MJMeld:
    tiles_136 = _hand_to_136(m.tiles, used)
    return _MJMeld(
        meld_type=_MELD_TYPE_MAP[m.type],
        tiles=tiles_136,
        opened=(m.type != "kan_closed"),
    )


def make_meld(type_: MeldType, tiles: Sequence[str]) -> Meld:
    """Convenience builder. Just a Meld with `tiles` as strings."""
    return Meld(type=type_, tiles=list(tiles))


# ---------------------------------------------------------------------------
# Top-level API
# ---------------------------------------------------------------------------


def calculate_han(
    concealed_hand: Sequence[str],
    win_tile: str,
    *,
    melds: Sequence[Meld] = (),
    is_tsumo: bool = False,
    is_riichi: bool = False,
    is_double_riichi: bool = False,
    is_ippatsu: bool = False,
    is_haitei: bool = False,
    is_houtei: bool = False,
    is_rinshan: bool = False,
    is_chankan: bool = False,
    dora_indicators: Sequence[str] = (),
    ura_indicators: Sequence[str] = (),
    seat_wind: int = 1,
    round_wind: int = 1,
    has_aka_dora: bool = True,
    has_open_tanyao: bool = True,
) -> HanResult:
    """Compute han + fu + yaku + score for a winning hand.

    Parameters
    ----------
    concealed_hand
        13 or 14 tile strings for the concealed portion. If 14, must
        include the win tile.
    win_tile
        The winning tile string. Must already appear in `concealed_hand`
        (the upstream library treats the hand as inclusive of the win).
    melds
        Already-locked sets (chi/pon/kan_*).
    is_tsumo / is_riichi / is_double_riichi / is_ippatsu / is_haitei /
    is_houtei / is_rinshan / is_chankan
        Situational flags.
    dora_indicators, ura_indicators
        Indicator tile strings (the indicator itself, NOT the dora).
    seat_wind, round_wind
        1..4 for E/S/W/N.
    has_aka_dora, has_open_tanyao
        Standard riichi-rules options. Defaults match Mahjong Soul.

    Returns
    -------
    HanResult. On error, `han == -1` and `error != HanError.NONE`.
    """
    melds = list(melds)
    n_melds = len(melds)

    # Hand-size sanity check.
    expected_with = 14 - 3 * n_melds
    expected_without = 13 - 3 * n_melds
    if len(concealed_hand) not in (expected_with, expected_without):
        return HanResult(
            -1, -1, 0, error=HanError.INVALID_INPUT,
            error_detail=(
                f"hand has {len(concealed_hand)} tiles with {n_melds} melds; "
                f"expected {expected_with} (with win tile) or {expected_without}."
            ),
        )

    # Build the full 14-tile concealed list (inclusive of win tile).
    if len(concealed_hand) == expected_without:
        full = list(concealed_hand) + [win_tile]
    else:
        full = list(concealed_hand)
        if win_tile not in full:
            return HanResult(
                -1, -1, 0, error=HanError.INVALID_INPUT,
                error_detail="win_tile not in concealed_hand",
            )

    try:
        # Build the full 14-tile view. The library expects ALL 14 tiles
        # (concealed + meld tiles) in `tiles`, plus the melds again in
        # `melds`. Build concealed first, then melds, sharing one `used`
        # tracker so 136 ids stay unique.
        used: list[int] = []
        tiles_136 = _hand_to_136(full, used)
        upstream_melds = [_meld_to_upstream(m, used) for m in melds]
        for m in upstream_melds:
            tiles_136.extend(m.tiles)

        win_idx = parse_tile(win_tile)
        win_is_red = _is_red(win_tile)
        target_34 = _to_34(win_idx)
        # Prefer a 136-id matching redness of the win tile.
        win_tile_136 = None
        for tid in reversed(tiles_136):
            if tid // 4 != target_34:
                continue
            is_canonical_red = tid in (16, 52, 88)
            if win_is_red and is_canonical_red:
                win_tile_136 = tid
                break
            if not win_is_red and not is_canonical_red:
                win_tile_136 = tid
                break
        if win_tile_136 is None:
            # Fallback: any matching tile.
            for tid in reversed(tiles_136):
                if tid // 4 == target_34:
                    win_tile_136 = tid
                    break
        if win_tile_136 is None:
            return HanResult(
                -1, -1, 0, error=HanError.INVALID_INPUT,
                error_detail="win_tile not represented in 136-array",
            )

        # Dora indicators have their own 136-ids that should NOT conflict
        # with the hand (they're "elsewhere on the wall"). Track separately.
        dora_used: list[int] = list(tiles_136)
        dora_136: list[int] = []
        for d in dora_indicators:
            idx34 = _to_34(parse_tile(d))
            is_red = _is_red(d)
            cand = _136_for_normal(idx34, dora_used, is_red_5=is_red)
            dora_used.append(cand)
            dora_136.append(cand)
        for d in ura_indicators:
            idx34 = _to_34(parse_tile(d))
            is_red = _is_red(d)
            cand = _136_for_normal(idx34, dora_used, is_red_5=is_red)
            dora_used.append(cand)
            dora_136.append(cand)

        rules = OptionalRules(
            has_open_tanyao=has_open_tanyao,
            has_aka_dora=has_aka_dora,
        )
        config = HandConfig(
            is_tsumo=is_tsumo,
            is_riichi=is_riichi,
            is_daburu_riichi=is_double_riichi,
            is_ippatsu=is_ippatsu,
            is_haitei=is_haitei,
            is_houtei=is_houtei,
            is_rinshan=is_rinshan,
            is_chankan=is_chankan,
            player_wind=_wind_to_const(seat_wind),
            round_wind=_wind_to_const(round_wind),
            options=rules,
        )

        result = _CALC.estimate_hand_value(
            tiles=tiles_136,
            win_tile=win_tile_136,
            melds=upstream_melds or None,
            dora_indicators=dora_136 or None,
            config=config,
        )
    except Exception as e:
        return HanResult(
            -1, -1, 0, error=HanError.INVALID_INPUT,
            error_detail=f"upstream library error: {e!r}",
        )

    # Map upstream errors to our enum.
    if result.error:
        err_str = str(result.error)
        if "no_yaku" in err_str or "no yaku" in err_str.lower():
            err = HanError.NO_YAKU
        elif "winning_tile_not_in_hand" in err_str or "hand_not_winning" in err_str:
            err = HanError.NOT_COMPLETE
        else:
            err = HanError.INVALID_INPUT
        return HanResult(
            -1, -1, 0, error=err, error_detail=err_str,
            yaku=[str(y) for y in (result.yaku or [])],
        )

    yaku_names = [str(y) for y in (result.yaku or [])]
    # Yakuman count: upstream reports han as 13/26/39/etc. in yakuman mode.
    # We count yakuman by looking at the cost yaku_level field when present,
    # or by checking if any yaku has `is_yakuman = True`.
    yakuman = 0
    if result.yaku:
        for y in result.yaku:
            if getattr(y, "is_yakuman", False):
                yakuman += 1

    # Dora count (excluding aka) — upstream stores them as a separate "Dora"
    # entry in the yaku list. Pull the han value of that yaku.
    dora_count = 0
    for y in result.yaku or []:
        name = str(y).strip().lower()
        if name == "dora":
            dora_count = getattr(y, "han_closed", None) or getattr(y, "han_open", None) or 0
            break

    return HanResult(
        han=int(result.han),
        fu=int(result.fu),
        yakuman=yakuman,
        yaku=yaku_names,
        dora=int(dora_count),
        cost=result.cost,
        error=HanError.NONE,
    )
