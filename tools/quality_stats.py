"""Scan tenhou's available phoenix archives and report the
distribution of quality_score (sum of player frequencies).

Tenhou serves two archive formats:

  hourly:  /sc/raw/dat/scc{YYYYMMDDHH}.html.gz       (last ~45 days)
  daily:   /sc/raw/dat/{YYYY}/scc{YYYYMMDD}.html.gz  (~50-135 days back)

Older than ~135 days is no longer hosted. This script auto-picks
the right endpoint for each calendar day in the requested window
and falls back gracefully on 404.

Usage:
    python tools/quality_stats.py --scan-days 135
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "demo"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import download as dl  # type: ignore


USER_AGENT = dl.USER_AGENT
DELAY_S = 1.3   # honor tenhou's ≥1.2s request spacing


def fetch(url: str) -> bytes | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def fetch_day_hourly(day: dt.date, prefix: str, log) -> list[dl.Game]:
    """Fetch all 24 hourly listings for one day; concat the parsed games."""
    out: list[dl.Game] = []
    for h in range(24):
        stamp = day.strftime("%Y%m%d") + f"{h:02d}"
        url = f"https://tenhou.net/sc/raw/dat/scc{stamp}.html.gz"
        try:
            data = fetch(url)
        except Exception as e:
            log(f"   hourly {stamp}: {e!r}")
            time.sleep(DELAY_S)
            continue
        if data is None:
            time.sleep(DELAY_S)
            continue
        html = data.decode("utf-8", errors="replace")
        out.extend(dl.parse_games(html, prefix, stamp))
        time.sleep(DELAY_S)
    return out


def fetch_day_daily(day: dt.date, prefix: str, log) -> list[dl.Game] | None:
    """Fetch one daily aggregate; None if not found."""
    ymd = day.strftime("%Y%m%d")
    url = f"https://tenhou.net/sc/raw/dat/{day.year}/scc{ymd}.html.gz"
    try:
        data = fetch(url)
    except Exception as e:
        log(f"   daily {ymd}: {e!r}")
        return None
    if data is None:
        return None
    html = data.decode("utf-8", errors="replace")
    return dl.parse_games(html, prefix, ymd + "00")


def percentile(sorted_vals: list[int], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scan-days", type=int, default=135,
                   help="Calendar days back to scan (default: 135).")
    p.add_argument("--sanma", action="store_true")
    p.add_argument("--out", default=str(REPO / "tools" / "quality_scan.txt"))
    args = p.parse_args()

    prefix = dl.PREFIX_3P if args.sanma else dl.PREFIX_4P
    label = "sanma" if args.sanma else "4p"

    t0 = time.time()
    jst_now = dt.datetime.utcnow() + dt.timedelta(hours=9)
    today = jst_now.date()
    # Skip today (incomplete) and yesterday (just to be safe).
    days = [today - dt.timedelta(days=d) for d in range(2, 2 + args.scan_days)]
    print(f"[stats] target: {label} phoenix, {len(days)} days "
          f"({days[-1]} → {days[0]})", flush=True)

    all_games: list[dl.Game] = []
    daily_skipped = 0
    for i, day in enumerate(days, 1):
        # Prefer daily aggregate (one HTTP call vs 24); fall back to hourly.
        gs = fetch_day_daily(day, prefix, log=print)
        time.sleep(DELAY_S)
        if gs is None:
            # Daily archive not available; try hourly.
            gs = fetch_day_hourly(day, prefix, log=print)
            mode = "hourly"
        else:
            mode = "daily "
        all_games.extend(gs)
        elapsed = time.time() - t0
        rate = i / max(elapsed, 0.001)
        eta = (len(days) - i) / max(rate, 0.001)
        print(f"[stats] {i:3d}/{len(days)}  {day}  {mode}: "
              f"+{len(gs):4d}  (cum={len(all_games):6d}, eta {eta/60:.0f}m)",
              flush=True)

    print(f"[stats] scan done in {(time.time()-t0)/60:.1f} min; "
          f"{len(all_games)} games total")

    if not all_games:
        print("[stats] no games found")
        return 1

    freq: Counter[str] = Counter()
    for g in all_games:
        for pl in g.players:
            freq[pl] += 1

    qualities = sorted(sum(freq[pl] for pl in g.players) for g in all_games)
    n = len(qualities)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(str(q) for q in qualities), encoding="utf-8")

    print()
    print(f"[stats] Quality score distribution over {n} games "
          f"(window={args.scan_days} days, format={label}):")
    print(f"  n      = {n}")
    print(f"  min    = {qualities[0]}")
    print(f"  p25    = {percentile(qualities, 25):.1f}")
    print(f"  p50    = {percentile(qualities, 50):.1f}")
    print(f"  p75    = {percentile(qualities, 75):.1f}")
    print(f"  p90    = {percentile(qualities, 90):.1f}")
    print(f"  p95    = {percentile(qualities, 95):.1f}")
    print(f"  p99    = {percentile(qualities, 99):.1f}")
    print(f"  max    = {qualities[-1]}")
    print(f"  mean   = {statistics.mean(qualities):.1f}")
    print(f"  stdev  = {statistics.pstdev(qualities):.1f}")
    print(f"  unique players in window = {len(freq)}")
    print(f"  top players by appearances:")
    for name, cnt in freq.most_common(10):
        print(f"    {cnt:4d}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

