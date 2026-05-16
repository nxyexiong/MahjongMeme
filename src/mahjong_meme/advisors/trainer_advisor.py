"""TrainerAdvisor — wraps the shanten/ukeire/safety engine."""
from __future__ import annotations

from typing import Optional

from . import Advice, Advisor


class TrainerAdvisor(Advisor):
    name = "trainer"

    def advise(self, state: dict) -> Optional[Advice]:
        actionable = state.get("actionable") or {}
        if actionable.get("kind") != "discard":
            return None
        match = state.get("match") or {}
        hand = [t for t in (match.get("hand") or []) if t]
        if not hand:
            return None

        try:
            from mahjong_meme.trainer import OpponentInfo, evaluate_turn
        except Exception as e:
            return Advice(name=self.name, summary=f"unavailable: {e!r}")

        melds = match.get("melds") or []
        discards = match.get("discards") or []
        dora_indicators = [d for d in (match.get("dora_indicators") or []) if d]
        liqi = match.get("liqi") or []
        my_seat = match.get("my_seat")

        my_melds_raw = (
            melds[my_seat]
            if my_seat is not None and 0 <= my_seat < len(melds)
            else []
        ) or []
        my_melds: list[list[str]] = [
            [t for t in (m.get("tiles") or []) if t] for m in my_melds_raw
        ]
        my_melds = [m for m in my_melds if m]

        flat_visible: list[str] = []
        for seat_idx, seat_melds in enumerate(melds):
            if seat_idx == my_seat:
                continue
            for meld in seat_melds or []:
                flat_visible.extend(t for t in (meld.get("tiles") or []) if t)
        for seat_discards in discards:
            flat_visible.extend(t for t in (seat_discards or []) if t)

        opponents = []
        n_seats = max(len(discards), len(liqi), 4)
        for seat in range(n_seats):
            if seat == my_seat:
                continue
            raw = discards[seat] if seat < len(discards) else []
            sd = [t for t in (raw or []) if t]
            in_riichi = bool(liqi[seat]) if seat < len(liqi) else False
            riichi_tile = sd[-1] if (in_riichi and sd) else None
            tiles_after = list(sd) if in_riichi else []
            opponents.append(OpponentInfo(
                discards=sd, riichi_tile=riichi_tile,
                tiles_after_riichi=tiles_after,
            ))

        try:
            ev = evaluate_turn(
                hand=hand, visible_tiles=flat_visible, my_melds=my_melds,
                dora_indicators=dora_indicators, opponents=opponents,
            )
        except Exception as e:
            return Advice(name=self.name, summary=f"evaluation failed: {e!r}")

        rec = ev.recommended_discard
        action = {"action": "discard", "tile": rec} if rec else None
        summary_lines = [
            f"shanten={ev.shanten} (std={ev.shanten_standard} "
            f"chii={ev.shanten_chiitoi} kokushi={ev.shanten_kokushi})  "
            f"dora={ev.dora_tiles}"
        ]
        if rec:
            summary_lines.append(
                f"recommended discard: {rec}  "
                f"-> {ev.current_ukeire} ukeire after"
            )
        if ev.discards:
            summary_lines.append("top discards:")
            for d in ev.discards[:5]:
                marker = "*" if d.is_recommended else " "
                safety = (
                    "  safety=" + str(d.safety_per_opponent)
                    if d.safety_per_opponent else ""
                )
                summary_lines.append(
                    f"  {marker} {d.tile:4} ukeire={d.ukeire_count:3}  "
                    f"tiles={d.ukeire_tiles}{safety}"
                )

        return Advice(
            name=self.name,
            action=action,
            summary="\n".join(summary_lines),
            extras={
                "shanten": ev.shanten,
                "current_ukeire": ev.current_ukeire,
                "dora": ev.dora_tiles,
            },
        )
