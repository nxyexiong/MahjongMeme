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

These must be clicked via Playwright's native mouse (synthesized DOM events
don't reach Laya's 3D raycaster). The agent passes
`inspect({ do: 'click', button_name: 'btn_peng' })` and `inspect.js` does
`page.mouse.move/down/up`.

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
- Do NOT call `app.NetAgent.sendReq2MJ` to fabricate packets or mutate
  `GameMgr.Inst` fields. The server cross-validates every action.
- Do NOT click hand tiles via `page.mouse` for discards — use the match
  controller (`setChoosePai` + `DoDiscardTile`). The 3D raycaster path is
  flaky enough to time you out.
- Do NOT loop on `inspect` faster than ~1 s; `computeState()` is cheap but
  the polling loop inside `inspect.js` already does this.
