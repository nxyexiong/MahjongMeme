"""mahjong-meme CLI entry point."""
from __future__ import annotations

import argparse
import sys

from mahjong_meme.browser import (
    DEFAULT_WINDOW_SIZE,
    default_profile_dir,
    launch_browser,
)
from mahjong_meme.observer import GAME_URL, run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mahjong-meme",
        description=(
            "Launch a Chromium-family browser with a persistent profile + "
            "remote debug port, attach via CDP, and stream Mahjong Soul "
            "match state."
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
        "--profile-dir",
        default=None,
        help="Path to the browser user-data dir to use. Defaults to a "
        "persistent per-user directory (so cookies/login survive between "
        "runs). Use --temp-profile to override with a fresh throwaway.",
    )
    p.add_argument(
        "--temp-profile",
        action="store_true",
        help="Use a fresh temp profile dir for this run (does NOT persist).",
    )
    p.add_argument(
        "--window-size",
        default=DEFAULT_WINDOW_SIZE,
        help=f"Initial window size 'W,H'. Default: {DEFAULT_WINDOW_SIZE}. "
        "Pass an empty string to leave it unset.",
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
        "--advisors",
        default=None,
        help="Comma-separated list of advisors to enable (trainer,myai,mortal). "
             "Default: trainer + myai (when checkpoint is available). "
             "Note: mortal is currently a no-op stub (see AI_PLAN.md Part B).",
    )
    p.add_argument(
        "--myai-checkpoint",
        default=None,
        help="Path to a MyAI .pt checkpoint. Overrides "
             "MAHJONG_MEME_MYAI_CHECKPOINT env var. "
             "Default: artifacts/myai/best.pt",
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
        "repeated. E.g. --extra-arg=--disable-gpu",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.no_launch:
        cdp_url = f"http://127.0.0.1:{args.port}"
        print(f"[mj] attaching to existing browser at {cdp_url}")
    else:
        if args.temp_profile:
            profile_arg: object = "TEMP"
        elif args.profile_dir:
            profile_arg = args.profile_dir
        else:
            profile_arg = default_profile_dir(args.browser)
        window = args.window_size if args.window_size else None
        b = launch_browser(
            args.browser,
            port=args.port,
            initial_url=args.url,
            extra_args=args.extra_arg,
            user_data_dir=profile_arg,
            window_size=window,
        )
        cdp_url = b.cdp_url
        print(f"[mj] launched {b.executable}")
        print(f"[mj]   pid={b.process.pid}  port={b.port}")
        kind = "temp" if args.temp_profile else "persistent"
        print(f"[mj]   profile ({kind}) = {b.user_data_dir}")
        if window:
            print(f"[mj]   window-size = {window}")
        print(f"[mj]   cdp = {cdp_url}")

    try:
        from mahjong_meme.advisors import build_default_advisors, parse_advisor_list
        advisors = build_default_advisors(
            enabled=parse_advisor_list(args.advisors),
            myai_checkpoint=args.myai_checkpoint,
        )
        run(
            cdp_url,
            poll_interval_s=args.poll_interval,
            verbose_events=args.verbose_events,
            advisors=advisors,
        )
    except KeyboardInterrupt:
        print("\n[mj] interrupted by user; exiting (browser left running)")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
