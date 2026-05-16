# Action vocabulary

Verified against the `0.11.251.w` English client (May 2026). Reconfirm with
a `computeState()` snapshot (run `inspect.js`) if anything stops matching.

The agent never needs to look these up by hand: `state.actionable.options[]`
and `state.meta_actions[]` enumerate everything currently clickable.
This file documents the underlying names so `state.js` can be extended
when new scenes are added.

## Login screen

| Action                                  | How |
|-----------------------------------------|-----|
| Enter Yostar credentials                | **Do not.** Login is human-driven. |
| Wait for login                          | `ask_user` to prompt the human, then `login_wait.js`. |

`state.scene === 'login'`. `state.actionable.kind === 'login'` with a single
`{ action: 'human_login' }` placeholder.

## Main lobby

`state.scene === 'main_lobby'`. Buttons exposed under `actionable.options[]`:

| `name`                | Effect |
|-----------------------|--------|
| `btn_yibanchang`      | Ranked Match (bronze/silver/gold/jade/throne). |
| `btn_dajiangsai`      | Tournament Match. |
| `btn_yourenfang`      | Friendly Match (friend rooms). |
| `btn_set`             | Settings. |
| `btn_help`            | Help. |
| `btn_mail`            | Mail. |
| `btn_achievement`     | Achievements. |
| `btn_camera`          | Photo mode / character viewer. |
| `btn_xinshouyindao`   | Tutorial / beginner guide. |
| `btn_qiri`            | 7-day login award. |
| `btn_roleset`         | Character settings. |

All clicked the same way: `inspect({ do: 'click', button_name: '<name>' })`.

## Friendly Match landing

`state.scene === 'friendly_landing'`. Reached from main lobby via
`btn_yourenfang`.

| Action            | Underlying node |
|-------------------|------------------|
| `open_create_room`| `btn0` under `page_friend` |
| `open_join_room`  | `btn1` under `page_friend` |
| `back`            | `btn_back` under `container_title` |

## Create Room dialog

`state.scene === 'create_room_dialog'`, `state.modal.kind ===
'create_room_dialog'`. `actionable.kind === 'modal_close'`.

`state.room_settings.groups[]` describes every toggle row:

```js
{
  group_id: number,           // index into the filtered tabGroup-having lines
  is_advance: boolean,        // hidden behind the "Advanced" expander
  options: [{ label, selected }],
  selected_index: number,
  selected_label: string,
}
```

For each non-selected option, `actionable.options[]` includes one
`set_room_setting` entry. Apply via:

```js
inspect({ do: 'set_room_setting', group_id, option_index })
// or
inspect({ do: 'set_room_setting', group_id, option_label: 'Two-Wind' })
```

Inside the page this is `ui.allLines[gid].tabGroup.selectedIndex = idx` —
the same code path the game uses when a human clicks an option, including
cascade refreshes when group 0 (Mode) changes.

Other buttons in the dialog (`btn_create`, `btn_close`, `btn_cancel`) are
classified into `confirm_modal` / `close_modal` and surfaced under
`actionable.options[]` with their `button_name`.

**Settings do NOT persist across dialog re-opens** — re-apply each time.

## Room lobby (waiting room)

`state.scene === 'room_lobby'`. Reached after creating a room (or joining).
`state.room` carries the full seat layout (see state-model.md).

| Action                    | When | Underlying |
|---------------------------|------|------------|
| `start_match`             | Host only, when seats are filled and ready | `btn_start` at root |
| `leave_room`              | Always | `btn_leave` in `top` |
| `open_character_panel`    | Always | `btn_suit` at root |
| `add_ai` (per empty seat) | Host only, empty seat | `seat.btn_add_robot` (named field, NOT a direct display child) — `extra.seat` carries the seat index |

## In-match decision buttons

Returned under `state.actionable.kind === 'call_window'` with the action
pre-classified by intent.

| Intent | Button names |
|--------|--------------|
| chi    | `btn_chi`, `btn_chii` |
| pon    | `btn_peng`, `btn_pon` |
| kan    | `btn_gang`, `btn_kan`, `btn_minkan`, `btn_ankan` |
| lizhi  | `btn_lizhi`, `btn_liqi`, `btn_riichi` |
| zimo   | `btn_zimo`, `btn_tsumo` |
| hu     | `btn_hu`, `btn_ron` |
| kita   | `btn_babei`, `btn_kita` (sanma north) |
| pass   | `btn_quxiao`, `btn_pass`, `btn_skip`, `btn_cancel` |

You can dispatch either by **clicking the button** (`inspect({do:'click',
button_name})`) or by **sending the wire packet directly** (see "Wire-level
dispatch" below — preferred, especially for multi-chi where the click
opens a sub-panel).

Click path uses Playwright's native mouse (synthesized DOM events don't
reach Laya's 3D raycaster). `inspect.js` already does the
`page.mouse.move/down/up` sequence for you when you pass
`{do:'click', button_name}`.

## Wire-level dispatch (preferred for in-match decisions)

Every in-match decision can be sent via the WebSocket sender
`app.NetAgent.sendReq2MJ(namespace, method, body, cb)` — no DOM clicks
needed.

**Namespace gotcha**: the receiver-side notify names use `.lq.FastTest.*`
(visible in the event buffer), but `sendReq2MJ` takes the **bare**
`'FastTest'`. Using `'.lq.FastTest'` throws
`ERR_SERVICE_NOT_FOUND, name=FastTest`.

Two wire methods cover all in-match input:

- `inputOperation`   — discard / riichi / tsumo / ankan / kita / cancel-own-turn
- `inputChiPengGang` — chi / pon / open-kan / chakan / ron / pass-call

Op-type enum (`mjcore.E_PlayOperation`):

| Code | Name        | Sent via            |
|------|-------------|---------------------|
| 1    | dapai       | `inputOperation`    |
| 2    | eat (chi)   | `inputChiPengGang`  |
| 3    | peng (pon)  | `inputChiPengGang`  |
| 4    | an_gang     | `inputChiPengGang`  |
| 5    | ming_gang   | `inputChiPengGang`  |
| 6    | add_gang    | `inputChiPengGang`  |
| 7    | liqi        | `inputOperation`    |
| 8    | zimo        | `inputOperation`    |
| 9    | rong (ron)  | `inputChiPengGang`  |
| 11   | babei (kita)| `inputOperation`    |

### Verified wire bodies

| Intent          | Body                                                                            |
|-----------------|---------------------------------------------------------------------------------|
| Discard a tile  | `{type:1, tile:"5z", moqie:false, timeuse:N, tile_state:0}` via `inputOperation` |
| Riichi declare  | `{type:7, tile, moqie, timeuse}` via `inputOperation` (use `mainrole.Action_LiQi(tile.val, moqie, false)` wrapper) |
| Tsumo           | `{type:8, index:0, timeuse:1}` via `inputOperation` |
| Kita (sanma N)  | `{type:11, index:0, timeuse:1}` via `inputOperation` |
| Cancel own turn | `{cancel_operation:true, timeuse:N}` via `inputOperation` |
| Chi (single)    | `{type:2, index:0, timeuse:1}` via `inputChiPengGang` |
| Chi (multi)     | `{type:2, index:K, timeuse:1}` where K is the position in `uiscript.UI_ChiPengHu.Inst._data.chi[]` |
| Pon             | `{type:3, index:0, timeuse:1}` via `inputChiPengGang` |
| Kan (open)      | `{type:5, index:0, timeuse:1}` via `inputChiPengGang` |
| Kan (closed)    | `{type:4, index:K, timeuse:1}` — multi-ankan: K = position in `_data.gang[]` |
| Kan (added)     | `{type:6, index:0, timeuse:1}` via `inputChiPengGang` |
| Ron             | `{type:9, index:0, timeuse:1}` via `inputChiPengGang` |
| Pass call window| `{cancel_operation:true, timeuse:N}` via `inputChiPengGang` |

### Where the call combinations live

`uiscript.UI_ChiPengHu.Inst._data` holds the legal combinations for
the currently-open call window:

```js
_data = {
  chi:  ["3p|5p"],          // single chi  — index 0
  chi:  ["2p|3p", "3p|5p"], // two chi    — index 0 or 1
  peng: ["5z|5z"],          // pon        — index 0
  gang: ["3m|3m|3m"],       // kan tile   — index per entry
}
```

Each entry is a `'|'`-joined string of the partner tiles you commit (NOT
including the called tile). For chi, you pick by partner pair. For
ankan, by the called tile.

`mainrole.operation.operation_list` ALSO contains this in protobuf form,
but the UI panel's `_data` is canonically populated whenever the panel
is visible. Read either; we prefer `_data` because it survives all UI
lifecycle quirks.

## Discard

`state.actionable.kind === 'discard'`. `state.match.can_discard === true`.
`options[]` has one entry per hand tile:
`{ action: 'discard', tile: '5m*', slot: 12 }`.

```js
inspect({ do: 'discard', tile: '5m*' })   // preferred
inspect({ do: 'discard', slot: 12 })      // discouraged — hand re-orders after pon/chi
```

Internally: `me.setChoosePai(pick, pick === me.last_tile); me.DoDiscardTile()`.
The `pick === me.last_tile` test produces the correct `moqie` flag
(tsumogiri vs in-hand discard).

## AFK dialog

`state.modal.kind === 'afk'` (the "I'm back" overlay). One option:
`{ action: 'dismiss_afk' }` — click its node.

## Confirm dialog

`state.modal.kind === 'confirm_dialog'`. Root-level `btn_confirm` +
`btn_cancel`. Two options: `confirm` and `cancel`. The visible question text
(e.g. "Do you wish to leave this room?") is captured into the option labels
when one is present.

## End-of-game flow

After the final hand:

1. `gameend` container appears with a full-canvas `btn_click` overlay.
   `state.actionable.kind === 'gameend_dismiss'`, one option to click the
   overlay (approx (1745, 990) in design coords).
2. Reward / next / finish screen. `state.actionable.kind === 'reward_confirm'`
   with one option per visible `btn_confirm` / `btn_next` / `btn_close` /
   `btn_finish` (or the text label `Confirm` if none of those exist).
3. Back to main lobby.

## Meta-actions (match scene only)

Always available, never set `needs_my_action`:

| Action          | Node |
|-----------------|------|
| `leave_match`   | `btn_leave` in `container_righttop` (opens a `confirm_dialog`). |
| `open_settings` | `btn_set` in `container_righttop`. |

## Server notify event names (verified)

These appear in `__mj.events.buffer` as `dir: 'recv', name: '.lq.<NAME>'`,
already auto-unwrapped from `lq.ActionPrototype`.

| Name                           | Meaning |
|--------------------------------|---------|
| `.lq.NotifyPlayerLoadGameReady`| All players loaded; match about to start. |
| `.lq.ActionMJStart`            | Match scene loaded server-side. |
| `.lq.ActionNewRound`           | New hand. Body has `chang`, `ju`, `ben`, `tiles`, `dora`, `scores`, `left_tile_count`. |
| `.lq.ActionDealTile`           | Draw. Yours has `tile != ""`; opponents arrive as `action: '<undecoded>'` (server-encrypted). |
| `.lq.ActionDiscardTile`        | Discard. `seat`, `tile`, `is_liqi`, `moqie`. |
| `.lq.ActionChiPengGang`        | Chi/pon/kan call landed. `seat`, `type` (0=chi/1=pon/2=kan), `tiles`, `froms`. |
| `.lq.ActionAnGangAddGang`      | Concealed or added kan. |
| `.lq.ActionLiqi`               | Riichi declared. |
| `.lq.ActionGangResult` / `.lq.ActionGangResultEnd` | New dora flipped after a kan. |
| `.lq.ActionHule`               | Win. `hules[]` per winner with `yakus`, `fu`, `fan`, `point_rong`. |
| `.lq.ActionNoTile`             | Exhaustive draw. `players[]` with tenpai + deltas. |
| `.lq.ActionLiuJu`              | Abortive draw. |
| `.lq.ActionBabei`              | Sanma kita played. |
| `.lq.NotifyGameTerminate`      | Match aborted by server. |
| `.lq.NotifyGameEndResult`      | Whole game ended; rank/point delta. |

## Client request names (verified)

`dir: 'send'`, `name: '.lq.<Service>.<method>'`. Lobby requests duplicate
2-3× due to layered transports; match-route traffic is single-emit.

| Name                          | Meaning |
|-------------------------------|---------|
| `.lq.FastTest.inputOperation` | Your discard / riichi / pass. Body: `type` (1=discard), `tile`, `moqie`, `timeuse`. |
| `.lq.FastTest.inputChiPengGang` | Your chi/pon/kan reaction. |
| `.lq.FastTest.enterGame`      | Sent on match start. |
| `.lq.FastTest.confirmNewRound`| Acknowledge next round. |
| `.lq.FastTest.syncGame`       | Mid-match resync. |
| `.lq.Lobby.heatbeat`          | Lobby heartbeat (~5 s — filter out). |
| `.lq.Route.heartbeat`         | Transport heartbeat. |
| `.lq.Lobby.fetchAccountInfo`  | Refresh account profile. |
| `.lq.Lobby.readAnnouncement`  | Mark a notice as read. |

## What NOT to do

- Do NOT echo / persist `summary_json` for `prepareLogin`, `oauth2Login`,
  `emailLogin`, `loginVerifyCode`, or `enterGame` — they carry tokens.
- Do NOT click hand tiles via `page.mouse` for discards — use the match
  controller (`setChoosePai` + `DoDiscardTile`). The 3D raycaster path is
  flaky enough to time you out.
- Do NOT discard a kuikae-restricted tile right after a chi (the called
  tile + same-suit swap-chi mate). The server silently rejects it and
  leaves `can_discard=true` until the round ages out. Always inspect
  `mainrole.hand[i]` flags after a chi (or just retry with a different
  candidate from your top-K).
- Do NOT loop on `inspect` faster than ~1 s; `computeState()` is cheap but
  the polling loop inside `inspect.js` already does this.

## Calling `sendReq2MJ` for actions: when it's safe

The blanket "don't call sendReq2MJ" warning applies to **fabricating
state** — e.g. trying to fake an opponent's discard or mutate
`GameMgr.Inst`. The server cross-validates every action.

What IS supported and verified safe: the wire bodies listed in the
"Wire-level dispatch" table above. They're literally the same packets
the UI buttons issue, just sent without the click. The server treats
them identically to a button press.
