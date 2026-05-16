"""From-scratch mahjong decision AI.

Multi-head CNN-ResNet trained via behavioral cloning on tenhou replays.
See ``AI_PLAN.md`` for the design rationale.
"""

NUM_TILES_34 = 34          # public action vocabulary size for discard head.
HEAD_NAMES = ("discard", "call", "kan", "riichi", "win")
HEAD_SIZES = (34, 5, 2, 2, 2)
