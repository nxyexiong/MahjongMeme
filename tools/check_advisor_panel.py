"""Smoke test: feed a real replay state through the advisor panel."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> int:
    from mahjong_meme.advisors import build_default_advisors
    from mahjong_meme.observer import _render_advisor_panel

    advisors = build_default_advisors()
    print(f"[advisors] loaded: {[a.name for a in advisors]}\n")

    # Find a discard-kind state and a call-window state from any replay.
    replay_root = REPO / "demo" / "parsed"
    first_replay = next(d for d in replay_root.iterdir() if d.is_dir())
    seat0 = first_replay / "seat0.jsonl"
    if not seat0.exists():
        seat0 = first_replay / "seat0.json"

    discard_state = None
    call_state = None

    def _iter_records(p: Path):
        if p.suffix == ".jsonl":
            with p.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        yield json.loads(line)
        else:
            for r in json.loads(p.read_text(encoding="utf-8"))["records"]:
                yield r

    for r in _iter_records(seat0):
        state = r["state"]
        kind = state["actionable"]["kind"]
        if kind == "discard" and r["choice"]["action"] == "discard" and discard_state is None:
            discard_state = state
            actual_discard = r["choice"]
        if kind == "call_window" and call_state is None:
            opts = state["actionable"]["options"]
            if any(o["action"] != "pass" for o in opts):
                call_state = state
                actual_call = r["choice"]
        if discard_state and call_state:
            break

    if discard_state:
        print("=" * 72)
        print(f"DISCARD STATE   actual choice = {actual_discard}")
        print("-" * 72)
        panel = _render_advisor_panel(discard_state, advisors)
        print(panel or "<no advice>")

    if call_state:
        print("\n" + "=" * 72)
        print(f"CALL WINDOW STATE   actual choice = {actual_call}")
        print("-" * 72)
        panel = _render_advisor_panel(call_state, advisors)
        print(panel or "<no advice>")

    return 0


if __name__ == "__main__":
    sys.exit(main())
