"""mahjong-meme CLI entry point."""
from __future__ import annotations

import argparse
import sys

from mahjong_meme.browser import launch_browser
from mahjong_meme.observer import GAME_URL, run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mahjong-meme",
        description=(
            "Launch a Chromium-family browser with a clean profile + remote "
            "debug port, attach via CDP, and stream Mahjong Soul match state."
        ),
    )
    p.add_argument(
        "--browser",
        "-b",
        default="chrome",
        help="Browser alias (chrome|edge|brave|chromium) or absolute path "
        "to an executable. Default: chrome.",
    )
    p.add_argument(
        "--port",
        "-p",
        type=int,
        default=9222,
        help="Remote debugging port to expose. Default: 9222.",
    )
    p.add_argument(
        "--url",
        default=GAME_URL,
        help=f"Initial URL. Default: {GAME_URL}",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="State polling interval in seconds. Default: 1.0.",
    )
    p.add_argument(
        "--verbose-events",
        action="store_true",
        help="Also print every new wire event as it streams in.",
    )
    p.add_argument(
        "--no-launch",
        action="store_true",
        help="Don't spawn a browser; attach to an already-running browser "
        "with --remote-debugging-port on --port.",
    )
    p.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        metavar="ARG",
        help="Extra command-line flag to pass to the browser. May be "
        "repeated. E.g. --extra-arg=--window-size=1600,900",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.no_launch:
        cdp_url = f"http://127.0.0.1:{args.port}"
        print(f"[mj] attaching to existing browser at {cdp_url}")
    else:
        b = launch_browser(
            args.browser,
            port=args.port,
            initial_url=args.url,
            extra_args=args.extra_arg,
        )
        cdp_url = b.cdp_url
        print(f"[mj] launched {b.executable}")
        print(f"[mj]   pid={b.process.pid}  port={b.port}")
        print(f"[mj]   profile={b.user_data_dir}  (temp; delete after use)")
        print(f"[mj]   cdp={cdp_url}")

    try:
        run(
            cdp_url,
            poll_interval_s=args.poll_interval,
            verbose_events=args.verbose_events,
        )
    except KeyboardInterrupt:
        print("\n[mj] interrupted by user; exiting (browser left running)")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
