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
            out = self.predictor.recommend(state, topk=3)
        except Exception as e:
            return Advice(name=self.name, summary=f"inference failed: {e!r}")
        if out.get("head") is None:
            return None

        topk = out.get("topk") or []
        top_strs = [f"{_short_action(act)}@{p:.2f}" for act, p in topk]
        summary = (
            f"head={out['head']}  p={out['prob']:.2f}  "
            f"top={', '.join(top_strs)}"
        )
        return Advice(
            name=self.name,
            action=out.get("action"),
            summary=summary,
            extras={"prob": out.get("prob"), "topk": topk},
        )


def _short_action(a: dict) -> str:
    act = a.get("action")
    if act == "discard":
        return a.get("tile") or "?"
    if act == "chi":
        return ((a.get("extra") or {}).get("position") or "chi")
    if act in ("pon", "kan", "hu", "zimo", "lizhi", "kita"):
        return act
    if act == "skip":
        return "skip"
    return act or "?"
