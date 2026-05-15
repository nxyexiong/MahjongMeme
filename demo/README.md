# Demos

High-quality replay fixtures from [tenhou.net](https://tenhou.net) phoenix
room (鳳凰卓) — the top-tier table reserved for 8+ dan players. Use them
to develop and test the trainer engine against real high-level play.

## ⚠️ Licensing

Replay files (`replays/*.xml`) are **not** committed to this repo.
Tenhou's terms (see <https://tenhou.net/sc/raw/>) prohibit:

1. Using the logs for products that compete with tenhou.
2. Building services that redistribute tenhou logs to third parties.

This project complies by **fetching replays on demand to your local
machine** via the included downloader script, and `.gitignore` excludes
`replays/` from version control. Don't push the downloaded XML anywhere.

## Fetch some

From the repo root:

```powershell
# Default: scan last 24h, download top 8 4-player phoenix games by quality
.\src\.venv\Scripts\python.exe demo\download.py

# Wider scan window (catches more 天鳳位 / 10段 appearances)
.\src\.venv\Scripts\python.exe demo\download.py --scan-hours 48 --count 16

# 3-player phoenix
.\src\.venv\Scripts\python.exe demo\download.py --sanma

# See the leaderboard without downloading
.\src\.venv\Scripts\python.exe demo\download.py --dry-run --show-top 30

# Only games where the four players collectively appear ≥ N times in the window
.\src\.venv\Scripts\python.exe demo\download.py --min-quality 20
```

## How "high quality" is determined

Tenhou doesn't expose player rank inline in the phoenix listings, but it
does give us the player names per game. We exploit a strong signal:

> Top players play many phoenix-room games per day. A 天鳳位 (rank 11, the
> highest, ~12 players ever) plays dozens; a fresh 8-dan plays once.

The script:

1. Scans the last `--scan-hours` (default 24) of hourly phoenix listings.
2. Counts how many phoenix games each player appears in.
3. Scores each game by the **sum** of its four players' frequencies.
4. Sorts and downloads the highest-quality games.

So a game where all four players appeared in 8+ phoenix games today
ranks much higher than a game with one regular and three first-timers.

Each downloaded `*.xml` gets a sidecar `*.json` with `quality_score`,
the players' names + final point deltas + per-player frequency.

## What the files look like

Each replay is a Tenhou v2.3 `<mjloggm>` XML document. Top-level elements
include `<SHUFFLE>`, `<UN>` (player names), `<INIT>` (round start),
`<T...>`/`<U...>`/`<V...>`/`<W...>` (per-seat draws), and `<D...>`/`<E...>`
discard events. Parsers for this format are available in the
[MahjongRepository/mahjong](https://github.com/MahjongRepository/mahjong)
ecosystem; the simplest reference parser is in
[tenhou-log-utils](https://github.com/mthrok/tenhou-log-utils).

## Why phoenix room

Phoenix-room (`gm-00a9` for 4-player, `gm-00b9` for 3-player) games are
played exclusively by 8-dan and above. They have:

- Higher variance / better hand selection than ranked rooms.
- A reliable filter for skilled play (8-dan is reachable only after
  thousands of hands with above-average performance).
- Decades of public hourly archives going back to 2009.

If you want lower-tier games for variety, edit the prefix in
`download.py` (`gm-00a1` is the silver-room hanchan format, etc.).
