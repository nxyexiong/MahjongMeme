"""Tests for the yaku wrapper around the MahjongRepository/mahjong package."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from mahjong_meme.trainer import HanError, calculate_han, make_meld

CASES = [
    # ---------- Errors ----------
    ("not_complete",
     dict(concealed_hand=["1m","2m","3m","4p","5p","6p","7s","8s","9s","1z","2z","3z","4z","5z"],
          win_tile="5z"),
     dict(error=HanError.NOT_COMPLETE)),

    ("invalid_size",
     dict(concealed_hand=["1m","2m","3m"], win_tile="3m"),
     dict(error=HanError.INVALID_INPUT)),

    # ---------- Pinfu ----------
    ("pinfu_ron",
     dict(concealed_hand=["1m","2m","3m","5m","6m","7m","2p","3p","4p","5s","5s","6s","7s"],
          win_tile="8s", is_tsumo=False),
     dict(han=1, fu=30, yaku_contains={"Pinfu"})),

    ("pinfu_tsumo",
     dict(concealed_hand=["1m","2m","3m","5m","6m","7m","2p","3p","4p","5s","5s","6s","7s"],
          win_tile="8s", is_tsumo=True),
     dict(han=2, fu=20, yaku_contains={"Pinfu", "Menzen Tsumo"})),

    # ---------- Tanyao ----------
    ("tanyao_open",
     dict(concealed_hand=["2m","3m","4m","5p","6p","7p","2s","2s","2s","3s"],
          melds=[make_meld("pon", ["6s","6s","6s"])],
          win_tile="4s"),
     dict(han_at_least=1, yaku_contains={"Tanyao"})),

    # ---------- Yakuhai ----------
    ("yakuhai_haku",
     dict(concealed_hand=["1m","2m","3m","4p","5p","6p","7s","8s","9s","2z","2z","5z","5z","5z"],
          win_tile="2z"),
     dict(han_at_least=1, yaku_contains={"Yakuhai (haku)"})),

    # ---------- Iipeiko ----------
    ("iipeiko",
     dict(concealed_hand=["2m","3m","4m","2m","3m","4m","5p","6p","7p","2s","3s","4s","9s","9s"],
          win_tile="4s"),
     dict(yaku_contains={"Iipeiko"})),

    # ---------- Sanshoku doujun ----------
    ("sanshoku",
     dict(concealed_hand=["2m","3m","4m","2p","3p","4p","2s","3s","4s","6s","7s","8s","9s","9s"],
          win_tile="9s"),
     dict(yaku_contains={"Sanshoku Doujun"})),

    # ---------- Ittsu ----------
    ("ittsu_closed",
     dict(concealed_hand=["1m","2m","3m","4m","5m","6m","7m","8m","9m","2p","3p","4p","5z","5z"],
          win_tile="4p"),
     dict(yaku_contains={"Ittsu"})),

    # ---------- Toitoi + Sanankou ----------
    ("toitoi_sanankou",
     dict(concealed_hand=["5p","5p","5p","7s","7s","7s","9s","9s","9s","5z","5z"],
          melds=[make_meld("pon", ["1m","1m","1m"])],
          win_tile="5z"),
     dict(yaku_contains={"Toitoi", "San Ankou"})),

    # ---------- Chiitoitsu ----------
    ("chiitoitsu",
     dict(concealed_hand=["1m","1m","3m","3m","5p","5p","7p","7p","2s","2s","4s","4s","9s","9s"],
          win_tile="9s"),
     dict(yaku_contains={"Chiitoitsu"}, fu=25)),

    # ---------- Honitsu / Chinitsu ----------
    ("honitsu_closed",
     dict(concealed_hand=["1m","2m","3m","4m","5m","6m","7m","8m","9m","2m","2m","5z","5z","5z"],
          win_tile="2m"),
     dict(yaku_contains={"Honitsu"})),

    ("chinitsu_closed",
     dict(concealed_hand=["1m","2m","3m","4m","5m","6m","7m","8m","9m","2m","2m","5m","5m","5m"],
          win_tile="2m"),
     dict(yaku_contains={"Chinitsu"})),

    # ---------- Honroutou ----------
    ("honroutou",
     dict(concealed_hand=["1m","1m","1m","9p","9p","9p","9s","9s","9s","1z","1z","5z","5z","5z"],
          win_tile="5z"),
     dict(yaku_contains={"Honroutou"})),

    # ---------- Riichi + Tsumo + Pinfu ----------
    ("riichi_tsumo_pinfu",
     dict(concealed_hand=["1m","2m","3m","5m","6m","7m","2p","3p","4p","5s","5s","6s","7s"],
          win_tile="8s", is_tsumo=True, is_riichi=True),
     dict(han=3, yaku_contains={"Riichi", "Menzen Tsumo", "Pinfu"})),

    # ---------- Yakuman ----------
    ("kokushi",
     dict(concealed_hand=["1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z","1z"],
          win_tile="1z"),
     dict(yakuman_at_least=1)),

    ("daisangen",
     dict(concealed_hand=["1m","2m","3m","5z","5z","5z","6z","6z","6z","7z","7z","7z","2p","2p"],
          win_tile="2p"),
     dict(yakuman_at_least=1)),

    ("tsuiisou",
     dict(concealed_hand=["1z","1z","1z","2z","2z","2z","3z","3z","3z","5z","5z","5z","6z","6z"],
          win_tile="6z"),
     dict(yakuman_at_least=1)),

    ("suuankou_tsumo",
     dict(concealed_hand=["1m","1m","1m","5p","5p","5p","7s","7s","7s","2z","2z","2z","5z","5z"],
          win_tile="2z", is_tsumo=True),
     dict(yakuman_at_least=1)),

    # ---------- Dora ----------
    ("dora_count",
     dict(concealed_hand=["1m","2m","3m","5m","6m","7m","2p","3p","4p","5s","5s","6s","7s"],
          win_tile="8s", is_tsumo=True, dora_indicators=["4m"]),  # dora = 5m
     dict(han_at_least=3)),

    ("aka_dora",
     dict(concealed_hand=["1m","2m","3m","5m*","6m","7m","2p","3p","4p","5s","5s","6s","7s"],
          win_tile="8s", is_tsumo=True),
     dict(han_at_least=3)),
]


def _verify(name, res, expected):
    fails = []
    if "error" in expected:
        if res.error != expected["error"]:
            fails.append(f"error: expected {expected['error'].name}, got {res.error.name}")
        return fails  # If we expect an error, skip other checks
    if res.error != HanError.NONE:
        fails.append(f"unexpected error: {res.error.name} ({res.error_detail})")
        return fails
    if "han" in expected and res.han != expected["han"]:
        fails.append(f"han: expected {expected['han']}, got {res.han}")
    if "han_at_least" in expected and res.han < expected["han_at_least"]:
        fails.append(f"han: expected >= {expected['han_at_least']}, got {res.han}")
    if "fu" in expected and res.fu != expected["fu"]:
        fails.append(f"fu: expected {expected['fu']}, got {res.fu}")
    if "yakuman_at_least" in expected and res.yakuman < expected["yakuman_at_least"]:
        fails.append(f"yakuman: expected >= {expected['yakuman_at_least']}, got {res.yakuman}")
    if "yaku_contains" in expected:
        got = {y for y in res.yaku}
        miss = expected["yaku_contains"] - got
        if miss:
            fails.append(f"yaku missing: {sorted(miss)}; got {sorted(got)}")
    return fails


def main():
    failures = []
    for name, kwargs, expected in CASES:
        try:
            res = calculate_han(**kwargs)
        except Exception as e:
            failures.append((name, [f"EXCEPTION: {e!r}"], None))
            continue
        f = _verify(name, res, expected)
        if f:
            failures.append((name, f, res))
    if failures:
        print("FAILURES:")
        for entry in failures:
            name, fs = entry[0], entry[1]
            res = entry[2] if len(entry) > 2 else None
            print(f"  {name}:")
            for line in fs:
                print(f"    - {line}")
            if res is not None:
                print(f"    got: han={res.han} fu={res.fu} yakuman={res.yakuman}")
                print(f"         yaku={res.yaku}")
                print(f"         error={res.error.name} ({res.error_detail})")
        return 1
    print(f"OK — {len(CASES)} cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
