"""Feature encoder for the MyAI model.

Turns an observer-shape ``state`` dict (as produced by
``parse_tenhou_replay`` or the live ``computeState`` JS) into a pair of
numeric tensors plus a per-head legality mask. Pure-numpy at the
encoder layer so callers can choose torch / jax / numpy downstream.

Output schema
-------------
``encode_state(state)`` returns ``{"planes", "scalars", "mask"}`` where:

- ``planes``  : np.ndarray shape (C_planes, 34) float32 — binary-ish
  feature planes indexed by the 34 base tile types
  (0..8 m, 9..17 p, 18..26 s, 27..33 z).
- ``scalars`` : np.ndarray shape (S,) float32 — round/score/meta
  features and pre-aggregated trainer outputs.
- ``mask``    : dict[str, bool] — which heads can act on this state,
  derived from ``state.actionable.options[]``.

The encoder is intentionally side-effect-free and cheap. Heavier
trainer-driven features (per-tile ukeire/safety) require an extra
``trainer_eval`` parameter; without it we still emit the placeholders
filled with zeros so the model topology never changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np


# ---------------------------------------------------------------------------
# Tile parsing — 34-cell encoding (red fives collapse to their normal cell).
# ---------------------------------------------------------------------------


def tile_to_index_34(tile: str) -> int:
    """Convert a tile string ('1m', '5p*', '3z') to a 0..33 index.

    Red fives ('5m*' / '5p*' / '5s*') collapse to the normal five cell;
    use ``tile_is_red()`` to recover the red flag separately.
    """
    if not tile:
        raise ValueError("empty tile string")
    t = tile[:-1] if tile.endswith("*") else tile
    if len(t) != 2:
        raise ValueError(f"invalid tile {tile!r}")
    try:
        n = int(t[0])
    except ValueError as e:
        raise ValueError(f"invalid tile {tile!r}") from e
    suit = t[1]
    if suit == "m":
        return n - 1
    if suit == "p":
        return n + 8
    if suit == "s":
        return n + 17
    if suit == "z":
        return n + 26
    raise ValueError(f"invalid tile suit in {tile!r}")


def tile_is_red(tile: str) -> bool:
    return tile.endswith("*")


def index_34_to_tile(idx: int) -> str:
    """Inverse of ``tile_to_index_34`` (returns the non-red form)."""
    if not 0 <= idx < 34:
        raise ValueError(idx)
    if idx < 9:
        return f"{idx + 1}m"
    if idx < 18:
        return f"{idx - 8}p"
    if idx < 27:
        return f"{idx - 17}s"
    return f"{idx - 26}z"


# ---------------------------------------------------------------------------
# Plane catalog — declarative list keeps `features.py` in sync with
# `model.py` (which reads NUM_PLANES from here).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlaneSpec:
    name: str
    count: int  # number of channels in this group


_PLANE_SPECS: tuple[PlaneSpec, ...] = (
    PlaneSpec("self_hand_copies",      4),   # >=1, >=2, >=3, ==4
    PlaneSpec("self_red_flag",         1),
    PlaneSpec("self_drawn",            1),
    PlaneSpec("self_meld_chi",         1),
    PlaneSpec("self_meld_pon",         1),
    PlaneSpec("self_meld_kan",         1),
    PlaneSpec("opp_discards",         12),   # 4 opponents x {early, mid, late}
    PlaneSpec("opp_meld_chi",          4),   # 1 per opponent
    PlaneSpec("opp_meld_pon",          4),
    PlaneSpec("opp_meld_kan",          4),
    PlaneSpec("opp_riichi_flag",       4),   # broadcast 0/1
    PlaneSpec("dora_indicators",       1),
    PlaneSpec("dora_tiles",            1),   # derived from indicators
    PlaneSpec("last_discard_tile",     1),
    PlaneSpec("last_discard_seat",     4),   # one-hot local seat 0..3
    PlaneSpec("last_discard_moqie",    1),   # broadcast 0/1
    PlaneSpec("round_wind",            4),   # one-hot E/S/W/N broadcast
    PlaneSpec("my_seat_wind",          4),   # one-hot E/S/W/N broadcast
    PlaneSpec("self_riichi_flag",      1),   # broadcast 0/1
    PlaneSpec("trainer_recommended",   1),   # binary plane: best discard tile
    PlaneSpec("trainer_ukeire_tiles",  1),   # tiles the trainer wants to draw
)

NUM_PLANES = sum(p.count for p in _PLANE_SPECS)

PLANE_INDEX: dict[str, tuple[int, int]] = {}
_offset = 0
for _spec in _PLANE_SPECS:
    PLANE_INDEX[_spec.name] = (_offset, _offset + _spec.count)
    _offset += _spec.count
del _offset, _spec


# ---------------------------------------------------------------------------
# Scalar catalog
# ---------------------------------------------------------------------------


_SCALAR_NAMES: tuple[str, ...] = (
    "left_tile_count_norm",
    "chang_norm",
    "ju_norm",
    "ben_norm",
    "honba_sticks",
    "riichi_sticks_norm",
    "score_self_norm",
    "score_shimo_norm",
    "score_toimen_norm",
    "score_kami_norm",
    "rank_self_norm",
    "any_riichi_flag",
    "is_dealer",
    "shanten_norm",
    "ukeire_norm",
    "has_yaku_flag",
    "trainer_safety_opp1",
    "trainer_safety_opp2",
    "trainer_safety_opp3",
    "in_riichi_self",
    "discard_kind_flag",
    "call_kind_flag",
)

NUM_SCALARS = len(_SCALAR_NAMES)
SCALAR_INDEX: dict[str, int] = {n: i for i, n in enumerate(_SCALAR_NAMES)}


# ---------------------------------------------------------------------------
# Plane writers — small helpers keep the main encoder readable.
# ---------------------------------------------------------------------------


def _slice(planes: np.ndarray, name: str) -> np.ndarray:
    a, b = PLANE_INDEX[name]
    return planes[a:b]


def _bin_count(planes_slice: np.ndarray, counts: np.ndarray) -> None:
    """Fill 4 binary planes encoding count >=1, >=2, >=3, ==4."""
    planes_slice[0] = (counts >= 1).astype(np.float32)
    planes_slice[1] = (counts >= 2).astype(np.float32)
    planes_slice[2] = (counts >= 3).astype(np.float32)
    planes_slice[3] = (counts == 4).astype(np.float32)


def _hand_counts_34(hand_strs: Iterable[str], red_flags: np.ndarray) -> np.ndarray:
    counts = np.zeros(34, dtype=np.int8)
    for s in hand_strs:
        if not s:
            continue
        idx = tile_to_index_34(s)
        counts[idx] += 1
        if tile_is_red(s):
            red_flags[idx] = 1.0
    return counts


def _phase_for_turn(turn_index: int) -> int:
    """0=early (<=5), 1=mid (6..11), 2=late (12+)."""
    if turn_index <= 5:
        return 0
    if turn_index <= 11:
        return 1
    return 2


def _next_tile_34(ind_idx: int) -> int:
    """Tenhou dora-indicator -> dora rotation."""
    if ind_idx < 9:
        return 0 if ind_idx == 8 else ind_idx + 1
    if ind_idx < 18:
        return 9 if ind_idx == 17 else ind_idx + 1
    if ind_idx < 27:
        return 18 if ind_idx == 26 else ind_idx + 1
    if ind_idx < 31:
        return 27 if ind_idx == 30 else ind_idx + 1
    return 31 if ind_idx == 33 else ind_idx + 1


# ---------------------------------------------------------------------------
# Main encoder
# ---------------------------------------------------------------------------


def encode_state(
    state: dict,
    *,
    trainer_eval: object = None,
) -> dict:
    """Encode an observer-state dict into ``{planes, scalars, mask}``."""
    planes = np.zeros((NUM_PLANES, 34), dtype=np.float32)
    scalars = np.zeros(NUM_SCALARS, dtype=np.float32)
    mask = {n: False for n in ("discard", "call", "kan", "riichi", "win")}

    if not isinstance(state, dict):
        return {"planes": planes, "scalars": scalars, "mask": mask}

    actionable = state.get("actionable") or {}
    kind = actionable.get("kind", "observe")
    options = actionable.get("options") or []

    match = state.get("match") or {}
    hand = match.get("hand") or []
    discards = match.get("discards") or [[]] * 4
    melds = match.get("melds") or [[]] * 4
    liqi = match.get("liqi") or [False] * 4
    scores = match.get("scores") or [25000, 25000, 25000, 25000]
    last_discard = match.get("last_discard")
    last_drawn = match.get("last_drawn_tile")
    dora_inds = match.get("dora_indicators") or []
    chang = match.get("chang", 0)
    ju = match.get("ju", 0)
    ben = match.get("ben", 0)
    left = match.get("left_tile_count", 70)

    # --- Self hand --------------------------------------------------------
    red_flags = _slice(planes, "self_red_flag")[0]
    hand_counts = _hand_counts_34(hand, red_flags)
    _bin_count(_slice(planes, "self_hand_copies"), hand_counts)

    if last_drawn:
        try:
            idx = tile_to_index_34(last_drawn)
            _slice(planes, "self_drawn")[0, idx] = 1.0
        except ValueError:
            pass

    # --- Own melds --------------------------------------------------------
    own_melds = melds[0] if melds else []
    for md in own_melds:
        mtype = (md or {}).get("type") if isinstance(md, dict) else None
        tiles = (md or {}).get("tiles") or []
        target = None
        if mtype in (0, "chi"):
            target = _slice(planes, "self_meld_chi")[0]
        elif mtype in (1, "pon"):
            target = _slice(planes, "self_meld_pon")[0]
        elif mtype in (2, 4, 5, "kan_open", "kan_closed", "kan_added"):
            target = _slice(planes, "self_meld_kan")[0]
        if target is None:
            continue
        for t in tiles:
            try:
                target[tile_to_index_34(t)] = 1.0
            except (ValueError, TypeError):
                continue

    # --- Opponent discards (split into early/mid/late by river index) -----
    opp_disc_planes = _slice(planes, "opp_discards")  # shape (12, 34)
    for opp_local in range(1, 4):
        seat_discards = discards[opp_local] if opp_local < len(discards) else []
        for turn_i, t in enumerate(seat_discards or []):
            try:
                idx = tile_to_index_34(t)
            except (ValueError, TypeError):
                continue
            phase = _phase_for_turn(turn_i)
            plane_id = (opp_local - 1) * 3 + phase
            opp_disc_planes[plane_id, idx] = 1.0

    # --- Opponent melds + riichi flag ------------------------------------
    chi_planes = _slice(planes, "opp_meld_chi")
    pon_planes = _slice(planes, "opp_meld_pon")
    kan_planes = _slice(planes, "opp_meld_kan")
    riichi_planes = _slice(planes, "opp_riichi_flag")
    for opp_local in range(4):
        if opp_local < len(liqi) and liqi[opp_local]:
            riichi_planes[opp_local, :] = 1.0
        if opp_local == 0:
            continue
        seat_melds = melds[opp_local] if opp_local < len(melds) else []
        for md in seat_melds or []:
            mtype = (md or {}).get("type") if isinstance(md, dict) else None
            tiles = (md or {}).get("tiles") or []
            if mtype in (0, "chi"):
                target = chi_planes[opp_local]
            elif mtype in (1, "pon"):
                target = pon_planes[opp_local]
            elif mtype in (2, 4, 5, "kan_open", "kan_closed", "kan_added"):
                target = kan_planes[opp_local]
            else:
                continue
            for t in tiles:
                try:
                    target[tile_to_index_34(t)] = 1.0
                except (ValueError, TypeError):
                    continue

    # --- Dora -------------------------------------------------------------
    dora_ind_plane = _slice(planes, "dora_indicators")[0]
    dora_tile_plane = _slice(planes, "dora_tiles")[0]
    for ind in dora_inds:
        try:
            ind_idx = tile_to_index_34(ind)
        except (ValueError, TypeError):
            continue
        dora_ind_plane[ind_idx] = 1.0
        dora_tile_plane[_next_tile_34(ind_idx)] = 1.0

    # --- Last discard ----------------------------------------------------
    if isinstance(last_discard, dict):
        tile = last_discard.get("tile")
        seat = last_discard.get("seat")
        moqie = last_discard.get("is_moqie")
        if tile:
            try:
                idx = tile_to_index_34(tile)
                _slice(planes, "last_discard_tile")[0, idx] = 1.0
            except (ValueError, TypeError):
                pass
        if isinstance(seat, int) and 0 <= seat < 4:
            _slice(planes, "last_discard_seat")[seat, :] = 1.0
        if moqie:
            _slice(planes, "last_discard_moqie")[0, :] = 1.0

    # --- Round/seat winds (broadcast) -------------------------------------
    if 0 <= chang < 4:
        _slice(planes, "round_wind")[chang, :] = 1.0
    my_server_seat = match.get("my_server_seat", 0)
    wind_idx = (my_server_seat - ju) % 4
    _slice(planes, "my_seat_wind")[wind_idx, :] = 1.0

    if liqi and liqi[0]:
        _slice(planes, "self_riichi_flag")[0, :] = 1.0

    # --- Trainer-driven planes/scalars ------------------------------------
    shanten_norm = 0.0
    ukeire_norm = 0.0
    has_yaku = 0.0
    safety_opp = [0.0, 0.0, 0.0]
    if trainer_eval is not None:
        try:
            sh = getattr(trainer_eval, "shanten", 0)
            shanten_norm = (max(-1, min(6, int(sh))) + 1) / 8.0
            uk = getattr(trainer_eval, "current_ukeire", 0)
            ukeire_norm = min(int(uk), 60) / 60.0
            rec = getattr(trainer_eval, "recommended_discard", None)
            if rec:
                try:
                    _slice(planes, "trainer_recommended")[0,
                        tile_to_index_34(rec)] = 1.0
                except (ValueError, TypeError):
                    pass
            for d in getattr(trainer_eval, "discards", []) or []:
                if getattr(d, "is_recommended", False):
                    for t in getattr(d, "ukeire_tiles", []) or []:
                        try:
                            _slice(planes, "trainer_ukeire_tiles")[0,
                                tile_to_index_34(t)] = 1.0
                        except (ValueError, TypeError):
                            continue
                    safs = getattr(d, "safety_per_opponent", []) or []
                    for i, s in enumerate(safs[:3]):
                        safety_opp[i] = max(0.0, float(s)) / 100.0
                    break
        except Exception:
            pass

    # --- Scalars ----------------------------------------------------------
    scalars[SCALAR_INDEX["left_tile_count_norm"]] = float(left) / 70.0
    scalars[SCALAR_INDEX["chang_norm"]] = float(chang) / 3.0
    scalars[SCALAR_INDEX["ju_norm"]] = float(ju) / 3.0
    scalars[SCALAR_INDEX["ben_norm"]] = min(float(ben), 8.0) / 8.0
    scalars[SCALAR_INDEX["honba_sticks"]] = min(float(ben), 8.0) / 8.0
    scalars[SCALAR_INDEX["riichi_sticks_norm"]] = 0.0
    for i, label in enumerate(("score_self_norm", "score_shimo_norm",
                                "score_toimen_norm", "score_kami_norm")):
        sc = scores[i] if i < len(scores) else 25000
        scalars[SCALAR_INDEX[label]] = (float(sc) - 25000.0) / 25000.0
    rank = 0
    if scores:
        better = sum(1 for s in scores[1:] if (s or 0) > (scores[0] or 0))
        rank = better
    scalars[SCALAR_INDEX["rank_self_norm"]] = float(rank) / 3.0
    scalars[SCALAR_INDEX["any_riichi_flag"]] = 1.0 if any(liqi) else 0.0
    scalars[SCALAR_INDEX["is_dealer"]] = 1.0 if my_server_seat == ju else 0.0
    scalars[SCALAR_INDEX["shanten_norm"]] = shanten_norm
    scalars[SCALAR_INDEX["ukeire_norm"]] = ukeire_norm
    scalars[SCALAR_INDEX["has_yaku_flag"]] = has_yaku
    for i, label in enumerate(("trainer_safety_opp1", "trainer_safety_opp2",
                                "trainer_safety_opp3")):
        scalars[SCALAR_INDEX[label]] = safety_opp[i]
    scalars[SCALAR_INDEX["in_riichi_self"]] = 1.0 if (liqi and liqi[0]) else 0.0
    scalars[SCALAR_INDEX["discard_kind_flag"]] = 1.0 if kind == "discard" else 0.0
    scalars[SCALAR_INDEX["call_kind_flag"]] = 1.0 if kind == "call_window" else 0.0

    # --- Mask from legal options -----------------------------------------
    for opt in options:
        a = (opt or {}).get("action") if isinstance(opt, dict) else None
        if a == "discard":
            mask["discard"] = True
        elif a in ("chi", "pon"):
            mask["call"] = True
        elif a == "kan":
            mask["kan"] = True
        elif a == "lizhi":
            mask["riichi"] = True
        elif a in ("hu", "zimo"):
            mask["win"] = True

    return {"planes": planes, "scalars": scalars, "mask": mask}
