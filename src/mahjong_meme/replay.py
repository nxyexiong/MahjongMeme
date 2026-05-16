"""Parse Tenhou replay XML files into observer-shaped state snapshots.

For every decision point in a replay we yield a `state` dict matching the
schema of the live observer's `window.__mj.computeState()`. This lets the
trainer run on real high-quality play without any adapter.

Public API:
    parse_tenhou_replay(path) -> Iterator[dict]
    decode_meld(m: int)       -> (type, tile_ids_136, from_offset)
    tenhou_to_string(tile_id) -> our 38-slot string ('5m*', '3z', etc.)

Tenhou XML format reference (well-documented):
    https://m77.hatenablog.com/entry/2017/05/21/214529 (Japanese)
    https://github.com/mthrok/tenhou-log-utils (Python parser)
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Tile encoding: Tenhou 0..135 → our '5m'/'5m*'/'3z' strings.
# ---------------------------------------------------------------------------


def tenhou_to_string(tile_id: int) -> str:
    """Convert a Tenhou 0..135 tile id to our 38-slot string.

    Tenhou encoding:
        id // 4 → base tile (0..33):
            0..8  = 1m..9m
            9..17 = 1p..9p
            18..26 = 1s..9s
            27..30 = E,S,W,N
            31..33 = 白(haku), 發(hatsu), 中(chun)
        Red fives: ids 16/52/88 (the 0th copy of 5m/5p/5s).
    """
    if not 0 <= tile_id < 136:
        raise ValueError(f"tile id {tile_id} out of range 0..135")
    is_aka = tile_id in (16, 52, 88)
    base = tile_id // 4
    if base < 9:
        return "5m*" if is_aka else f"{base + 1}m"
    if base < 18:
        return "5p*" if is_aka else f"{base - 8}p"
    if base < 27:
        return "5s*" if is_aka else f"{base - 17}s"
    # 27..33 = E,S,W,N,白,發,中
    return f"{base - 26}z"


# ---------------------------------------------------------------------------
# Meld decoder for <N who="..." m="..."/>
# ---------------------------------------------------------------------------


def decode_meld(m: int) -> tuple[str, list[int], int]:
    """Decode the meld integer from a Tenhou ``<N m=...>`` element.

    Returns
    -------
    type : str
        'chi' | 'pon' | 'kan_open' | 'kan_closed' | 'kan_added' | 'nuki'
    tile_ids_136 : list[int]
        All tiles in the meld (3 for chi/pon, 4 for kan).
    from_offset : int
        0..3. For called sets: 1=shimocha (right), 2=toimen (across),
        3=kamicha (left). For closed kan: 0 (self).
    """
    from_offset = m & 0x3

    # Chi (bit 2)
    if m & 0x4:
        t = [(m >> 3) & 0x3, (m >> 5) & 0x3, (m >> 7) & 0x3]
        base_low = m >> 10
        block = base_low // 3  # 0..20 (3 suits × 7 starts per suit)
        suit = block // 7
        rank = block % 7  # start tile rank in 1..7 (1m..7m, 1p..7p, 1s..7s)
        start = suit * 9 + rank  # base tile 0..33 (only m/p/s reach here)
        return ("chi", [(start + i) * 4 + t[i] for i in range(3)], from_offset)

    # Pon or added-kan (bits 3 or 4)
    if m & 0x18:
        unused = (m >> 5) & 0x3
        base_encoded = m >> 9
        base = base_encoded // 3
        if m & 0x8:
            # Pon: 3 tiles, skip the `unused` copy
            return ("pon", [base * 4 + j for j in range(4) if j != unused], from_offset)
        # Added kan (chakan / shouminkan): all 4 copies
        return ("kan_added", [base * 4 + j for j in range(4)], from_offset)

    # Nuki (sanma north tile, bit 5)
    if m & 0x20:
        return ("nuki", [(m >> 8) & 0xff], from_offset)

    # Open or closed kan (no flag bits set)
    one_tile = (m >> 8) & 0xff
    base = one_tile // 4
    tiles = [base * 4 + j for j in range(4)]
    if from_offset == 0:
        return ("kan_closed", tiles, 0)
    return ("kan_open", tiles, from_offset)


# ---------------------------------------------------------------------------
# Replay state machine
# ---------------------------------------------------------------------------


@dataclass
class _RoundState:
    """Mutable per-round state tracked while replaying events."""
    hands: list[list[int]] = field(default_factory=lambda: [[] for _ in range(4)])
    """Per server seat: tenhou 0..135 ids currently in concealed hand."""
    melds: list[list[dict]] = field(default_factory=lambda: [[] for _ in range(4)])
    """Per server seat: list of {'type': str, 'tiles': list[int]}."""
    discards: list[list[int]] = field(default_factory=lambda: [[] for _ in range(4)])
    """Per server seat: tenhou ids in the discard river, including tiles
    later called by others (matches live state.js which keeps them too)."""
    liqi: list[bool] = field(default_factory=lambda: [False] * 4)
    scores: list[int] = field(default_factory=lambda: [25000, 25000, 25000, 25000])
    dora_indicators: list[int] = field(default_factory=list)
    left_tile_count: int = 70
    oya: int = 0
    chang: int = 0
    ju: int = 0
    ben: int = 0
    last_discard_seat: int | None = None
    last_discard_tile: int | None = None
    last_discard_moqie: bool = False
    last_drawn: list[int | None] = field(default_factory=lambda: [None, None, None, None])
    """Per server seat: the tenhou id of the most recent draw, or None if
    the seat hasn't drawn since their last discard or a call."""
    """Riichi declarations come as two events: step=1 (intent) then a
    discard, which is the actual riichi-declaration tile. We track the
    intent here so the next discard from that seat sets ``liqi``."""
    pending_riichi_seat: int | None = None


_DRAW_TAGS = {"T": 0, "U": 1, "V": 2, "W": 3}
_DISCARD_TAGS = {"D": 0, "E": 1, "F": 2, "G": 3}


def _tile_sort_key(s: str) -> tuple[int, int]:
    """Sort 'Nm'/'Np'/'Ns'/'Nz' by suit then number; red fives sort with 5."""
    is_red = s.endswith("*")
    if is_red:
        s = s[:-1]
    if len(s) != 2:
        return (99, 0)
    suit_order = {"m": 0, "p": 1, "s": 2, "z": 3}
    try:
        return (suit_order.get(s[1], 99), int(s[0]))
    except ValueError:
        return (99, 0)


# Meld type code mapping to match the live state.js encoding.
# In live state.js, `meld.type` is the integer reported by Mahjong Soul's
# `mc.mings[i].type`. Tenhou's XML uses string types — we translate so
# downstream consumers see the same integers either way.
_MJ_MELD_TYPE_CODES = {
    "chi": 0,
    "pon": 1,
    "kan_open": 2,
    "kan_closed": 4,
    "kan_added": 5,
    "nuki": 6,
}


# ---------------------------------------------------------------------------
# Legality inference: what calls is a seat allowed to make right now?
# ---------------------------------------------------------------------------


def _tile_string_normal(t: int) -> str:
    """Normalize a tenhou 0..135 id to its non-red string form."""
    s = tenhou_to_string(t)
    return s[:-1] if s.endswith("*") else s


def _norm_red(s: str) -> str:
    return s[:-1] if s.endswith("*") else s


def _can_chi(hand_tile_strs: list[str], discard_str: str) -> list[tuple[str, str]]:
    """Return list of (a, b) chi partner pairs available in `hand_tile_strs`
    for the discarded tile. Only same-suit number tiles can chi.
    """
    d = _norm_red(discard_str)
    if len(d) != 2 or d[1] not in "mps":
        return []
    try:
        v = int(d[0])
    except ValueError:
        return []
    suit = d[1]
    pairs: list[tuple[str, str]] = []
    norms = [_norm_red(t) for t in hand_tile_strs]
    for a, b in ((v - 2, v - 1), (v - 1, v + 1), (v + 1, v + 2)):
        if not (1 <= a <= 9 and 1 <= b <= 9):
            continue
        a_str, b_str = f"{a}{suit}", f"{b}{suit}"
        if a_str in norms and b_str in norms:
            pairs.append((a_str, b_str))
    return pairs


def _count_matching(hand_tile_strs: list[str], target_str: str) -> int:
    t = _norm_red(target_str)
    return sum(1 for s in hand_tile_strs if _norm_red(s) == t)


def _is_complete_hand(hand_strs: list[str], meld_count: int) -> bool:
    """Check if `hand_strs` (after-win) forms a valid winning shape.

    Uses the trainer's shanten function. `meld_count` is the number of
    locked melds; we pad with East-wind triplets the same way the trainer
    does so the standard-shanten algorithm sees a 14-tile-equivalent hand.
    """
    # Late import — replay module shouldn't fail-import if trainer is missing.
    try:
        from mahjong_meme.trainer.shanten import (
            calculate_chiitoitsu_shanten,
            calculate_kokushi_shanten,
            calculate_standard_shanten,
        )
        from mahjong_meme.trainer.tiles import HAND_SIZE, parse_tile
    except Exception:
        return False
    counts = [0] * HAND_SIZE
    for s in hand_strs:
        counts[parse_tile(s)] += 1
    # East-wind padding for open hands.
    counts[31] += 3 * meld_count
    std = calculate_standard_shanten(counts)
    if std == -1:
        return True
    if meld_count == 0:
        chii = calculate_chiitoitsu_shanten(counts)
        kok = calculate_kokushi_shanten(counts)
        return chii == -1 or kok == -1
    return False


# ---------------------------------------------------------------------------
# Option synthesis
# ---------------------------------------------------------------------------


def _make_pass_option() -> dict:
    return {"action": "pass", "label": "Pass", "button_name": "btn_quxiao"}


def _can_win_with_yaku(
    concealed_hand: list[str],
    win_tile: str,
    melds_typed: list[dict],
    *,
    is_tsumo: bool,
    is_riichi: bool,
    dora_indicators: list[str],
    seat_wind: int,
    round_wind: int,
    own_discards: list[str] = (),
) -> bool:
    """Yaku- and furiten-aware win check. Calls the trainer's
    `calculate_han()` and returns True only when the hand can ACTUALLY win:

      - shape is complete (NOT_COMPLETE → False),
      - has ≥1 yaku (NO_YAKU → False),
      - is not furiten when ron-completing (FURITEN → False).

    `melds_typed` is the parser's per-seat meld list (dicts with string
    'type' keys). `own_discards` is the responder's own discard pile,
    used for furiten enforcement (only relevant for is_tsumo=False).
    """
    try:
        from mahjong_meme.trainer import (
            HanError,
            calculate_han,
            make_meld,
        )
    except Exception:
        return _is_complete_hand(concealed_hand + [win_tile], len(melds_typed))

    meld_objs = []
    for m in melds_typed:
        mtype = m.get("type")
        tiles = [tenhou_to_string(t) for t in m.get("tiles") or []]
        if not tiles:
            continue
        if mtype == "chi":
            meld_objs.append(make_meld("chi", tiles))
        elif mtype == "pon":
            meld_objs.append(make_meld("pon", tiles))
        elif mtype == "kan_open":
            meld_objs.append(make_meld("kan_open", tiles))
        elif mtype == "kan_closed":
            meld_objs.append(make_meld("kan_closed", tiles))
        elif mtype == "kan_added":
            meld_objs.append(make_meld("kan_added", tiles))
    try:
        res = calculate_han(
            concealed_hand=concealed_hand,
            win_tile=win_tile,
            melds=meld_objs,
            is_tsumo=is_tsumo,
            is_riichi=is_riichi,
            dora_indicators=dora_indicators,
            seat_wind=seat_wind,
            round_wind=round_wind,
            own_discards=list(own_discards) if not is_tsumo else (),
        )
    except Exception:
        return False
    return res.error == HanError.NONE and res.han > 0


# Backwards compat — used to be called directly from the parser. Now
# folded into `_can_win_with_yaku` via the trainer's `own_discards` arg.
def _in_furiten(
    own_discards: list[int],
    winning_waits: set[str] | None,
    discarded_str: str,
) -> bool:
    target = _norm_red(discarded_str)
    own_norms = {_tile_string_normal(t) for t in own_discards}
    if target in own_norms:
        return True
    if winning_waits and (winning_waits & own_norms):
        return True
    return False


def _options_for_call_window(
    hand_tile_strs: list[str],
    melds_typed: list[dict],
    discard_str: str,
    *,
    own_discards: list[int],
    is_riichi: bool,
    dora_indicators: list[str],
    seat_wind: int,
    round_wind: int,
    can_open_calls: bool = True,
) -> list[dict]:
    """Enumerate all LEGAL responses to an opponent's discard.

    `hand_tile_strs` is the responder's concealed hand BEFORE the call.
    `melds_typed` is their existing called sets (dicts with 'type'/'tiles').
    `own_discards` is the responder's discard pile (for furiten checking).
    """
    opts: list[dict] = []

    # Ron: yaku-validated + furiten-aware (furiten check is done inside
    # _can_win_with_yaku via calculate_han's own_discards arg).
    own_discards_str = [tenhou_to_string(t) for t in own_discards]
    if _can_win_with_yaku(
        hand_tile_strs, discard_str, melds_typed,
        is_tsumo=False, is_riichi=is_riichi,
        dora_indicators=dora_indicators,
        seat_wind=seat_wind, round_wind=round_wind,
        own_discards=own_discards_str,
    ):
        opts.append({"action": "hu", "label": f"Ron {discard_str}",
                     "button_name": "btn_hu"})

    if can_open_calls:
        # Pon
        if _count_matching(hand_tile_strs, discard_str) >= 2:
            opts.append({"action": "pon", "label": f"Pon {_norm_red(discard_str)}",
                         "button_name": "btn_peng"})
        # Open kan
        if _count_matching(hand_tile_strs, discard_str) >= 3:
            opts.append({"action": "kan", "label": f"Kan {_norm_red(discard_str)}",
                         "button_name": "btn_minkan"})
        # Chi (kamicha only — caller filters by relative seat)
        for a, b in _can_chi(hand_tile_strs, discard_str):
            opts.append({
                "action": "chi",
                "label": f"Chi {a}+{b}+{_norm_red(discard_str)}",
                "button_name": "btn_chi",
                "extra": {"partner_tiles": [a, b]},
            })

    opts.append(_make_pass_option())
    return opts


def _options_for_post_draw(
    hand_tile_strs: list[str],
    melds_typed: list[dict],
    drawn_str: str | None,
    is_closed: bool,
    *,
    dora_indicators: list[str],
    seat_wind: int,
    round_wind: int,
    is_riichi: bool = False,
) -> list[dict]:
    """Enumerate the SPECIAL post-draw options (tsumo / ankan / chakan /
    riichi / kita). The default `discard` analysis is separate from this
    — those options only apply when the player has a real choice beyond
    just discarding.

    Tsumo is yaku-validated via the trainer. Returns an empty list if no
    special action is legal — in which case the parser emits a plain
    `discard` kind instead of `call_window`.
    """
    opts: list[dict] = []

    if drawn_str is None:
        return opts

    # Tsumo: yaku-validated. The drawn tile IS in `hand_tile_strs`.
    concealed_pre = list(hand_tile_strs)
    if drawn_str in concealed_pre:
        concealed_pre.remove(drawn_str)
    if _can_win_with_yaku(
        concealed_pre, drawn_str, melds_typed,
        is_tsumo=True, is_riichi=is_riichi,
        dora_indicators=dora_indicators,
        seat_wind=seat_wind, round_wind=round_wind,
    ):
        opts.append({"action": "zimo", "label": "Tsumo", "button_name": "btn_zimo"})

    # Ankan: 4 of any tile in hand.
    counts: dict[str, int] = {}
    for s in hand_tile_strs:
        n = _norm_red(s)
        counts[n] = counts.get(n, 0) + 1
    for tile, c in counts.items():
        if c == 4:
            opts.append({"action": "kan", "label": f"Ankan {tile}",
                         "button_name": "btn_ankan",
                         "extra": {"tile": tile, "subtype": "kan_closed"}})

    # Riichi: closed + tenpai. (Yaku is guaranteed by the riichi yaku itself.)
    if is_closed and not melds_typed and not is_riichi:
        try:
            from mahjong_meme.trainer.shanten import calculate_minimum_shanten
            from mahjong_meme.trainer.tiles import HAND_SIZE, parse_tile
            counts_arr = [0] * HAND_SIZE
            for s in hand_tile_strs:
                counts_arr[parse_tile(s)] += 1
            for i in range(HAND_SIZE):
                if counts_arr[i] == 0:
                    continue
                counts_arr[i] -= 1
                if calculate_minimum_shanten(counts_arr) == 0:
                    opts.append({"action": "lizhi", "label": "Riichi",
                                 "button_name": "btn_lizhi"})
                    counts_arr[i] += 1
                    break
                counts_arr[i] += 1
        except Exception:
            pass

    return opts


def _hand_strings_for(rs: "_RoundState", seat: int) -> list[str]:
    """Tile-string view of a seat's concealed hand (preserves draw order)."""
    return [tenhou_to_string(t) for t in rs.hands[seat]]


def _seat_wind(rs: "_RoundState", seat: int) -> int:
    """1..4 for E/S/W/N — the seat wind relative to the round's dealer."""
    return ((seat - rs.oya) % 4) + 1


def _make_skip_choice() -> dict:
    """Canonical 'this player did nothing at this event' choice."""
    return {"action": "skip"}


def _meld_choice(mtype: str, label_tiles: list[str] | None = None) -> dict:
    """Build a ``choice`` dict for a call (chi/pon/kan/nuki).

    For kan types we additionally surface a normalized ``tile`` field
    (red-five collapsed to its non-red form) so consumers know WHICH
    tile is being declared on without parsing ``extra.tiles``.
    """
    tiles = list(label_tiles or [])
    norm_tile = (tiles[0][:-1] if tiles and tiles[0].endswith("*") else tiles[0]) \
        if tiles else None

    if mtype == "chi":
        return {"action": "chi",
                "label": f"Chi {'+'.join(tiles)}" if tiles else "Chi",
                "extra": {"tiles": tiles}}
    if mtype == "pon":
        return {"action": "pon",
                "label": f"Pon {tiles[0]}" if tiles else "Pon",
                "tile": norm_tile,
                "extra": {"tiles": tiles}}
    if mtype == "kan_open":
        return {"action": "kan", "label": "Open Kan",
                "tile": norm_tile,
                "extra": {"subtype": "kan_open", "tiles": tiles}}
    if mtype == "kan_closed":
        return {"action": "kan", "label": "Ankan",
                "tile": norm_tile,
                "extra": {"subtype": "kan_closed", "tiles": tiles}}
    if mtype == "kan_added":
        return {"action": "kan", "label": "Chakan",
                "tile": norm_tile,
                "extra": {"subtype": "kan_added", "tiles": tiles}}
    if mtype == "nuki":
        return {"action": "kita", "label": "Kita",
                "tile": norm_tile,
                "extra": {"tiles": tiles}}
    return {"action": "skip"}


def _observer_view(
    rs: "_RoundState",
    seat: int,
    event_kind: str,
    actor: int | None,
) -> tuple[str, list[dict]]:
    """Compute (kind, options) for `seat` AFTER an event has been applied,
    assuming `seat` is a *non-actor* observer at this event.

    Returns ("observe", []) when the player has nothing to do; or
    ("call_window", [...]) / ("discard", [...]) when they have options.
    """
    if event_kind == "discard" and rs.last_discard_tile is not None:
        # Non-discarder observers see the discard land; they may have
        # legal call responses (chi from kamicha only, pon/kan/ron from anyone).
        if rs.last_discard_seat == seat:
            return ("observe", [])
        discard_str = tenhou_to_string(rs.last_discard_tile)
        is_kamicha = ((seat - rs.last_discard_seat) % 4) == 1
        opts = _options_for_call_window(
            _hand_strings_for(rs, seat),
            rs.melds[seat],
            discard_str,
            own_discards=rs.discards[seat],
            is_riichi=rs.liqi[seat],
            dora_indicators=[tenhou_to_string(d) for d in rs.dora_indicators],
            seat_wind=_seat_wind(rs, seat),
            round_wind=rs.chang + 1,
            can_open_calls=True,
        )
        if not is_kamicha:
            opts = [o for o in opts if o.get("action") != "chi"]
        if any(o.get("action") not in (None, "pass") for o in opts):
            return ("call_window", opts)
        return ("observe", [])

    if event_kind == "draw" and rs.last_drawn[seat] is not None:
        # Drawer is observed-with-options here (we treat draw as actorless;
        # the drawer's actual choice is captured at the NEXT XML event).
        drawn = tenhou_to_string(rs.last_drawn[seat])
        is_closed = len(rs.melds[seat]) == 0
        specials = _options_for_post_draw(
            _hand_strings_for(rs, seat),
            rs.melds[seat],
            drawn,
            is_closed,
            dora_indicators=[tenhou_to_string(d) for d in rs.dora_indicators],
            seat_wind=_seat_wind(rs, seat),
            round_wind=rs.chang + 1,
            is_riichi=rs.liqi[seat],
        )
        discards = _discard_options(rs.hands[seat])
        opts = specials + discards
        # If we have any non-discard specials, this is a call_window moment.
        kind = "call_window" if specials else "discard"
        return (kind, opts)

    return ("observe", [])


def _classify_event(
    rs: "_RoundState",
    elem: ET.Element,
    *,
    next_elem: ET.Element | None = None,
) -> tuple[str, int | None, dict, str, list[dict]]:
    """Return ``(event_kind, actor, actor_choice, actor_state_kind, actor_options)``
    for the upcoming XML element, computed against the *pre-apply* state.

    - ``event_kind``: one of 'init', 'draw', 'discard', 'call', 'riichi',
      'agari', 'dora', 'ryuukyoku', 'unknown'.
    - ``actor``: server seat of the player performing this action, or None
      for actorless events (init/draw/dora/ryuukyoku).
    - ``actor_choice``: the choice dict to record on the actor (only used
      when actor is not None).
    - ``actor_state_kind``: state.actionable.kind to render for the actor.
    - ``actor_options``: legal-options list the actor was choosing from.
    """
    tag = elem.tag
    # Draw — actorless from a decision perspective; the drawer's actual
    # choice surfaces at the NEXT event.
    if len(tag) >= 2 and tag[0] in _DRAW_TAGS and tag[1:].isdigit():
        return ("draw", None, _make_skip_choice(), "observe", [])

    # Discard.
    if len(tag) >= 2 and tag[0] in _DISCARD_TAGS and tag[1:].isdigit():
        seat = _DISCARD_TAGS[tag[0]]
        tile = int(tag[1:])
        slot = rs.hands[seat].index(tile) if tile in rs.hands[seat] else -1
        choice = {"action": "discard", "tile": tenhou_to_string(tile), "slot": slot}
        options = _discard_options(rs.hands[seat])
        # If the actor JUST drew, the post-draw specials are also legal
        # options at this decision point — surface them so the model can
        # see that tsumo/ankan/riichi were on the table too.
        if rs.last_drawn[seat] is not None:
            drawn = tenhou_to_string(rs.last_drawn[seat])
            is_closed = len(rs.melds[seat]) == 0
            specials = _options_for_post_draw(
                _hand_strings_for(rs, seat),
                rs.melds[seat],
                drawn,
                is_closed,
                dora_indicators=[tenhou_to_string(d) for d in rs.dora_indicators],
                seat_wind=_seat_wind(rs, seat),
                round_wind=rs.chang + 1,
                is_riichi=rs.liqi[seat],
            )
            options = specials + options
        return ("discard", seat, choice, "discard", options)

    # Call (chi/pon/kan/nuki).
    if tag == "N":
        who = int(elem.get("who") or "0")
        m = int(elem.get("m") or "0")
        mtype, tiles_136, _from = decode_meld(m)
        tile_strs = [tenhou_to_string(t) for t in tiles_136]
        choice = _meld_choice(mtype, tile_strs)
        # Build the legal-options list the caller was choosing from.
        if mtype in ("chi", "pon", "kan_open") and rs.last_discard_tile is not None:
            discard_str = tenhou_to_string(rs.last_discard_tile)
            options = _options_for_call_window(
                _hand_strings_for(rs, who),
                rs.melds[who],
                discard_str,
                own_discards=rs.discards[who],
                is_riichi=rs.liqi[who],
                dora_indicators=[tenhou_to_string(d) for d in rs.dora_indicators],
                seat_wind=_seat_wind(rs, who),
                round_wind=rs.chang + 1,
                can_open_calls=True,
            )
        elif mtype in ("kan_closed", "kan_added"):
            # Caller had a post-draw special-options moment.
            drawn = (
                tenhou_to_string(rs.last_drawn[who])
                if rs.last_drawn[who] is not None
                else None
            )
            is_closed = len(rs.melds[who]) == 0
            specials = _options_for_post_draw(
                _hand_strings_for(rs, who),
                rs.melds[who],
                drawn,
                is_closed,
                dora_indicators=[tenhou_to_string(d) for d in rs.dora_indicators],
                seat_wind=_seat_wind(rs, who),
                round_wind=rs.chang + 1,
                is_riichi=rs.liqi[who],
            )
            options = specials + [_make_pass_option()]
        elif mtype == "nuki":
            options = [
                {"action": "kita", "label": "Kita", "button_name": "btn_babei"},
                _make_pass_option(),
            ]
        else:
            options = [_make_pass_option()]
        return ("call", who, choice, "call_window", options)

    # Riichi declaration.
    if tag == "REACH":
        who = int(elem.get("who") or "0")
        step = int(elem.get("step") or "1")
        if step == 1:
            # Look-ahead: a REACH step=1 is always immediately followed
            # by the same seat's discard (which is the declaration tile).
            # We attach that tile so the choice is fully specified for
            # training / advisor display.
            riichi_tile: str | None = None
            if next_elem is not None:
                ntag = next_elem.tag
                if (len(ntag) >= 2 and ntag[0] in _DISCARD_TAGS
                        and ntag[1:].isdigit()
                        and _DISCARD_TAGS[ntag[0]] == who):
                    try:
                        riichi_tile = tenhou_to_string(int(ntag[1:]))
                    except ValueError:
                        riichi_tile = None
            choice: dict = {"action": "lizhi", "label": "Riichi"}
            if riichi_tile is not None:
                choice["tile"] = riichi_tile
                choice["extra"] = {"declare_on": riichi_tile}
            drawn = (
                tenhou_to_string(rs.last_drawn[who])
                if rs.last_drawn[who] is not None
                else None
            )
            is_closed = len(rs.melds[who]) == 0
            specials = _options_for_post_draw(
                _hand_strings_for(rs, who),
                rs.melds[who],
                drawn,
                is_closed,
                dora_indicators=[tenhou_to_string(d) for d in rs.dora_indicators],
                seat_wind=_seat_wind(rs, who),
                round_wind=rs.chang + 1,
                is_riichi=False,
            )
            return ("riichi", who, choice, "call_window",
                    specials + [_make_pass_option()])
        # step=2 is a confirmation broadcast; no decision was made here.
        return ("riichi", None, _make_skip_choice(), "observe", [])

    # AGARI (round-ending win).
    if tag == "AGARI":
        who = int(elem.get("who") or "0")
        from_who = int(elem.get("fromWho") or str(who))
        if who == from_who:
            choice = {"action": "zimo", "label": "Tsumo"}
            options = [
                {"action": "zimo", "label": "Tsumo", "button_name": "btn_zimo"},
                _make_pass_option(),
            ]
        else:
            choice = {"action": "hu", "label": "Ron"}
            options = [
                {"action": "hu", "label": "Ron", "button_name": "btn_hu"},
                _make_pass_option(),
            ]
        return ("agari", who, choice, "call_window", options)

    if tag == "INIT":
        return ("init", None, _make_skip_choice(), "observe", [])
    if tag == "DORA":
        return ("dora", None, _make_skip_choice(), "observe", [])
    if tag == "RYUUKYOKU":
        return ("ryuukyoku", None, _make_skip_choice(), "observe", [])
    return ("unknown", None, _make_skip_choice(), "observe", [])


def _build_state(rs: _RoundState, server_seat: int, kind: str,
                 options: list[dict] | None = None) -> dict:
    """Build an observer-schema state dict from `server_seat`'s POV.

    Rotates per-seat arrays so the focal player sits at local index 0.
    """
    def to_local(s: int) -> int:
        return (s - server_seat) % 4

    melds_local: list[list[dict] | None] = [None] * 4
    discards_local: list[list[str] | None] = [None] * 4
    liqi_local: list[bool | None] = [None] * 4
    scores_local: list[int | None] = [None] * 4

    for s in range(4):
        loc = to_local(s)
        melds_local[loc] = [
            {
                "type": _MJ_MELD_TYPE_CODES.get(m["type"], m["type"]),
                "tiles": [tenhou_to_string(t) for t in m["tiles"]],
            }
            for m in rs.melds[s]
        ]
        discards_local[loc] = [tenhou_to_string(t) for t in rs.discards[s]]
        liqi_local[loc] = rs.liqi[s]
        scores_local[loc] = rs.scores[s]

    # Hand order: match the live state's behavior (preserve in-hand order;
    # the just-drawn tile is conventionally the last element). Tenhou
    # replays don't naturally preserve UI order, but they DO append draws
    # to the end and remove discards from anywhere — we maintain that
    # ordering in `rs.hands[seat]` already, so just stringify in place.
    hand_strs = [tenhou_to_string(t) for t in rs.hands[server_seat]]

    last_disc: dict | None = None
    if rs.last_discard_seat is not None and rs.last_discard_tile is not None:
        last_disc = {
            "seat": to_local(rs.last_discard_seat),
            "tile": tenhou_to_string(rs.last_discard_tile),
            "is_moqie": rs.last_discard_moqie,
        }

    # last_drawn_tile mirrors the live `me.last_tile.val` field: present
    # when we just drew (and haven't yet discarded), null right after a
    # call. The replay state machine sets `rs.last_drawn[seat]` on every
    # draw and clears it on discard.
    last_drawn = rs.last_drawn[server_seat]
    last_drawn_str = tenhou_to_string(last_drawn) if last_drawn is not None else None

    return {
        "ok": True,
        "scene": "match",
        "modal": None,
        "needs_my_action": True,
        "actionable": {"kind": kind, "options": list(options or [])},
        "room_settings": None,
        "room": None,
        "meta_actions": [],
        "account": {"logined": True, "name": "<replay>", "id": server_seat},
        "match": {
            "my_seat": 0,
            "my_server_seat": server_seat,
            "scores": scores_local,
            "chang": rs.chang,
            "ju": rs.ju,
            "ben": rs.ben,
            "left_tile_count": rs.left_tile_count,
            "dora_indicators": [tenhou_to_string(d) for d in rs.dora_indicators],
            "hand": hand_strs,
            "last_drawn_tile": last_drawn_str,
            "melds": melds_local,
            "discards": discards_local,
            "liqi": liqi_local,
            "last_discard": last_disc,
            "can_discard": kind == "discard",
        },
        "event_seq": 0,
    }


def _apply_init(rs: _RoundState, elem: ET.Element) -> None:
    seed_parts = [int(x) for x in (elem.get("seed") or "0").split(",")]
    while len(seed_parts) < 6:
        seed_parts.append(0)
    rs.chang = seed_parts[0] // 4
    rs.ju = seed_parts[0] % 4
    rs.ben = seed_parts[1]
    # seed_parts[2] = riichi sticks on table, seed_parts[3..4] = dice
    rs.dora_indicators = [seed_parts[5]]

    ten_str = elem.get("ten") or ""
    if ten_str:
        rs.scores = [int(x) * 100 for x in ten_str.split(",")[:4]]
        while len(rs.scores) < 4:
            rs.scores.append(25000)

    rs.oya = int(elem.get("oya") or "0")
    rs.hands = [[] for _ in range(4)]
    rs.melds = [[] for _ in range(4)]
    rs.discards = [[] for _ in range(4)]
    rs.liqi = [False] * 4
    rs.left_tile_count = 70
    rs.last_discard_seat = None
    rs.last_discard_tile = None
    rs.last_discard_moqie = False
    rs.last_drawn = [None, None, None, None]
    rs.pending_riichi_seat = None

    for i in range(4):
        hai = elem.get(f"hai{i}") or ""
        if hai:
            rs.hands[i] = [int(x) for x in hai.split(",")]


def _apply_call(rs: _RoundState, who: int, m: int) -> None:
    """Mutate state for a successful call. The call's pre-state should
    have been yielded before this is invoked.
    """
    mtype, tiles_136, _from = decode_meld(m)
    # Identify which tile in the meld came from the discard pile (for non-
    # concealed calls). The remaining tiles get pulled from `who`'s hand.
    consumed_from_hand = list(tiles_136)
    if mtype in ("chi", "pon", "kan_open", "kan_added"):
        if rs.last_discard_tile is not None and rs.last_discard_tile in consumed_from_hand:
            consumed_from_hand.remove(rs.last_discard_tile)
    for t in consumed_from_hand:
        if t in rs.hands[who]:
            rs.hands[who].remove(t)
    rs.melds[who].append({"type": mtype, "tiles": list(tiles_136)})


def _apply_event(rs: "_RoundState", elem: ET.Element, event_kind: str) -> None:
    """Mutate ``rs`` to reflect the XML element being processed."""
    tag = elem.tag
    if event_kind == "draw":
        seat = _DRAW_TAGS[tag[0]]
        tile = int(tag[1:])
        rs.hands[seat].append(tile)
        rs.last_drawn[seat] = tile
        rs.left_tile_count = max(0, rs.left_tile_count - 1)
        return
    if event_kind == "discard":
        seat = _DISCARD_TAGS[tag[0]]
        tile = int(tag[1:])
        if tile in rs.hands[seat]:
            rs.hands[seat].remove(tile)
        rs.discards[seat].append(tile)
        rs.last_discard_seat = seat
        rs.last_discard_tile = tile
        rs.last_discard_moqie = (rs.last_drawn[seat] == tile)
        rs.last_drawn[seat] = None
        if rs.pending_riichi_seat == seat:
            rs.liqi[seat] = True
            rs.scores[seat] -= 1000
            rs.pending_riichi_seat = None
        return
    if event_kind == "call":
        who = int(elem.get("who") or "0")
        m = int(elem.get("m") or "0")
        _apply_call(rs, who, m)
        rs.last_drawn[who] = None
        # Calls consume the discard; clear it so subsequent observer
        # records don't treat a stale tile as ron-eligible.
        rs.last_discard_seat = None
        rs.last_discard_tile = None
        rs.last_discard_moqie = False
        return
    if event_kind == "riichi":
        who = int(elem.get("who") or "0")
        step = int(elem.get("step") or "1")
        if step == 1:
            rs.pending_riichi_seat = who
        return
    if event_kind == "dora":
        hai = int(elem.get("hai") or "0")
        rs.dora_indicators.append(hai)
        return
    if event_kind == "init":
        _apply_init(rs, elem)
        return
    # 'agari' and 'ryuukyoku' end the round; we don't mutate further.


def parse_tenhou_replay(
    path: Path | str,
    *,
    legacy: bool = False,
) -> Iterator[dict]:
    """Yield ``(state, choice)`` records — one per server seat per XML event.

    For every event in the replay we emit FOUR records: one from each of
    the 4 server seats' POVs. The yielded dict has the shape::

        {
            "state":  <observer-shape state dict, from this seat's POV>,
            "choice": <{"action": ...} describing what THIS SEAT did>,
            "seat":   <server seat index 0..3>,
            "event":  {
                "index": <0-based event sequence number>,
                "tag":   <XML tag, e.g. "T", "D", "N", "AGARI">,
                "kind":  <"draw"|"discard"|"call"|"agari"|"riichi"
                          |"dora"|"init"|"ryuukyoku"|"unknown">,
                "actor": <server seat of the player acting, or None>,
            },
        }

    The actor's record uses the *pre-apply* state (their decision moment);
    non-actor records use the *post-apply* state (what they see immediately
    after the event happens). Non-actor seats always carry
    ``choice = {"action": "skip"}`` — they either had no action available
    or didn't act at this particular event. When skip is paired with a
    populated ``actionable.options[]``, the player had legal actions but
    elected to pass (e.g. an opponent's discard they didn't call).

    Choice ``action`` values:
        discard      one of ``actionable.options[]`` — the tile they cut
        chi/pon/kan  a called meld (``extra.subtype`` distinguishes kans)
        hu           ron win
        zimo         tsumo win
        lizhi        riichi declaration
        kita         sanma north tile
        skip         no action / passed call window

    Parameters
    ----------
    path
        Tenhou replay XML file.
    legacy
        If True, yield the pre-v2 schema (raw state dicts, one per
        decision point, no choice/seat/event wrapping). Default: False.
    """
    path = Path(path)
    tree = ET.parse(path)
    root = tree.getroot()
    rs = _RoundState()

    # Pre-game/header XML tags that don't represent gameplay events.
    _SKIP_TAGS = {"SHUFFLE", "GO", "UN", "TAIKYOKU", "BYE"}

    # Materialize once so we can peek at the next element (needed for
    # REACH lookahead: the riichi declaration tile is on the next D###).
    children = list(root)
    for event_index, elem in enumerate(children):
        tag = elem.tag
        if tag in _SKIP_TAGS:
            continue

        next_elem = children[event_index + 1] if event_index + 1 < len(children) else None
        event_kind, actor, actor_choice, actor_state_kind, actor_options = (
            _classify_event(rs, elem, next_elem=next_elem)
        )
        event_meta = {
            "index": event_index,
            "tag": tag,
            "kind": event_kind,
            "actor": actor,
        }

        # Step 1: actor's pre-apply record (their decision moment).
        if actor is not None:
            actor_state = _build_state(rs, actor, actor_state_kind, actor_options)
            if legacy:
                yield actor_state
            else:
                yield {
                    "state": actor_state,
                    "choice": actor_choice,
                    "seat": actor,
                    "event": dict(event_meta),
                }

        # Step 2: apply the event to advance state.
        _apply_event(rs, elem, event_kind)

        # Step 3: post-apply records for every other seat.
        for seat in range(4):
            if seat == actor:
                continue
            obs_kind, obs_options = _observer_view(rs, seat, event_kind, actor)
            obs_state = _build_state(rs, seat, obs_kind, obs_options)
            if legacy:
                # Legacy mode emits at decision points only; skip records
                # that have no actionable options (would have been silently
                # dropped by the previous version).
                if obs_kind == "observe":
                    continue
                yield obs_state
            else:
                yield {
                    "state": obs_state,
                    "choice": _make_skip_choice(),
                    "seat": seat,
                    "event": dict(event_meta),
                }


# ---------------------------------------------------------------------------
# Discard option enumeration
# ---------------------------------------------------------------------------


def _discard_options(hand_ids: list[int]) -> list[dict]:
    """Build one `discard` option per slot in the hand. Mirrors live
    state.js which emits {action:'discard', tile, slot} per slot.
    """
    out: list[dict] = []
    for i, tile_id in enumerate(hand_ids):
        out.append({
            "action": "discard",
            "tile": tenhou_to_string(tile_id),
            "slot": i,
        })
    return out
