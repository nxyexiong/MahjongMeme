"""Compare the Python port against JS reference data emitted by
tools/parity_export.js.

Run:
    cmd /c "node tools\\parity_export.js > tools\\parity_expected.json"
    .\\src\\.venv\\Scripts\\python tools\\check_parity.py

(Use `cmd /c` for the redirect rather than PowerShell's `>` because the
latter adds a UTF-8 BOM that json.loads chokes on.)

Exits non-zero on any mismatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

from mahjong_meme.trainer.evaluations import evaluate_best_discard
from mahjong_meme.trainer.shanten import (
    calculate_minimum_shanten,
    calculate_standard_shanten,
)
from mahjong_meme.trainer.tiles import (
    ALL_TILES_REMAINING,
    HAND_SIZE,
    merge_red_fives,
    parse_tile,
)
from mahjong_meme.trainer.ukeire import (
    calculate_discard_ukeire,
    calculate_ukeire,
)


def tile_counts(strings):
    c = [0] * HAND_SIZE
    for s in strings:
        c[parse_tile(s)] += 1
    return c


def remaining_from_visible(visible, hand):
    v = [0] * HAND_SIZE
    for t in visible:
        v[parse_tile(t)] += 1
    for t in hand:
        v[parse_tile(t)] += 1
    v = merge_red_fives(v)
    return [max(0, ALL_TILES_REMAINING[i] - v[i]) for i in range(HAND_SIZE)]


CASES = [
    {
        "name": "tenpai_shanpon",
        "hand": ["1m","2m","3m","4p","5p","6p","7s","8s","9s","1z","1z","2z","2z"],
        "visible": [],
    },
    {
        "name": "discard_basic",
        "hand": ["1m","2m","3m","4p","5p","6p","7s","8s","9s","1z","1z","5m","5m*","3z"],
        "visible": [],
    },
    {
        "name": "chiitoi_1shanten",
        "hand": ["1m","1m","3m","3m","5p","5p","7p","7p","2s","2s","4s","9s","9s","3z"],
        "visible": [],
    },
    {
        "name": "kokushi_1shanten",
        "hand": ["1m","9m","1p","9p","1s","9s","1z","2z","3z","4z","5z","6z","7z","5m"],
        "visible": [],
    },
    {
        "name": "complete_standard",
        "hand": ["1m","2m","3m","4p","5p","6p","7s","8s","9s","1z","1z","2z","2z","2z"],
        "visible": [],
    },
    {
        "name": "limited_ukeire",
        "hand": ["1m","2m","3m","4p","5p","6p","7s","8s","9s","1z","1z","5m","5m","3m"],
        "visible": ["3z","3z","3z","3z"],
    },
]


def compute(case):
    hand = tile_counts(case["hand"])
    remaining = remaining_from_visible(case["visible"], case["hand"])
    min_shan = calculate_minimum_shanten(hand)
    std_shan = calculate_standard_shanten(hand)
    if len(case["hand"]) == 14:
        per = calculate_discard_ukeire(
            hand, remaining, calculate_minimum_shanten, min_shan
        )
        per_dict = [
            {"index": i, "value": r.value, "tiles": list(r.tiles)}
            for i, r in enumerate(per)
        ]
        best = evaluate_best_discard([r.value for r in per])
        cur = per_dict[best]["value"] if best >= 0 else 0
        return {
            "name": case["name"],
            "shanten": min_shan,
            "shanten_standard": std_shan,
            "current_ukeire": cur,
            "best_discard_index": best,
            "per_discard": per_dict,
        }
    u = calculate_ukeire(hand, remaining, calculate_minimum_shanten, min_shan)
    return {
        "name": case["name"],
        "shanten": min_shan,
        "shanten_standard": std_shan,
        "current_ukeire": u.value,
        "best_discard_index": None,
        "per_discard": None,
    }


def main() -> int:
    expected_path = REPO / "tools" / "parity_expected.json"
    if not expected_path.exists():
        print(
            f"missing {expected_path}; run "
            f'cmd /c "node tools\\parity_export.js > tools\\parity_expected.json" first'
        )
        return 2
    expected = json.loads(expected_path.read_text(encoding="utf-8-sig"))
    expected_by_name = {e["name"]: e for e in expected}

    failures: list[str] = []
    for case in CASES:
        got = compute(case)
        exp = expected_by_name.get(case["name"])
        if exp is None:
            failures.append(f"{case['name']}: no expected data")
            continue
        for key in ("shanten", "shanten_standard", "current_ukeire", "best_discard_index"):
            if got.get(key) != exp.get(key):
                failures.append(
                    f"{case['name']}.{key}: expected {exp.get(key)!r}, got {got.get(key)!r}"
                )
        if got["per_discard"] is not None and exp["per_discard"] is not None:
            for i in range(HAND_SIZE):
                gv = got["per_discard"][i]
                ev = exp["per_discard"][i]
                if gv["value"] != ev["value"]:
                    failures.append(
                        f"{case['name']}.per_discard[{i}].value: "
                        f"expected {ev['value']}, got {gv['value']}"
                    )
                if sorted(gv["tiles"]) != sorted(ev["tiles"]):
                    failures.append(
                        f"{case['name']}.per_discard[{i}].tiles: "
                        f"expected {ev['tiles']}, got {gv['tiles']}"
                    )

    if failures:
        print("PARITY FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print(f"OK — {len(CASES)} cases match JS reference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

