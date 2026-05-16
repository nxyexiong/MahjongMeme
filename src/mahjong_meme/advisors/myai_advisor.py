"""MyAIAdvisor — wraps the MyAI from-scratch checkpoint."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import Advice, Advisor


class MyAIAdvisor(Advisor):
    name = "myai"

    def __init__(self, checkpoint: str | Path):
        self.checkpoint = Path(checkpoint)
        self.predictor = None
        self.is_available = False
        self._load_error: str | None = None

        if not self.checkpoint.exists():
            self._load_error = f"checkpoint not found: {self.checkpoint}"
            return
        try:
            from mahjong_meme.myai.predict import MyAIPredictor
        except Exception as e:
            self._load_error = f"torch/myai unavailable: {e!r}"
            return
        try:
            self.predictor = MyAIPredictor(self.checkpoint)
        except Exception as e:
            self._load_error = f"failed to load checkpoint: {e!r}"
            return
        self.is_available = True

    def advise(self, state: dict) -> Optional[Advice]:
        if not self.is_available or self.predictor is None:
            return None
        try:
            out = self.predictor.recommend(state, topk=5)
        except Exception as e:
            return Advice(name=self.name, summary=f"inference failed: {e!r}")
        if out.get("head") is None:
            return None

        topk = out.get("topk") or []
        # Render each top-K candidate on its own line for readability.
        lines = [f"top={len(topk)} moves:"]
        for i, (act, p) in enumerate(topk, 1):
            marker = "*" if i == 1 else " "
            lines.append(f"  {marker} {_short_action(act):<14}  p={p:.3f}")
        summary = "\n".join(lines)
        return Advice(
            name=self.name,
            action=out.get("action"),
            summary=summary,
            extras={"prob": out.get("prob"), "topk": topk},
        )


def _short_action(a: dict) -> str:
    act = a.get("action")
    if act == "discard":
        return f"discard {a.get('tile') or '?'}"
    if act == "chi":
        return f"chi:{((a.get('extra') or {}).get('position') or '?')}"
    if act == "pon":
        return "pon"
    if act == "kan":
        extra = a.get("extra") or {}
        sub = extra.get("subtype")
        tile = a.get("tile") or extra.get("tile")
        if sub and tile:
            return f"kan:{sub} on {tile}"
        if sub:
            return f"kan:{sub}"
        if tile:
            return f"kan on {tile}"
        return "kan"
    if act == "lizhi":
        tile = a.get("tile") or (a.get("extra") or {}).get("declare_on")
        return f"riichi on {tile}" if tile else "riichi"
    if act == "hu":
        return "ron"
    if act == "zimo":
        return "tsumo"
    if act == "kita":
        return "kita"
    if act == "skip":
        return "skip"
    return act or "?"
