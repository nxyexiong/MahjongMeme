"""Pluggable advisor registry for the observer.

Each advisor takes the observer's state dict and returns an ``Advice``
describing (a) what action it recommends and (b) a short human-readable
summary. The observer displays a side-by-side panel of all available
advisors' opinions on every actionable state.

Adding a new advisor: subclass ``Advisor``, implement ``advise(state)``,
and append an instance to ``DEFAULT_ADVISORS``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class Advice:
    """One advisor's opinion on a single state.

    Attributes
    ----------
    name
        Short label rendered in [brackets] (e.g. ``trainer``, ``myai``).
    action
        The recommended action in observer choice-dict shape, e.g.
        ``{"action": "discard", "tile": "3z"}`` or ``{"action": "skip"}``.
        Use ``None`` when the advisor has no opinion (e.g. observer-only
        states).
    summary
        Short one-line text shown after the action. May include
        confidence, shanten, ukeire, top-k, etc.
    extras
        Free-form structured data the consumer may render or compare on.
    """

    name: str
    action: Optional[dict] = None
    summary: str = ""
    extras: dict = field(default_factory=dict)


class Advisor:
    """Base class. Subclasses override ``name`` and ``advise``."""

    name: str = "advisor"

    def advise(self, state: dict) -> Optional[Advice]:
        """Return an ``Advice`` or ``None`` if this advisor has no opinion."""
        raise NotImplementedError


def actions_equivalent(a: Optional[dict], b: Optional[dict]) -> bool:
    """True iff two action dicts represent the same decision.

    Tolerant comparison: ignores red-five marks on discard tiles and
    optional fields like ``slot``. Two ``None`` or two ``skip`` actions
    compare equal.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    aa = a.get("action")
    bb = b.get("action")
    if aa != bb:
        return False
    if aa == "discard":
        ta = (a.get("tile") or "")
        tb = (b.get("tile") or "")
        ta = ta[:-1] if ta.endswith("*") else ta
        tb = tb[:-1] if tb.endswith("*") else tb
        return ta == tb
    if aa in ("chi", "pon", "kan"):
        sub_a = (a.get("extra") or {}).get("subtype")
        sub_b = (b.get("extra") or {}).get("subtype")
        if sub_a is None and sub_b is None:
            return True
        return sub_a == sub_b
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def build_default_advisors(
    *,
    enabled: Iterable[str] | None = None,
    myai_checkpoint: str | None = None,
) -> list[Advisor]:
    """Build the default advisor list.

    Parameters
    ----------
    enabled
        Optional iterable of advisor names to include (e.g. ``["trainer",
        "myai"]``). Default: all available advisors that import cleanly.
    myai_checkpoint
        Path to the MyAI checkpoint (.pt). Defaults to env var
        ``MAHJONG_MEME_MYAI_CHECKPOINT`` or ``artifacts/myai/best.pt``.
    """
    want = set(enabled) if enabled else None
    out: list[Advisor] = []

    if want is None or "trainer" in want:
        from .trainer_advisor import TrainerAdvisor
        out.append(TrainerAdvisor())

    if want is None or "myai" in want:
        ckpt = (
            myai_checkpoint
            or os.environ.get("MAHJONG_MEME_MYAI_CHECKPOINT")
            or "artifacts/myai/best.pt"
        )
        try:
            from .myai_advisor import MyAIAdvisor
            adv = MyAIAdvisor(checkpoint=ckpt)
            if adv.is_available:
                out.append(adv)
            elif want is not None and "myai" in want:
                print(f"[mj.advisors] myai unavailable: {adv._load_error}")
        except Exception as e:
            if want is not None and "myai" in want:
                print(f"[mj.advisors] myai unavailable: {e!r}")

    if want is not None and "mortal" in want:
        # Mortal integration is deliberately stubbed: see AI_PLAN.md
        # Part B for the licensing + weights blockers.
        print("[mj.advisors] mortal unavailable: see AI_PLAN.md Part B "
              "for blockers (AGPL license + no public weights)")

    return out


def parse_advisor_list(s: str | None) -> list[str] | None:
    """Parse a comma-separated list from CLI or env. Returns None when
    ``s`` is empty (== use defaults)."""
    if not s:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]
