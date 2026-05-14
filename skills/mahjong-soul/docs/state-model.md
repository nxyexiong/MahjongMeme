# Game state model

Everything the skill reads flows through one function:
**`window.__mj.computeState()`** (installed by `scripts/state.js`).

`inspect.js` calls it once per poll inside its wait loop and returns the
result. The agent should never read scene-graph internals or `GameMgr.Inst`
directly — if a field is missing from the returned state, add it to
`state.js`.

## Globals read by `state.js`

| Source                                | Used for |
|---------------------------------------|----------|
| `window.GameMgr.Inst`                 | Account + top-level scene flags. |
| `window.Laya.stage`                   | The Laya scene graph (button + modal detection). |
| `window.game.MJNetMgr.Inst.netMJ`     | Indirect: the match controller is cached off this. |
| `window.uiscript.UI_Create_Room.Inst` | Authoritative source for Create Room toggles. |
| `window.uiscript.UI_WaitingRoom.Inst` | Authoritative source for room seats + room mode. |
| `window.net.ProtobufManager`          | Used by `hook_events.js` to decode action bodies. |

## `GameMgr.Inst` fields actually used

| Field                                              | Meaning |
|----------------------------------------------------|---------|
| `logined: boolean`                                 | True once a Yostar session is established. |
| `account_id: number`                               | Player ID. -1 before login. Used to mark `is_me` on seats. |
| `account_data: { nickname, … }`                    | Authoritative profile. `account_data.nickname` is the display name (`player_name` is often empty). |
| `ingame: boolean`                                  | True while inside a live match. |
| `_current_scene` / `_scene_lobby`                  | Identity comparison to detect the lobby scene. |

## Scene resolution

`state.js` returns one of:

| `state.scene`           | When |
|-------------------------|------|
| `'login'`               | `!GameMgr.Inst.logined`. |
| `'match'`               | `GameMgr.Inst.ingame` and no end-of-match overlay. |
| `'match_end'`           | A visible `gameend` container is on stage. |
| `'create_room_dialog'`  | A visible `container_create_room` is on stage. |
| `'friendly_landing'`    | A visible `page_friend` node is on stage (the Friendly Match landing). |
| `'room_lobby'`          | The waiting-room layout is up (host: `btn_start` at root; guest: `btn_suit`). |
| `'main_lobby'`          | `_current_scene === _scene_lobby` and no overlay above. |
| `'transition'`          | Anything else — short-lived loading/post-match screens. Poll again. |

## Modal detection

`state.modal` is computed independently of scene and may shadow the scene's
default actionable. Priority:

```
afk
> gameend
> create_room_dialog
> confirm_dialog
> pop_*
```

| Modal `kind`              | Recognition |
|---------------------------|-------------|
| `'afk'`                   | A visible text node reading `"I'm back"`. |
| `'gameend'`               | Visible `gameend` container. |
| `'create_room_dialog'`    | Visible `container_create_room`. |
| `'confirm_dialog'`        | A `btn_confirm` AND `btn_cancel` both as direct children of `root` (e.g. "Do you wish to leave this room?"). |
| `'pop'`                   | Any visible node whose name matches `/^pop_/`. |

## Match-time state

`state.match` is populated when `scene === 'match'` or `'match_end'`. It is
read entirely from the match controller `O` (cached at `window.__mj.match`):

```js
O = game.MJNetMgr.Inst.netMJ.notifyHander.handlers['.lq.ActionPrototype']['0'].caller;
```

Yes — the player's own hand IS reachable from JS at `O.mainrole.hand` (each
entry has `.val = { type, index, dora }`). This is what `state.match.hand`
returns. **Old docs said "you can't read your hand without the network log."
That was wrong** — the match controller exposes it directly.

| `state.match` field        | Source on `O` |
|----------------------------|---------------|
| `my_seat`                  | `O.seat` |
| `scores`                   | `O.players[i].score` |
| `chang`, `ju`, `ben`       | `O.index_change`, `O.index_ju`, `O.index_ben` |
| `left_tile_count`          | `O.left_tile_count` |
| `dora_indicators`          | `O.dora[]` |
| `hand`                     | `O.mainrole.hand[].val` → tile string |
| `melds[seat]`              | `O.players[i].container_ming.mings[].{type, pais}` |
| `discards[seat]`           | `O.players[i].container_qipai.pais[]` |
| `liqi[seat]`               | `O.players[i].lichi` |
| `last_discard`             | `O.lastqipai`, `O.lastpai_seat` |
| `can_discard`              | `O.mainrole.can_discard` |

### Tile encoding

`tile.val = { type: 0..3, index: 1..9, dora: bool }` →

| Suit | Type | String |
|------|------|--------|
| Man  | 0    | `Nm`   |
| Pin  | 1    | `Np`   |
| Sou  | 2    | `Ns`   |
| Honor| 3    | `Nz` (1z=E, 2z=S, 3z=W, 4z=N, 5z=白, 6z=發, 7z=中) |

Red five is `5m*` / `5p*` / `5s*` (`dora === true`).

### Discard mechanism (the only correct path)

```js
// Inside page.evaluate
const me = window.__mj.match.mainrole;
me.setChoosePai(pick, pick === me.last_tile);
me.DoDiscardTile();
```

`pick === me.last_tile` decides `moqie` (tsumogiri). Direct API call, no DOM
race. **Specify the tile by string, not by hand slot**, because the hand
re-orders after a pon/chi.

### Call buttons (chi/pon/kan/lizhi/zimo/hu)

These ARE DOM-level: visible Laya buttons under `container_btn` /
`container_btns`. `state.js` enumerates them under
`actionable.kind === 'call_window'` and pre-classifies them by intent:

| Intent | Button names |
|--------|--------------|
| chi    | `btn_chi`, `btn_chii` |
| pon    | `btn_peng`, `btn_pon` |
| kan    | `btn_gang`, `btn_kan`, `btn_minkan`, `btn_ankan` |
| lizhi  | `btn_lizhi`, `btn_liqi`, `btn_riichi` |
| zimo   | `btn_zimo`, `btn_tsumo` |
| hu     | `btn_hu`, `btn_ron` |
| kita   | `btn_babei`, `btn_kita` (sanma) |
| pass   | `btn_quxiao`, `btn_pass`, `btn_skip`, `btn_cancel` |

The agent clicks them via Playwright's native `page.mouse` (synthesized
events fail silently on the 3D scene).

## Room state (`state.room`, `state.scene === 'room_lobby'`)

Read from `uiscript.UI_WaitingRoom.Inst`:

| Field                       | Source |
|-----------------------------|--------|
| `room_id`                   | `wr.room_id` |
| `owner_id`                  | `wr.owner_id` |
| `is_host`                   | `owner_id === my account_id` |
| `max_player_count`          | `wr.max_player_count` (3 or 4) |
| `seats[i]`                  | `wr.players[i]` → `{seat, account_id, nickname, is_me, is_empty, is_ai, ready}` |
| `mode`                      | `wr.room_mode` (raw object — fields like `mode`, `time_fixed`, `time_add`, `dora_count`, `ai_level`) |

**Add-AI button**: each seat's add-AI button lives on the seat object as a
NAMED field — `wr.playerSeats[i].btn_add_robot` — NOT as a direct display
child. State.js exposes one `add_ai` action per empty seat with
`extra.seat = i`.

## Room settings (`state.room_settings`, `scene === 'create_room_dialog'`)

`uiscript.UI_Create_Room.Inst.allLines[]` is the canonical source. Filter
to lines that have a `tabGroup` (skips numeric/splice rows); each
filtered line is a one-of-N radio group:

```js
const radioLines = ui.allLines.filter(L => L && L.tabGroup);
// radioLines[gi].tabGroup.selectedIndex = idx  // setter ALSO works
```

- Group 0 (Mode) uses `toggleParent` children labelled `'template'`.
- Other groups use `toggleObjs[]`.
- Hidden advanced toggles (below the scrollable viewport) are still present
  in `allLines` and ARE settable via the index assignment — the same code
  path the game uses internally, including cascade refresh (changing Mode
  rebuilds player-count / time / handicap rows).
- Option labels come from the first non-empty `.text` field inside the
  template node. Group titles are localized graphics; the agent infers them
  from the option labels.

Settings DO NOT persist across Create-Room-dialog re-opens; the agent must
re-apply each time.

## Actionable kinds

`state.actionable.kind` (when `needs_my_action` is true) is one of:

| Kind                   | Meaning |
|------------------------|---------|
| `'discard'`            | Match scene, your turn, no call window. `options[]` = one entry per hand tile. |
| `'call_window'`        | Match scene, the game is offering you a call. `options[]` = chi/pon/.../pass. |
| `'afk'`                | "I'm back" AFK dialog is up. Dismiss it. |
| `'confirm_dialog'`     | Root-level Confirm/Cancel dialog. Two options. |
| `'gameend_dismiss'`    | Full-canvas overlay swallowing the first click after a match. |
| `'reward_confirm'`     | Post-match reward/next/finish buttons. |
| `'modal_close'`        | A pop view or the Create Room dialog is up; close or confirm it. For `create_room_dialog`, also includes one `set_room_setting` per non-selected option. |
| `'lobby_navigation'`   | `main_lobby` / `friendly_landing` / `room_lobby` — options include all navigation buttons + (in room_lobby) `start_match` / `leave_room` / `open_character_panel` / per-seat `add_ai`. |
| `'login'`              | `human_login` placeholder — call `login_wait.js`. |

## Meta-actions

`state.meta_actions[]` is the always-available out-of-flow set. Currently
populated only in the match scene:

- `leave_match` (`btn_leave` in `container_righttop`) — opens the
  leave-room confirm dialog.
- `open_settings` (`btn_set` in `container_righttop`).

These never set `needs_my_action` on their own — they're there so the agent
doesn't have to probe the scene graph to find "exit" or "settings".

## Coordinate spaces

```
design coords (1920 × 1080)
        |
        | Laya internal transform (pivot, anchor, scale) — node.localToGlobal handles it
        v
stage coords  ==  what node.localToGlobal returns
        |
        | linear scale: design(x,y) -> client(rect.x + x*rect.w/1920, rect.y + y*rect.h/1080)
        v
client/viewport coords  ==  what page.mouse needs
```

`__mj.designToClient(x, y)` and `__mj.clientToDesign(x, y)` (init.js) do this
in both directions. `__mj.globalCenter(node)` returns the node's center in
design coords. All `client: {x,y}` fields in `state.actionable.options[]` are
already-converted client coords ready for `page.mouse.move`.

## Network hook

`hook_events.js` patches the prototype of every reachable transport
(`game.MJNetMgr.Inst.netMJ`'s class, every `net.*` class with `sendRequest`
or `onRouteNotifyProto`, plus `app.NetAgent.sendReq2Lobby`). Events stream
to `window.__mj.events.buffer` (ring, default 500) and console.

The match server wraps every notify in `lq.ActionPrototype { name, step,
data: Uint8Array }`; the hook unwraps and decodes the inner action via
`net.ProtobufManager.lookupType('lq.' + name).decode(data)`.

### `events.buffer` event shape

```ts
{
  seq: number,         // monotonically increasing
  t: number,           // Date.now()
  dir: 'send' | 'send_lobby' | 'recv' | 'recv_rsp',
  name: string,        // ".lq.FastTest.inputOperation" or ".lq.ActionNewRound" etc.
  summary: object,     // shallow JSON-safe summary
  summary_json: string // pre-stringified, capped at 800 chars
}
```

Pull recent events with `events_tail.js({ sinceSeq: N })`. The agent loop
doesn't need this — `state.event_seq` is included in every `computeState()`
result, so the agent can detect "did anything happen on the wire since my
last inspect" without parsing the buffer.

### Duplicate emissions

A single lobby request flows through three patched prototypes
(`NetAgent.sendReq2Lobby` → `NetRouteGroup.sendRequest` →
`Socket.sendRequest`). You'll see the same name with `dir` values
`send_lobby`, `send`, `send`. Match-route traffic is single-emit.

### Privacy: tokens in the buffer

`prepareLogin`, `oauth2Login`, `emailLogin`, `loginVerifyCode`, and
`enterGame` carry Yostar/MJ tokens. Do NOT echo `summary_json` for any of
those names, persist the buffer, or send it to any external service.
