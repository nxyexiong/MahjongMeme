# MahjongMeme

A [Copilot skill](https://docs.github.com/en/copilot) that teaches an agent to
inspect, navigate, and play [Mahjong Soul](https://mahjongsoul.game.yo-star.com/)
through the Playwright MCP browser tools.

No Python, no server, no Chrome extension — everything runs inside the live
page via `playwright-browser_evaluate` and `playwright-browser_run_code_unsafe`.

## What's in `skills/mahjong-soul/`

```
skills/mahjong-soul/
├── SKILL.md                       agent entry point — when/how to invoke
├── README.md                      (this file)
├── docs/
│   ├── state-model.md             globals, computeState, network hook, coords
│   ├── action-vocabulary.md       verified button names, server event names
│   └── troubleshooting.md         recovery for common failure modes
└── scripts/
    ├── init.js                    installs window.__mj primitives (run first)
    ├── hook_events.js             network log + decodes ActionPrototype
    ├── state.js                   installs window.__mj.computeState (sole observer)
    ├── inspect.js                 reference template for the one agent tool
    ├── login_wait.js              polls GameMgr.Inst.logined after human logs in
    └── events_tail.js             optional raw stream from the event buffer
```

## The one-tool loop

Everything during a session runs as `inspect → think → inspect → …`:

```
state = inspect()                     # observe only
while state.scene != 'match_end':
    action = decide(state)            # YOU think
    state = inspect(action=action)    # act + wait until next decision
```

`inspect` is not a real Playwright tool — it's an inline `async (page) => {…}`
script (template in `scripts/inspect.js`) that the agent passes directly to
`playwright-browser_run_code_unsafe`. Each call:

1. Optionally executes one action (discard / click / set_room_setting).
2. Polls `window.__mj.computeState()` inside the page until the game needs the
   agent's input (`needs_my_action === true`) or the match ends.
3. Returns the full observable state.

`state.js` is the **sole observer**. Every scene/modal/action the agent should
ever see is enumerated under `state.actionable.options[]` and
`state.meta_actions[]`. If the agent finds itself reaching for
`playwright-browser_take_screenshot` or hand-rolling a `page.evaluate` to find
a button, that's a `state.js` bug — fix `state.js`, don't probe from the call
site.

## Three things to know

1. **Match decisions are turn-based.** When `state.needs_my_action` is true in
   the match scene, return immediately. `state.match` carries the entire
   decision context — hand, melds per seat, discards per seat, dora,
   `left_tile_count`, riichi flags, `last_discard`.

2. **In-match actions bypass the DOM.** Discards go through the match
   controller directly: `me.setChoosePai(tile, isDrawn); me.DoDiscardTile()`.
   Calls and lobby/menu buttons use Playwright's native `page.mouse` because
   synthesized `PointerEvent`s skip Laya's 3D raycaster.

3. **Bootstrap after every page load.** `window.__mj` and the network hook
   die on reload. Re-run `init.js` → `hook_events.js` → `state.js`, then
   `inspect.js`.

## Verified live

Tested end-to-end May 2026 against client `0.11.251.w` (English):

- Cold-open → human login → main lobby → friendly landing → create room dialog
  (all 38 toggles across 13 groups settable programmatically via
  `UI_Create_Room.Inst.allLines[i].tabGroup.selectedIndex`).
- Room lobby → fill empty seats with AI via `seat.btn_add_robot` → start match.
- In-match play with chi/pon/kan call windows, riichi, discards, end-of-round
  reward/confirm flow, leave-match confirm dialog → back to main lobby.

## Design notes

- Engine = Laya. Design surface 1920 × 1080, rendered into
  `<canvas id="layaCanvas">`.
- All state reads come from five globals: `GameMgr.Inst`, `Laya.stage`,
  `game.MJNetMgr.Inst.netMJ`, `uiscript.*` (`UI_Create_Room`, `UI_WaitingRoom`,
  …), and `net.ProtobufManager` (for decoding wire bytes).
- **Login is the human's job.** The skill prompts via `ask_user` and waits
  for `GameMgr.Inst.logined === true` (see `login_wait.js`).
- The match controller `O = MJNetMgr.Inst.netMJ.notifyHander.handlers
  ['.lq.ActionPrototype']['0'].caller` exposes `mainrole.hand`,
  `players[].container_qipai/container_ming`, `dora`, `left_tile_count`,
  `lastqipai`. `state.js` caches it at `window.__mj.match`.

## Not in scope

- No automated Yostar account creation, login, or 2FA handling.
- No raw WebSocket sniffing — events come from the JS layer where the
  protobufs are already structured objects.
- No anti-detection. The skill assists a human account holder; running it
  unattended as an autoplay bot violates the Mahjong Soul ToS.
- No strategy engine. The skill surfaces state and executes actions; the
  agent decides what to do.
