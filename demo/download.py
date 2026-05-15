"""Download top-tier replays from tenhou.net phoenix room (鳳凰卓).

Phoenix room is already gated to 8-dan and above, but skill spread within
it is wide: a 天鳳位 (the highest rank, ~12 players ever) plays many
games per day, while a fresh 8-dan plays only occasionally. We exploit
this by:

  1. Scanning the last N hours of phoenix listings (default: 24h).
  2. Building a per-player appearance frequency table.
  3. Scoring each game by the SUM of its four players' frequencies.
  4. Downloading the top --count games.

This naturally surfaces matchups featuring multiple repeat phoenix-room
grinders — the closest approximation to "high-quality" available from
public tenhou data without scraping per-user profile pages.

Tenhou's documented rules are honored:
- Maximum one concurrent session.
- ≥1.2s between requests (well above their suggested rate limit).
- Only the documented .html.gz / ?log= endpoints.
- Normal browser User-Agent.

Reference: https://tenhou.net/sc/raw/
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Force UTF-8 output so Japanese player names render correctly even on
# Windows consoles defaulting to cp932/cp1252. Safe no-op on POSIX.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SCC_BASE = "https://tenhou.net/sc/raw/dat"
LOG_BASE = "https://tenhou.net/0/log"
REQUEST_DELAY_S = 1.2

# Phoenix-room game ID prefixes.
PREFIX_4P = "gm-00a9"  # 四鳳南喰赤
PREFIX_3P = "gm-00b9"  # 三鳳南喰赤


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# Format of each <li> in the phoenix listing (example):
#   19:00 | 33 | 四鳳南喰赤－ | <a href="http://tenhou.net/0/?log=2026051419gm-00a9-0000-54f3f37b">牌譜</a> |
#       こだわりパジャマ(+52.5) 豊臣軍陸(+17.4) 新子望(-22.5) ぽん助(-47.4)<br>
GAME_LINE_RE = re.compile(
    r'log=(?P<game_id>[0-9]+gm-[0-9a-f]+-[0-9a-f]+-[0-9a-f]+)"[^>]*>[^<]*</a>'
    r'\s*\|\s*(?P<players>[^<]+)<br>',
    re.UNICODE,
)
# Player+score pattern: <name>(+/-NN.N), greedy but stops before next paren.
PLAYER_RE = re.compile(r'(?P<name>[^()\s][^()]*?)\(([\+\-][0-9.]+)\)', re.UNICODE)


@dataclass
class Game:
    game_id: str
    hour_stamp: str        # YYYYMMDDHH the listing it came from
    players: list[str]     # 3 (sanma) or 4 (4p)
    scores: list[float]    # final point deltas


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _request(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(), resp.headers.get("Content-Encoding", "")


def fetch_hour_listing(hour_stamp: str) -> str:
    """Download a single hourly phoenix log gz and return the HTML."""
    url = f"{SCC_BASE}/scc{hour_stamp}.html.gz"
    data, _enc = _request(url)
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def fetch_replay(game_id: str) -> bytes:
    """Download one replay XML."""
    url = f"{LOG_BASE}/?{game_id}"
    data, _enc = _request(url)
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_games(html: str, prefix: str, hour_stamp: str) -> list[Game]:
    """Pull all phoenix games matching `prefix` from an hour listing."""
    games: list[Game] = []
    for m in GAME_LINE_RE.finditer(html):
        gid = m.group("game_id")
        if prefix not in gid:
            continue
        names: list[str] = []
        scores: list[float] = []
        for pm in PLAYER_RE.finditer(m.group("players")):
            name = pm.group("name").strip()
            try:
                score = float(pm.group(2))
            except ValueError:
                continue
            if name:
                names.append(name)
                scores.append(score)
        if len(names) in (3, 4):
            games.append(Game(
                game_id=gid, hour_stamp=hour_stamp,
                players=names, scores=scores,
            ))
    return games


# ---------------------------------------------------------------------------
# Window scanning + ranking
# ---------------------------------------------------------------------------


def hour_stamps_back(hours_back: int) -> list[str]:
    """Return YYYYMMDDHH stamps for the last `hours_back` hours in JST,
    starting 2 hours ago (so the most recent listing is fully populated)."""
    jst_now = dt.datetime.utcnow() + dt.timedelta(hours=9)
    out: list[str] = []
    for offset in range(2, 2 + hours_back):
        stamp = (jst_now - dt.timedelta(hours=offset)).strftime("%Y%m%d%H")
        out.append(stamp)
    return out


def scan_window(
    prefix: str, hours: int, *, log: callable = print,
) -> list[Game]:
    """Fetch the last `hours` of phoenix listings; return all parsed games."""
    stamps = hour_stamps_back(hours)
    log(f"[demo] scanning {len(stamps)} hours of phoenix listings…")
    all_games: list[Game] = []
    for i, stamp in enumerate(stamps, 1):
        try:
            if i > 1:
                time.sleep(REQUEST_DELAY_S)
            html = fetch_hour_listing(stamp)
        except urllib.error.HTTPError as e:
            log(f"[demo]   {stamp}: HTTP {e.code} {e.reason}")
            continue
        except Exception as e:
            log(f"[demo]   {stamp}: {e!r}")
            continue
        games = parse_games(html, prefix, stamp)
        all_games.extend(games)
        log(f"[demo]   {stamp}: {len(games):3d} games "
            f"(cumulative: {len(all_games)})")
    return all_games


def rank_games(games: list[Game]) -> list[tuple[Game, int, list[int]]]:
    """Sort games by quality (sum of player frequencies in this scan window).

    Returns a list of (game, quality_score, per_player_freqs) tuples,
    sorted highest quality first.
    """
    freq: Counter[str] = Counter()
    for g in games:
        for p in g.players:
            freq[p] += 1
    scored = []
    for g in games:
        per_player = [freq[p] for p in g.players]
        quality = sum(per_player)
        scored.append((g, quality, per_player))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--count", "-n", type=int, default=8,
                   help="Number of replays to download (default: 8).")
    p.add_argument("--scan-hours", type=int, default=24,
                   help="How many recent hours to scan for the frequency "
                        "ranking (default: 24).")
    p.add_argument("--sanma", action="store_true",
                   help="Fetch 3-player phoenix instead of 4-player.")
    p.add_argument("--min-quality", type=int, default=0,
                   help="Drop games with quality (sum of player frequencies) "
                        "below this threshold. Default: 0 (keep all).")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "replays"),
                   help="Output directory (default: demo/replays).")
    p.add_argument("--dry-run", action="store_true",
                   help="List the top-ranked games without downloading XML.")
    p.add_argument("--show-top", type=int, default=15,
                   help="Print this many top-ranked games (default: 15).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = PREFIX_3P if args.sanma else PREFIX_4P
    label = "sanma" if args.sanma else "4p"
    print(f"[demo] target: {label} phoenix, top {args.count} of last {args.scan_hours}h")

    games = scan_window(prefix, args.scan_hours)
    if not games:
        print("[demo] no games found — try increasing --scan-hours.")
        return 1

    ranked = rank_games(games)
    if args.min_quality > 0:
        ranked = [r for r in ranked if r[1] >= args.min_quality]
    print(f"[demo] ranked {len(ranked)} games; "
          f"top quality score = {ranked[0][1] if ranked else 0}")

    # Show the top of the leaderboard so you can sanity-check who's playing.
    print(f"[demo] showing top {min(args.show_top, len(ranked))}:")
    for game, qual, freqs in ranked[: args.show_top]:
        players = "  ".join(
            f"{name}(×{f})" for name, f in zip(game.players, freqs)
        )
        print(f"  q={qual:3d}  {game.game_id[:8]}  {players}")

    if args.dry_run:
        print("[demo] --dry-run set; not downloading XML.")
        return 0

    print()
    saved = 0
    for game, qual, freqs in ranked[: args.count]:
        target = out_dir / f"q{qual:03d}_{game.game_id}.xml"
        if target.exists() and target.stat().st_size > 0:
            print(f"[demo]   {target.name} already present, skipping")
            continue
        try:
            time.sleep(REQUEST_DELAY_S)
            xml = fetch_replay(game.game_id)
        except urllib.error.HTTPError as e:
            print(f"[demo]   {game.game_id}: HTTP {e.code} {e.reason}")
            continue
        except Exception as e:
            print(f"[demo]   {game.game_id}: {e!r}")
            continue
        target.write_bytes(xml)
        # Side-car JSON with metadata.
        meta_path = target.with_suffix(".json")
        meta_path.write_text(json.dumps({
            "game_id": game.game_id,
            "hour_stamp": game.hour_stamp,
            "format": label,
            "quality_score": qual,
            "players": [
                {"name": name, "final_score": score, "frequency_in_window": f}
                for name, score, f in zip(game.players, game.scores, freqs)
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[demo]   saved {target.name}  ({len(xml):,} bytes, q={qual})")
        saved += 1

    print(f"\n[demo] done — {saved} replay(s) saved to {out_dir}")
    if saved:
        print(
            "[demo] Reminder: tenhou.net's terms prohibit redistributing\n"
            "       these replays. They are gitignored by default."
        )
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
