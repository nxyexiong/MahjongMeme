"""Walk a tenhou replay and print decision states + trainer advice."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# Force UTF-8 console output so Japanese names render.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from mahjong_meme.replay import parse_tenhou_replay


def _lazy_trainer_advice():
    """Import _trainer_advice lazily — observer.py pulls in playwright,
    which is only needed when --advice is requested."""
    from mahjong_meme.observer import _trainer_advice
    return _trainer_advice


def _choice_str(choice: dict) -> str:
    act = choice.get("action", "?")
    if act == "discard":
        return f"discard {choice.get('tile')}@slot{choice.get('slot')}"
    if act in ("chi", "pon", "kan"):
        sub = (choice.get("extra") or {}).get("subtype")
        tiles = (choice.get("extra") or {}).get("tiles") or []
        suffix = f" [{','.join(tiles)}]" if tiles else ""
        return f"{act}{':' + sub if sub else ''}{suffix}"
    return act


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("xml", help="Path to a tenhou replay XML.")
    p.add_argument("--limit", type=int, default=5,
                   help="Print this many records (default: 5).")
    p.add_argument("--from-seat", type=int, default=None,
                   help="Only show records where seat matches this (0..3).")
    p.add_argument("--kind", choices=["discard", "call_window", "observe"], default=None,
                   help="Only show records whose state.actionable.kind matches this.")
    p.add_argument("--event-kind", default=None,
                   help="Only show records for this event kind "
                        "(draw|discard|call|agari|riichi|init|dora|ryuukyoku).")
    p.add_argument("--choice", default=None,
                   help="Only show records where the chosen action matches "
                        "(e.g. 'discard', 'pon', 'skip').")
    p.add_argument("--skip", type=int, default=0,
                   help="Skip the first N matching records.")
    p.add_argument("--advice", action="store_true",
                   help="Run the trainer on each shown state and print its advice.")
    p.add_argument("--full", action="store_true",
                   help="Print the entire record dict (default: compact summary).")
    args = p.parse_args()

    shown = 0
    skipped = 0
    total = 0
    for record in parse_tenhou_replay(args.xml):
        total += 1
        state = record["state"]
        choice = record["choice"]
        seat = record["seat"]
        event = record["event"]
        if args.from_seat is not None and seat != args.from_seat:
            continue
        if args.kind is not None and state["actionable"]["kind"] != args.kind:
            continue
        if args.event_kind is not None and event["kind"] != args.event_kind:
            continue
        if args.choice is not None and choice.get("action") != args.choice:
            continue
        if skipped < args.skip:
            skipped += 1
            continue
        if shown >= args.limit:
            break

        m = state["match"]
        kind = state["actionable"]["kind"]
        print(f"\n=== record #{shown + 1}  event=#{event['index']} {event['tag']}/{event['kind']}"
              f"  seat={seat}{'(actor)' if event['actor'] == seat else ''}"
              f"  state_kind={kind}  E{m['chang']}-{m['ju']+1}  left={m['left_tile_count']} ===")
        print(f"  hand:     {' '.join(m['hand'])}")
        if m['last_drawn_tile']:
            print(f"  drawn:    {m['last_drawn_tile']}")
        own_melds = m['melds'][0] if m['melds'] and m['melds'][0] else []
        if own_melds:
            print(f"  melds:    {[md.get('tiles') if isinstance(md, dict) else md for md in own_melds]}")
        print(f"  dora:     {m['dora_indicators']}")
        ld = m["last_discard"]
        if ld:
            print(f"  last_disc: seat={ld['seat']}  tile={ld['tile']}")
        n_opts = len(state["actionable"]["options"])
        print(f"  options:  {n_opts} legal action(s)")
        print(f"  CHOICE:   {_choice_str(choice)}")

        if args.full:
            print(json.dumps(record, ensure_ascii=False, indent=2))

        if args.advice:
            advice = _lazy_trainer_advice()(state)
            if advice:
                for line in advice.split("\n"):
                    print(f"  {line}")
            else:
                print("  [trainer] no advice for this state")

        shown += 1

    print(f"\n[{Path(args.xml).name}] total records: {total}  shown: {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
