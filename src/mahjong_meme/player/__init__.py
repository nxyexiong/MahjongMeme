"""Auto-play module: executes the MyAI advisor's chosen action via CDP.

Wires into the observer's poll loop: when ``needs_my_action`` is True
and the state is actionable, we ask MyAI for its top-K candidates and
try them in order until one succeeds.

No safety rails (per user direction) — runs continuously, does not
distinguish ranked vs friend rooms.
"""

DELAY_INSTANT = "instant"
DELAY_RANDOM = "random"
DELAY_MODES = (DELAY_INSTANT, DELAY_RANDOM)
