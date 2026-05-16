"""Dump a tenhou replay into 4 per-seat JSON files for ML training.

Each output file contains the chronological ``(state, choice, event)``
records yielded by ``parse_tenhou_replay`` for one server seat (0..3).
The 4 files together fully cover every event in the replay from every
player's POV.

Usage
-----
    python tools/dump_replay.py demo/replays/q050_...xml
    # writes 4 files into demo/parsed/q050_.../ :
    #   seat0.json  seat1.json  seat2.json  seat3.json

    python tools/dump_replay.py demo/replays/q050_...xml \\
        --out-dir my_out --format jsonl
    # writes seat{0..3}.jsonl into my_out/<replay-basename>/

Output format
-------------
Default ``--format json`` produces a single JSON object per file:

    {
        "replay":      "<source XML basename>",
        "seat":        0..3,
        "player":      {"name": "...", "rate": ..., "dan": ...}  # from <UN>, if available
        "record_count": <int>,
        "records":     [<per-event record>, ...]
    }

Each record matches what ``parse_tenhou_replay`` yields, with ``seat``
elided (it's constant within a file):

    {
        "event":  {"index", "tag", "kind", "actor"},
        "choice": {"action", ...},
        "state":  <observer-shape state from this seat's POV>
    }

``--format jsonl`` emits one record per line (no envelope) -- standard
for ML data pipelines.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from mahjong_meme.replay import parse_tenhou_replay


def _extract_players(xml_path: Path) -> list[dict]:
    """Parse the <UN> tag for player names + tenhou rate/dan if present.

    Returns a list of 4 dicts (one per server seat); empty dicts when
    metadata is missing.
    """
    out: list[dict] = [{} for _ in range(4)]
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return out

    for elem in root:
        if elem.tag != "UN":
            continue
        # <UN n0="..." n1="..." n2="..." n3="..." dan="..." rate="..." sx="MMFF"/>
        # Names are URL-encoded (percent-escaped UTF-8).
        for i in range(4):
            raw = elem.get(f"n{i}")
            if raw is None:
                continue
            try:
                name = urllib.parse.unquote(raw)
            except Exception:
                name = raw
            out[i]["name"] = name
        dan = elem.get("dan")
        if dan:
            dans = dan.split(",")
            for i in range(min(4, len(dans))):
                try:
                    out[i]["dan"] = int(dans[i])
                except ValueError:
                    pass
        rate = elem.get("rate")
        if rate:
            rates = rate.split(",")
            for i in range(min(4, len(rates))):
                try:
                    out[i]["rate"] = float(rates[i])
                except ValueError:
                    pass
        sx = elem.get("sx")
        if sx:
            # Tenhou writes sx as comma-separated ("M,F,F,F") in modern
            # logs and as concatenated ("MFFM") in older ones.
            sxs = sx.split(",") if "," in sx else list(sx)
            for i in range(min(4, len(sxs))):
                if sxs[i]:
                    out[i]["sex"] = sxs[i]
        break  # only the first UN element matters

    return out


def _strip_record(rec: dict) -> dict:
    """Drop the redundant ``seat`` field (constant within a per-seat file)."""
    return {
        "event":  rec["event"],
        "choice": rec["choice"],
        "state":  rec["state"],
    }


def dump_replay(
    xml_path: Path,
    out_dir: Path,
    *,
    fmt: str = "json",
    indent: int | None = None,
) -> list[Path]:
    """Parse ``xml_path`` and write 4 per-seat files into ``out_dir``.

    Returns the list of files written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    players = _extract_players(xml_path)

    # Pre-create per-seat buckets; for jsonl we stream straight to disk.
    suffix = "jsonl" if fmt == "jsonl" else "json"
    paths = [out_dir / f"seat{i}.{suffix}" for i in range(4)]

    if fmt == "jsonl":
        handles = [p.open("w", encoding="utf-8") for p in paths]
        try:
            counts = [0, 0, 0, 0]
            for rec in parse_tenhou_replay(xml_path):
                seat = rec["seat"]
                line = json.dumps(_strip_record(rec), ensure_ascii=False,
                                  separators=(",", ":"))
                handles[seat].write(line)
                handles[seat].write("\n")
                counts[seat] += 1
        finally:
            for h in handles:
                h.close()
        # Side-car metadata for jsonl.
        meta_path = out_dir / "meta.json"
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump({
                "replay":  xml_path.name,
                "format":  "jsonl",
                "players": players,
                "record_counts": dict(enumerate(counts)),
            }, f, ensure_ascii=False, indent=2)
        return paths + [meta_path]

    # JSON (single object per file).
    buckets: list[list[dict]] = [[], [], [], []]
    for rec in parse_tenhou_replay(xml_path):
        buckets[rec["seat"]].append(_strip_record(rec))

    for seat in range(4):
        envelope = {
            "replay":       xml_path.name,
            "seat":         seat,
            "player":       players[seat],
            "record_count": len(buckets[seat]),
            "records":      buckets[seat],
        }
        with paths[seat].open("w", encoding="utf-8") as f:
            json.dump(envelope, f, ensure_ascii=False, indent=indent,
                      separators=(",", ":") if indent is None else None)
    return paths


def _dump_one_worker(args_tuple):
    """Worker entrypoint for multiprocessing pool."""
    xml_path, base, fmt, indent, skip_existing = args_tuple
    out_dir = base / xml_path.stem
    if skip_existing:
        if (out_dir / f"seat0.{'jsonl' if fmt == 'jsonl' else 'json'}").exists():
            return (xml_path.name, "skip", 0)
    try:
        files = dump_replay(xml_path, out_dir, fmt=fmt, indent=indent)
        size_kb = sum(f.stat().st_size for f in files) / 1024
        return (xml_path.name, "ok", size_kb)
    except Exception as e:
        return (xml_path.name, f"error: {e!r}", 0)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xml", nargs="+",
                   help="Path(s) to tenhou replay XML file(s), or directories "
                        "containing them. Multiple inputs: each XML gets its "
                        "own subfolder.")
    p.add_argument("--out-dir", default=None,
                   help="Base output directory. Per-replay subfolder is "
                        "created inside. Default: demo/parsed/")
    p.add_argument("--format", choices=["json", "jsonl"], default="json",
                   help="Output format. json = one envelope per file (default); "
                        "jsonl = newline-delimited record stream + meta.json sidecar.")
    p.add_argument("--indent", type=int, default=None,
                   help="Pretty-print JSON with this indent (json format only). "
                        "Default: compact.")
    p.add_argument("--quiet", action="store_true", help="Suppress per-file logging.")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip replays whose output folder already has seat0 dumped.")
    p.add_argument("--workers", "-j", type=int, default=1,
                   help="Number of parallel worker processes (default: 1).")
    args = p.parse_args()

    base = Path(args.out_dir) if args.out_dir else REPO / "demo" / "parsed"

    # Expand directories into their *.xml contents.
    inputs: list[Path] = []
    for arg in args.xml:
        path = Path(arg)
        if path.is_dir():
            inputs.extend(sorted(path.glob("*.xml")))
        else:
            inputs.append(path)

    work = [(xml_path, base, args.format, args.indent, args.skip_existing)
            for xml_path in inputs]

    rc = 0
    done = 0
    t0 = __import__("time").time()
    if args.workers > 1:
        import multiprocessing as mp
        with mp.Pool(processes=args.workers) as pool:
            for name, status, size_kb in pool.imap_unordered(
                    _dump_one_worker, work, chunksize=4):
                done += 1
                if status == "ok":
                    if not args.quiet:
                        print(f"  [{done}/{len(work)}] {name}  ({size_kb:.0f} KB)",
                              flush=True)
                elif status == "skip":
                    pass
                else:
                    print(f"  [{done}/{len(work)}] {name}  {status}",
                          file=sys.stderr, flush=True)
                    rc = 1
                if done % 50 == 0:
                    dt = __import__("time").time() - t0
                    rate = done / max(dt, 1e-9)
                    eta = (len(work) - done) / max(rate, 1e-9)
                    print(f"  [{done}/{len(work)}] rate={rate:.1f}/s "
                          f"ETA={eta:.0f}s", flush=True)
    else:
        for item in work:
            name, status, size_kb = _dump_one_worker(item)
            done += 1
            if status == "ok" and not args.quiet:
                print(f"  [{done}/{len(work)}] {name}  ({size_kb:.0f} KB)",
                      flush=True)
            elif status not in ("ok", "skip"):
                print(f"  [{done}/{len(work)}] {name}  {status}",
                      file=sys.stderr, flush=True)
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
