"""Quick sanity check: predict on a few decision points from a parsed replay."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from mahjong_meme.myai.predict import MyAIPredictor


def _load_records(path: Path):
    """Yield record dicts from either .json (envelope) or .jsonl files."""
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data.get("records", []):
            yield r


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/check_myai_predict.py <checkpoint> [replay_dir]")
        return 2
    ckpt = sys.argv[1]
    if len(sys.argv) >= 3:
        replay_dir = Path(sys.argv[2])
    else:
        # pick the first replay directory
        replay_dir = next((REPO / "demo" / "parsed").iterdir())

    # prefer jsonl, fall back to json
    seat_file = replay_dir / "seat0.jsonl"
    if not seat_file.exists():
        seat_file = replay_dir / "seat0.json"

    predictor = MyAIPredictor(ckpt)
    print(f"checkpoint: {ckpt}")
    print(f"replay:     {seat_file}\n")

    n_match = 0
    n_total = 0
    for r in _load_records(seat_file):
        if (r["state"]["actionable"]["kind"] != "discard"
                or r["choice"]["action"] != "discard"):
            continue
        out = predictor.recommend(r["state"], topk=3)
        actual = r["choice"].get("tile")
        rec = out["action"].get("tile")
        match = actual == rec
        n_total += 1
        if match:
            n_match += 1
        if n_total <= 10:
            tag = "OK" if match else " ."
            top3 = ", ".join(f"{a.get('tile')}@{p:.2f}"
                             for a, p in out["topk"])
            print(f"  [{tag}] event#{r['event']['index']:>3}  "
                  f"actual={actual:>4}  predicted={rec:>4}  top3=[{top3}]")
    print(f"\nDiscard top-1 agreement on this replay: "
          f"{n_match}/{n_total} = {100 * n_match / max(1, n_total):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
