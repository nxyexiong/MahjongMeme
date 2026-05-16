# Troubleshooting

## `inspect` returns `{ ok: false, reason: 'init_missing' }` or `'state_not_installed'`

`window.__mj` (or `__mj.computeState`) was wiped — usually by a
`playwright-browser_navigate`, account switch, region change, or forced
refresh. Re-bootstrap in order:

1. `playwright-browser_evaluate` with `scripts/init.js` (whole file is one
   arrow function).
2. `playwright-browser_evaluate` with `() => (` + `scripts/hook_events.js` +
   `)({})` (wrap to supply opts).
3. `playwright-browser_run_code_unsafe` with `scripts/state.js` (already an
   `async (page) => {…}`).
4. Run `inspect.js` again.

## Match-time discard didn't fire / `inputOperation` shows `moqie: true`

You probably tried to click a tile via `page.mouse`. **Don't.** Discards go
through the match controller directly:

```js
inspect({ do: 'discard', tile: '5m*' })   // tile string, not slot
```

`moqie: true` in the outbound `inputOperation` means the server timed you
out and tsumogiri'd. If you DID issue the controller call, check:

- Was `state.match.can_discard` true at the time? If not, it wasn't your
  turn — the previous decision was probably a call window.
- Did the tile actually exist in `state.match.hand`? After a pon/chi the
  hand re-orders; always re-read state before deciding.

## Call button click had no effect

Call buttons (`btn_peng`, `btn_chi`, etc.) ARE DOM-level. They must be
clicked via Playwright's NATIVE mouse, not synthesized `PointerEvent`:

```js
await page.mouse.move(client.x, client.y);
await page.waitForTimeout(80);
await page.mouse.down();
await page.waitForTimeout(80);
await page.mouse.up();
```

`inspect.js` does this for you when you pass
`inspect({ do: 'click', button_name: 'btn_peng' })`. If the result is
`{ error: 'button_not_found' }`, the call window already closed — re-inspect
and pick from the new `state.actionable.options[]`.

Alternative: use the wire-level dispatch documented in
[action-vocabulary.md](action-vocabulary.md). For multi-chi, the wire
path is more reliable — clicking `btn_chi` opens a sub-panel that the
agent then has to click again, while
`sendReq2MJ('FastTest', 'inputChiPengGang', {type:2, index:K})` commits
the chosen combination in one shot.

## Discard after chi silently fails / `can_discard` stuck at false

You hit the **kuikae** (swap-call) rule. After chi-ing, the server
rejects discarding:

- the called tile itself (e.g. chi'd 3p with 2p+4p → can't discard 3p),
- and for some chi positions, the swap-chi mate that would form a
  different chi with the same partner pair.

Symptoms: `inputOperation type=1` sent, no error returned client-side,
but `mainrole.can_discard` flips to false and stays there until the
round times out.

Fix: after a chi commits (you see `mainrole.container_ming.mings` grow),
DON'T immediately pick a tile from the just-formed chi range. Drop a
safe tile from elsewhere in the hand first. The conservative rule:

```text
forbidden after chi on `called`:
  the called tile,
  AND if your partners were the LOWER two (e.g. 2p+3p on 4p): also called+3 (7p),
  AND if your partners were the HIGHER two (e.g. 5p+6p on 4p): also called-3 (1p),
  AND if your partners straddle (e.g. 3p+5p on 4p): no extra restriction.
```

In practice, drop your safest tile (honors, terminals, distant
isolated tiles) right after a chi — never a tile in the same suit as
the called tile.

## `inspect` times out (returns `{ timeout: true, … }`)

The wait loop returns once `state.needs_my_action === true` OR `scene ===
'match_end'`. If you hit the default 180 s timeout:

- During a match: the game is waiting on an opponent and the agent's last
  action probably already advanced the turn. The included `last` snapshot
  shows the current scene/match state — usually fine to immediately call
  `inspect` again.
- In a transition scene: the game is mid-loading. Re-call `inspect` after a
  short wait; eventually `scene` flips to `main_lobby` / `room_lobby` /
  `match`.
- In a stuck modal you didn't recognize: take a `playwright-browser_snapshot`
  (NOT during a match) to identify it, then add the recognition rule to
  `state.js`.

## `state.actionable.options[]` is empty but `needs_my_action === true`

This is a `state.js` bug. The state recognized a scene/modal that requires
input but didn't enumerate buttons for it. Fix path:

1. Snapshot the page or read `Laya.stage` to find the relevant button.
2. Add the recognition to the matching branch in `state.js`
   (`scene === '…'` or `modal && modal.kind === '…'`).
3. Re-install `state.js` and re-inspect.

**Do not** patch around it by clicking via raw `page.evaluate` from the call
site — that's exactly what the single-tool design forbids.

## `actionable.kind === 'modal_close'` but no `confirm_modal` option visible

The modal might be a `pop_*` with only a close button (e.g. a notice). All
modals are escapable via the `close_modal` action. If you actually need to
proceed (e.g. you're stuck on a tutorial), re-check `state.modal.name` and
add a more specific recognition.

## Create Room dialog: option `set_room_setting` returns
`{ error: 'set_room_setting_failed', details: { err: 'group_not_found' } }`

`UI_Create_Room.Inst` isn't open. Confirm `state.modal.kind ===
'create_room_dialog'` first. If the dialog IS open but the group_id is out
of range, the layout changed: re-inspect and pick from the updated
`state.room_settings.groups[]`.

## Create Room settings reset between dialog re-opens

Expected. The game does not persist Create Room settings across closes.
Re-apply each time the dialog is opened.

## Hidden advanced toggles seem to set but the UI doesn't show the highlight

Functional, cosmetic-only. The `tabGroup.selectedIndex` assignment fires
the same internal handlers as a human click, but the highlight redraw on
hidden rows can lag until the user expands the Advanced section or until a
parent group (Mode) is changed. The actual setting takes effect.

## Reload-after-crash recipe

1. `playwright-browser_navigate { url: 'https://mahjongsoul.game.yo-star.com/' }`
2. `playwright-browser_wait_for { time: 18 }` (Laya boot + asset load).
3. Re-install `init.js`, `hook_events.js`, `state.js`.
4. `inspect.js` to confirm `state.scene` (usually `main_lobby` if the
   session cookie is intact, otherwise `login`).

## Lobby requests appear 2-3× in the event log

Expected. Each lobby request flows through three patched prototypes
(`NetAgent.sendReq2Lobby` → `NetRouteGroup.sendRequest` →
`Socket.sendRequest`). Match-route traffic is single-emit. Dedup with
`(dir, name, summary_json)` if you care.

## Tokens visible in the buffer

`prepareLogin`, `oauth2Login`, `emailLogin`, `loginVerifyCode`, and
`enterGame` carry Yostar/MJ tokens. Do NOT echo `summary_json` for any of
those, persist the buffer to disk, or send it externally. Filter before
relaying:

```js
events.filter(e => !/prepareLogin|oauth2Login|emailLogin|loginVerifyCode|enterGame/.test(e.name))
```

## Game updated — button names or event names changed

Reconfirm with live data:

- For UI: run `inspect.js` and read `state.actionable.options[].button_name`
  / `state.meta_actions[].button_name`. For not-yet-modeled scenes, walk
  `Laya.stage` once via a one-off `page.evaluate` (outside the match) to
  identify the new name, then add it to `state.js`.
- For events: tail `__mj.events.buffer[]` (or use `events_tail.js`) and
  read the new `name` strings.

Then update `docs/action-vocabulary.md`.

## "Client update required" screen

The skill can't bypass forced updates. Wait for Yo-star to ship the new
build.

## Window resized → clicks miss

`__mj.designToClient` reads `getBoundingClientRect()` on every call, so
coords stay correct as long as you re-derive them from a fresh
`computeState()`. Cached `client: {x,y}` from an older `state.actionable`
go stale after a resize — always click using the coords from the latest
inspect result.
