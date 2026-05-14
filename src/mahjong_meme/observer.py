"""CDP attach, script injection, and live state polling loop."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from importlib import resources
from typing import Any

from playwright.sync_api import (
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)


GAME_URL = "https://mahjongsoul.game.yo-star.com/"

# Scenes that we recognize as "in a match" — once we see one, snapshots
# print on every flip of needs_my_action.
MATCH_SCENES = {"match", "match_end"}


# ---------------------------------------------------------------------------
# Script loading
# ---------------------------------------------------------------------------

def load_script(name: str) -> str:
    """Read a bundled JS script from mahjong_meme/scripts/."""
    return resources.files("mahjong_meme.scripts").joinpath(name).read_text(
        encoding="utf-8"
    )


# init.js and hook_events.js are arrow expressions; we wrap them to be
# directly evaluatable inside page.evaluate(). state.js is already an
# `async (page) => { ... }` that expects a Playwright `page`, but inside the
# browser we don't have `page` — so we adapt it to evaluate inline.

INIT_JS = load_script("init.js")           # `() => { ... }` — call with no args
HOOK_JS = load_script("hook_events.js")    # `(opts) => { ... }` — call with {}
STATE_JS = load_script("state.js")         # `async (page) => { ... }` — adapted below


def _state_install_in_page_js() -> str:
    """Build a JS expression that installs window.__mj.computeState INSIDE
    the page (no Playwright `page` available). state.js is an outer wrapper
    that calls `page.evaluate(() => { ... installation ... })`; we want
    just the inner installation body. Strip the wrapper.
    """
    src = STATE_JS
    # state.js shape:
    #   (async (page) => {
    #     const installed = await page.evaluate(() => {
    #       <BODY — the bit we want>
    #     });
    #     return installed;
    #   })
    # We want to wrap <BODY> as `() => { <BODY> }` so the browser can eval it.
    marker_open = "await page.evaluate(() => {"
    marker_close = "});\n  return installed;"
    i = src.find(marker_open)
    j = src.rfind(marker_close)
    if i < 0 or j < 0:
        raise RuntimeError(
            "state.js shape changed; observer can no longer extract the "
            "installation body. Update _state_install_in_page_js()."
        )
    body = src[i + len(marker_open):j]
    return "() => {\n" + body + "\n}"


STATE_INSTALL_JS = _state_install_in_page_js()


# ---------------------------------------------------------------------------
# CDP attach
# ---------------------------------------------------------------------------

def wait_for_cdp(cdp_url: str, timeout_s: float = 30.0) -> None:
    """Block until the CDP endpoint answers /json/version, or raise."""
    t0 = time.monotonic()
    last_err: Exception | None = None
    while time.monotonic() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(cdp_url + "/json/version", timeout=2) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            last_err = e
        time.sleep(0.4)
    raise RuntimeError(
        f"CDP endpoint at {cdp_url} did not become ready within "
        f"{timeout_s:.0f}s. Last error: {last_err!r}"
    )


def attach_to_game_page(playwright: Playwright, cdp_url: str) -> Page:
    """Connect via CDP and return the page that is on (or will be navigated
    to) the Mahjong Soul URL.
    """
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        raise RuntimeError("Browser exposed no contexts over CDP.")
    ctx = browser.contexts[0]
    # The browser was launched with the game URL as the first arg, so the
    # first page is usually already on the right origin. But it may still be
    # blank during launch — find or create.
    page: Page
    if ctx.pages:
        page = ctx.pages[0]
    else:
        page = ctx.new_page()
    current = page.url or ""
    if not current.startswith(GAME_URL):
        page.goto(GAME_URL, wait_until="domcontentloaded")
    return page


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

def wait_for_laya(page: Page, timeout_s: float = 90.0) -> None:
    """Block until Laya.stage is reachable inside the page."""
    page.wait_for_function(
        "window.Laya && Laya.stage && window.GameMgr && GameMgr.Inst",
        timeout=int(timeout_s * 1000),
    )


def inject_observer(page: Page) -> dict[str, Any]:
    """(Re-)install init, hook_events, and state. Idempotent."""
    init_res = page.evaluate(INIT_JS)
    hook_res = page.evaluate(f"() => ({HOOK_JS})({{}})")
    # state.js wraps installation in page.evaluate; here we run the inner
    # body directly inside the page.
    state_res = page.evaluate(STATE_INSTALL_JS)
    return {"init": init_res, "hook": hook_res, "state": state_res}


def wait_for_login(page: Page, *, log=print) -> None:
    """Poll until GameMgr.Inst.logined is true."""
    logged_in = page.evaluate(
        "() => !!(window.GameMgr && GameMgr.Inst && GameMgr.Inst.logined)"
    )
    if logged_in:
        return
    log("[mj] not logged in — please log in via the browser window. Waiting…")
    # No hard timeout — the user is the one logging in.
    while True:
        try:
            ok = page.evaluate(
                "() => !!(window.GameMgr && GameMgr.Inst && GameMgr.Inst.logined)"
            )
        except Exception:
            ok = False
        if ok:
            log("[mj] logged in.")
            return
        time.sleep(1.0)


def compute_state(page: Page) -> dict[str, Any] | None:
    """Call window.__mj.computeState() and return its result, or None if the
    observer isn't installed yet (e.g. just after a page navigation)."""
    return page.evaluate(
        "() => (window.__mj && window.__mj.computeState) "
        "? window.__mj.computeState() : null"
    )


def fetch_events_since(page: Page, seq: int) -> list[dict[str, Any]]:
    """Pull new events from the ring buffer since the given seq."""
    return page.evaluate(
        "(seq) => (window.__mj && window.__mj.events) "
        "? window.__mj.events.since(seq).map(e => ({"
        "  seq: e.seq, t: e.t, dir: e.dir, name: e.name,"
        "  summary: e.summary"
        "})) : []",
        seq,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _short(value: Any, limit: int = 400) -> str:
    s = json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def print_state(state: dict[str, Any], *, log=print) -> None:
    """Pretty-print a full state snapshot."""
    log("=" * 72)
    log(f"[mj] STATE  scene={state.get('scene')}  "
        f"needs_my_action={state.get('needs_my_action')}  "
        f"event_seq={state.get('event_seq')}")
    log("-" * 72)
    log(json.dumps(state, ensure_ascii=False, indent=2, default=str))
    log("=" * 72)


def print_events(events: list[dict[str, Any]], *, log=print) -> None:
    for ev in events:
        log(f"[mj.evt] seq={ev['seq']} {ev['dir']:11} {ev['name']}  "
            f"{_short(ev.get('summary'), 220)}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(
    cdp_url: str,
    *,
    poll_interval_s: float = 1.0,
    verbose_events: bool = False,
    log=print,
) -> None:
    """Attach to the browser, install the observer, then loop forever.

    Prints a full state snapshot whenever needs_my_action transitions from
    False to True, or when scene changes. Optionally prints every new event.
    """
    wait_for_cdp(cdp_url)

    with sync_playwright() as pw:
        page = attach_to_game_page(pw, cdp_url)
        log(f"[mj] attached to page: {page.url}")
        log("[mj] waiting for Laya to boot …")
        wait_for_laya(page)
        log("[mj] Laya ready; injecting observer scripts")
        inject_observer(page)

        wait_for_login(page, log=log)

        last_state: dict[str, Any] | None = None
        last_event_seq = 0
        last_match_seen = False
        match_announced = False

        log("[mj] entering poll loop — waiting for a match to start…")
        while True:
            try:
                state = compute_state(page)
            except PWTimeoutError:
                state = None
            except Exception as e:
                log(f"[mj] computeState failed: {e!r}")
                # If __mj got wiped (rare; navigation race), reinstall.
                try:
                    inject_observer(page)
                except Exception:
                    pass
                state = None

            if state is None or not state.get("ok"):
                # Observer not (yet) installed — reinstall and retry.
                try:
                    inject_observer(page)
                except Exception:
                    pass
                time.sleep(poll_interval_s)
                continue

            scene = state.get("scene")
            in_match = scene in MATCH_SCENES

            # Announce the moment we first see a match.
            if in_match and not match_announced:
                log(f"[mj] match detected (scene={scene})")
                match_announced = True
                print_state(state, log=log)
            elif not in_match and match_announced and not last_match_seen:
                # We left the match — reset the announcement gate so the
                # next match also triggers.
                match_announced = False

            # Scene transition: always announce.
            scene_changed = (
                last_state is None or last_state.get("scene") != scene
            )

            # needs_my_action rising edge: print full state.
            needs = bool(state.get("needs_my_action"))
            prev_needs = bool(last_state and last_state.get("needs_my_action"))
            if needs and not prev_needs:
                print_state(state, log=log)
            elif scene_changed and last_state is not None:
                log(f"[mj] scene → {scene}")

            # Stream events
            new_seq = int(state.get("event_seq") or 0)
            if verbose_events and new_seq > last_event_seq:
                try:
                    events = fetch_events_since(page, last_event_seq)
                    if events:
                        print_events(events, log=log)
                except Exception:
                    pass
            last_event_seq = new_seq

            last_state = state
            last_match_seen = in_match
            time.sleep(poll_interval_s)
