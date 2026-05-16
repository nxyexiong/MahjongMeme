"""CDP-side execution of advisor-chosen actions.

ALL in-match decisions go through the controller's WebSocket sender
(``app.NetAgent.sendReq2MJ``), not through DOM clicks. Position-based
clicking is no longer used for any action.

Public surface
--------------

``Executor.execute(page, state, candidates) -> bool``

    Tries each candidate from ``candidates`` (a top-K list of dicts
    like ``[{action, prob, ...}, ...]``) in order until one executes
    successfully. Returns True on the first success, False if all
    candidates failed.
"""
from __future__ import annotations

import random
import time
from typing import Callable, Sequence

from .action_js import (
    CALL_JS, DISCARD_JS, KITA_JS, PASS_CALL_JS, PASS_OWN_JS, RIICHI_JS,
    TSUMO_JS,
)
from . import DELAY_INSTANT, DELAY_RANDOM


def _norm_tile(s: str | None) -> str | None:
    if not s:
        return None
    if len(s) == 2 and s[0] == "0" and s[1] in "mps":
        return "5" + s[1] + "*"
    return s


class Executor:
    """Stateful executor: tracks last-acted ``event_seq`` to avoid
    double-execution within a single decision point."""

    def __init__(self, *, log: Callable[[str], None] = print,
                 delay_mode: str = DELAY_INSTANT):
        self.log = log
        self.delay_mode = delay_mode
        self.last_acted_seq: int = -1

    # ---- public ------------------------------------------------------

    def execute(self, page, state: dict, candidates: Sequence[dict]) -> bool:
        event_seq = int(state.get("event_seq") or 0)
        if event_seq == self.last_acted_seq:
            return False  # Already acted on this state.

        self._sleep_before_action()
        for i, cand in enumerate(candidates):
            action = cand.get("action") if isinstance(cand, dict) else None
            if not action:
                continue
            label = self._fmt_action(action)
            prob = cand.get("prob") if isinstance(cand, dict) else None
            tag = f"#{i + 1}/{len(candidates)}"
            self.log(f"[mj.play] {tag} trying {label}"
                     + (f"  p={prob:.3f}" if isinstance(prob, float) else ""))
            ok, reason = self._dispatch(page, state, action)
            if ok:
                self.log(f"[mj.play] {tag} EXECUTED: {label}")
                self.last_acted_seq = event_seq
                return True
            self.log(f"[mj.play] {tag} failed ({reason}); falling back")
        self.log(f"[mj.play] all {len(candidates)} candidates failed; "
                 f"giving up on event_seq={event_seq}")
        return False

    # ---- internals ---------------------------------------------------

    def _sleep_before_action(self) -> None:
        if self.delay_mode == DELAY_RANDOM:
            secs = random.uniform(1.0, 5.0)
            self.log(f"[mj.play] delay-mode=random sleeping {secs:.2f}s")
            time.sleep(secs)

    def _dispatch(self, page, state: dict, action: dict) -> tuple[bool, str]:
        act = action.get("action")
        kind = (state.get("actionable") or {}).get("kind")

        if act == "discard":
            return self._call_js(page, DISCARD_JS,
                                  {"tile": _norm_tile(action.get("tile"))})
        if act == "lizhi":
            tile = action.get("tile") or (action.get("extra") or {}).get("declare_on")
            return self._call_js(page, RIICHI_JS,
                                  {"tile": _norm_tile(tile)})
        if act == "zimo":
            return self._call_js(page, TSUMO_JS, {})
        if act == "kita":
            return self._call_js(page, KITA_JS, {})

        if act == "chi":
            partners = (action.get("extra") or {}).get("partner_tiles") or []
            combos = (state.get("actionable") or {}).get("chi_combinations") or []
            return self._call_js(page, CALL_JS,
                                  {"type": "chi", "partner_tiles": partners,
                                   "combinations": list(combos)})
        if act == "pon":
            combos = (state.get("actionable") or {}).get("pon_combinations") or []
            return self._call_js(page, CALL_JS,
                                  {"type": "pon", "combinations": list(combos)})
        if act == "kan":
            extra = action.get("extra") or {}
            subtype = extra.get("subtype")
            if not subtype:
                # On own-turn (kind='discard'), the kan can only be ankan
                # (4) or chakan (6). The wire type 5 (minkan) silently
                # locks up the round on own-turn. On call_window the
                # only available kan is minkan.
                subtype = "kan_closed" if kind == "discard" else "kan_open"
            tile = action.get("tile") or extra.get("tile")
            combos = (state.get("actionable") or {}).get("kan_combinations") or []
            return self._call_js(page, CALL_JS,
                                  {"type": subtype, "tile": _norm_tile(tile),
                                   "combinations": list(combos)})
        if act == "hu":
            return self._call_js(page, CALL_JS, {"type": "ron"})

        if act == "skip":
            # On call_window: server-side cancel of the chi/pon/kan/ron offer.
            # On discard-kind state: there's no such thing as "skip"
            # (you owe a discard). Return failure so the executor falls
            # through to the next top-K candidate (which should be a
            # real discard).
            if kind == "call_window":
                return self._call_js(page, PASS_CALL_JS, None)
            return False, "skip_invalid_on_own_turn"

        return False, f"unknown_action:{act}"

    def _call_js(self, page, js: str, args) -> tuple[bool, str]:
        try:
            result = (page.evaluate(js, args) if args is not None
                      else page.evaluate(js))
        except Exception as e:
            return False, f"evaluate_raised:{e!r}"
        if isinstance(result, dict) and result.get("ok"):
            # Surface useful context (combination index for chi/kan, etc).
            extras = []
            for k in ("type", "index", "method", "combination", "tile", "isDrawn"):
                if k in result:
                    extras.append(f"{k}={result[k]}")
            if extras:
                self.log("[mj.play]   wire: " + ", ".join(extras))
            return True, "ok"
        reason = (result.get("reason") if isinstance(result, dict)
                  else f"non_dict:{type(result).__name__}")
        message = (result.get("message") if isinstance(result, dict) else None)
        return False, f"{reason}" + (f":{message}" if message else "")

    # ---- formatting --------------------------------------------------

    def _fmt_action(self, action: dict) -> str:
        a = action.get("action")
        if a == "discard":
            return f"discard {action.get('tile')}"
        if a == "chi":
            extra = action.get("extra") or {}
            pos = extra.get("position")
            partners = extra.get("partner_tiles") or []
            base = f"chi:{pos}" if pos else "chi"
            return f"{base} [{','.join(partners)}]" if partners else base
        if a == "pon":
            return "pon"
        if a == "kan":
            extra = action.get("extra") or {}
            sub = extra.get("subtype")
            tile = action.get("tile") or extra.get("tile")
            if sub and tile:
                return f"kan:{sub} {tile}"
            return f"kan:{sub}" if sub else (f"kan {tile}" if tile else "kan")
        if a == "lizhi":
            tile = action.get("tile") or (action.get("extra") or {}).get("declare_on")
            return f"riichi on {tile}" if tile else "riichi"
        if a == "hu":
            return "ron"
        if a == "zimo":
            return "tsumo"
        if a == "kita":
            return "kita"
        if a == "skip":
            return "skip"
        return a or "?"
