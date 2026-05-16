# mahjong-soul skill

Inspect and play [Mahjong Soul](https://mahjongsoul.game.yo-star.com/) (web
client) through Playwright MCP.

## When to invoke

The user mentions Mahjong Soul: open it, look at it, navigate the lobby,
create a room, play a hand, watch a match.

Do not invoke for other mahjong sites — internals here are specific to the
Laya-based Yo-star build.

## The mental model

Everything happens through **one tool**: `scripts/inspect.js`.

- **`inspect`** does two things in order:
  1. Optionally execute a single action (discard a tile or click a button).
  2. Block (polling inside the page) until something needs the agent's
     decision — your discard turn, a chi/pon/kan/riichi/ron prompt, a modal
     popup, the gameend screen, the lobby — and then return the full
     observable state.
- The agent reads the returned `state`, **thinks** about what to do, and
  calls `inspect` again with the chosen action. That is the entire loop.

```
state = inspect()                        # initial — no action
while state.scene != 'match_end' and not state.timeout:
    action = decide(state)               # YOU think; nothing in code decides
    state = inspect(action=action)
```

**Do not**:
- take screenshots during a match (use `state.match.*` instead — faster and
  more accurate),
- enumerate the Laya scene graph from outside `inspect` (everything you need
  is already in `state.actionable.options[]` and `state.match`),
- dispatch your own clicks or hand-roll evaluate calls for game actions,
- put strategy heuristics in the scripts (`inspect.js` is observer + executor
  only; the agent is the player).

## Bootstrap (once per page load)

After `playwright-browser_navigate` and a `wait_for { time: 15 }` to let
Laya finish booting, install the helpers:

```
playwright-browser_evaluate  function = <contents of scripts/init.js>
playwright-browser_evaluate  function = "() => (" + <hook_events.js> + ")({})"
```

These set up `window.__mj` (coord helpers, event buffer, network hooks,
match-controller pointer). Re-run them after any page reload.

Then run `inspect.js` once. If `state.scene === 'login'`:

1. Call `ask_user`: _"Mahjong Soul is open. Please log in, then say 'ok'."_
2. Inject `scripts/login_wait.js` to block until `GameMgr.Inst.logined`.
3. Re-run `inspect.js`.

## Running inspect

`inspect.js` is an `async (page) => { ... }`. Call it inline through
`playwright-browser_run_code_unsafe` — **paste the action and the wait loop
together in the `code` parameter**. Do not split into "write file →
substitute OPTIONS → run file"; build the whole script in the same tool
call. The repository copy at `scripts/inspect.js` is a reference template;
inline the parts you need at the call site.

Minimum inline form (just observe — block until you have a decision):

```js
async (page) => {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < 200000) {
    last = await page.evaluate('window.__mj.computeState()');
    if (!last.ok) return last;
    if (last.needs_my_action || last.scene === 'match_end') return last;
    await page.waitForTimeout(900);
  }
  return Object.assign({ timeout: true }, last || {});
}
```

Discard form (act, then wait for next decision):

```js
async (page) => {
  const tile = '7z';   // <-- the tile you decided to discard
  const r = await page.evaluate((tile) => {
    const me = window.__mj.match.mainrole;
    if (!me.can_discard) return { ok: false, err: 'cannot discard right now' };
    function ts(v){return v.index+['m','p','s','z'][v.type]+(v.dora?'*':'');}
    let pick = null;
    for (let i = me.hand.length - 1; i >= 0; i--)
      if (ts(me.hand[i].val) === tile) { pick = me.hand[i]; break; }
    if (!pick) return { ok: false, err: 'not in hand', hand: me.hand.map(t=>ts(t.val)) };
    me.setChoosePai(pick, pick === me.last_tile);
    me.DoDiscardTile();
    return { ok: true };
  }, tile);
  if (!r.ok) return { error: 'discard_failed', details: r };
  const actionedAt = Date.now();
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < 200000) {
    last = await page.evaluate('window.__mj.computeState()');
    if (!last.ok) return last;
    if (last.scene === 'match_end') return last;
    if (last.needs_my_action) {
      // In-match decisions are turn-based — return immediately. Outside
      // the match, enforce a 3-second post-action settle so we don't
      // hammer lobby/modal buttons.
      if (last.scene === 'match' || Date.now() - actionedAt >= 3000) return last;
    }
    await page.waitForTimeout(900);
  }
  return Object.assign({ timeout: true }, last || {});
}
```

Click form (for call windows, modal close, lobby buttons):

```js
async (page) => {
  const button_name = 'btn_peng';   // or 'btn_cancel', 'btn_chi', etc.
  const coords = await page.evaluate((name) => {
    const mj = window.__mj;
    function cv(n){let c=n;while(c&&c!==Laya.stage){if(c.visible===false)return false;c=c.parent;}return true;}
    function vis(f){const o=[];function w(r,d){if(!r||d>40)return;if(r.visible&&cv(r)&&f(r))o.push(r);const k=r._childs||r._children||[];for(let i=0;i<k.length;i++)w(k[i],d+1);}w(Laya.stage,0);return o;}
    const btns = vis(n => n.name === name && n.mouseEnabled);
    if (!btns.length) return null;
    const d = mj.globalCenter(btns[0]);
    return mj.designToClient(d.x, d.y);
  }, button_name);
  if (!coords) return { error: 'button_not_found', button_name };
  await page.mouse.move(coords.x, coords.y);
  await page.waitForTimeout(80);
  await page.mouse.down(); await page.waitForTimeout(80); await page.mouse.up();
  const actionedAt = Date.now();
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < 200000) {
    last = await page.evaluate('window.__mj.computeState()');
    if (!last.ok) return last;
    if (last.scene === 'match_end') return last;
    if (last.needs_my_action) {
      if (last.scene === 'match' || Date.now() - actionedAt >= 3000) return last;
    }
    await page.waitForTimeout(900);
  }
  return Object.assign({ timeout: true }, last || {});
}
```

| Action shape                                | What happens |
|---------------------------------------------|--------------|
| (omitted)                                   | Pure observe — wait, then return state. |
| `{do:'discard', tile:'5z'}`                 | Pick that tile from your hand and discard via `mainrole.setChoosePai + DoDiscardTile`. No DOM clicks, no race. Tile strings: `Nm` man, `Np` pin, `Ns` sou, `Nz` honor (1z=E,2z=S,3z=W,4z=N,5z=白,6z=發,7z=中); red fives are `5m*`/`5p*`/`5s*`. |
| `{do:'click', button_name:'btn_peng'}`      | Resolve the named visible+mouseEnabled Laya node, click via native CDP mouse. Use for call windows, modals, lobby buttons, add-AI seats, etc. |
| `{do:'click', client:{x,y}}`                | Click an absolute viewport coord. Use the `client` field that came back in `state.actionable.options[]`. |
| `{do:'call', type:'chi', index:K}`          | Send the wire packet `inputChiPengGang {type:2, index:K}`. For multi-chi, `K` is the position in `state.actionable.chi_combinations[]` (see docs/action-vocabulary.md "Wire-level dispatch"). |
| `{do:'set_room_setting', group_id, option_index}` or `{…, option_label}` | Set a Create-Room toggle programmatically via `ui.allLines[gid].tabGroup.selectedIndex = idx`. Same code path as a human click; works for hidden advanced groups too. |

After executing the action, the inline wait loop polls
`__mj.computeState()` (no extra round-trips) until
`state.needs_my_action === true` or scene transitions to `match_end`, then
returns.

## State shape (what you actually read)

```
{
  ok: true,
  scene: 'login' | 'main_lobby' | 'friendly_landing' | 'create_room_dialog'
       | 'room_lobby' | 'match' | 'match_end' | 'transition',
  modal: { kind, name } | null,   // 'afk', 'gameend', 'pop',
                                   // 'create_room_dialog', 'confirm_dialog'
  needs_my_action: boolean,
  actionable: {
    kind: 'discard' | 'call_window' | 'afk' | 'confirm_dialog'
        | 'modal_close' | 'reward_confirm' | 'gameend_dismiss'
        | 'lobby_navigation' | 'login' | null,
    options: [
      // For discard:     { action:'discard', tile, slot }
      // For call_window: { action:'chi'|'pon'|'kan'|'hu'|'zimo'|'lizhi'|'pass',
      //                    button_name:'btn_peng', client:{x,y}, ... }
      // For confirm_dialog: two entries — action:'confirm' or 'cancel'
      // For modal/lobby: { action:..., button_name, client:{x,y}, ... }
    ],
  },
  meta_actions: [                 // out-of-flow buttons always available
    // e.g. in match: { action:'leave_match', button_name:'btn_leave', ... }
    //                { action:'open_settings', button_name:'btn_set', ... }
  ],
  room: null | {                  // populated when scene === 'room_lobby'
    room_id, owner_id, is_host, max_player_count,
    seats: [{seat, account_id, nickname, is_me, is_empty, is_ai, ready}, ...],
    seats_filled, seats_open, all_ready, mode, public_live,
  },
  room_settings: null | {         // populated when scene === 'create_room_dialog'
    groups: [{
      group_id, is_advance,
      options: [{label, selected}, ...],
      selected_index, selected_label,
    }, ...]
  },
  account: { logined, name, id },
  match: null | {
    my_seat, scores: [4],
    chang, ju, ben, left_tile_count,
    dora_indicators: ['2m', ...],
    hand: ['4p','5p',...],              // includes drawn tile when can_discard
    melds:    [[ {type,tiles}, ... ], ... ],   // per seat
    discards: [[ '4z','8m', ... ], ... ],      // per seat, in order
    last_discard: { seat, tile, is_moqie } | null,
    liqi: [bool, bool, bool, bool],
    can_discard,
  },
  event_seq: N,
}
```

**`actionable.options[]` and `meta_actions[]` together enumerate every
button the agent might press in the current state.** If something the
agent needs to click is missing from both lists, that is a state.js bug —
fix state.js, do not probe the scene graph from the call site.

## How the agent should think each turn

1. `state.actionable.kind === 'call_window'` → decide which of the offered
   call options serves your hand. The options array contains every legal
   call the game is currently letting you make plus `pass`. Pick one's
   `button_name` and call `inspect({do:'click', button_name})`.
2. `state.actionable.kind === 'discard'` → look at `state.match.hand`,
   `state.match.discards` (your river + the three opponents'),
   `state.match.melds`, `state.match.liqi`, `state.match.dora_indicators`,
   and `state.match.left_tile_count`. Decide a tile. Call
   `inspect({do:'discard', tile:'<tile>'})`. **Always specify by `tile`
   string** rather than `slot` so you can't be off-by-one after a pon/chi
   has re-ordered the hand.
3. `state.actionable.kind === 'afk'` → click the dismiss option immediately.
4. `state.actionable.kind === 'gameend_dismiss'` /  `'reward_confirm'` →
   click the offered option to advance through end-of-match screens.
5. `state.actionable.kind === 'modal_close'` → a `pop_view` (character
   panel) or similar is on top. Click its close button before doing
   anything else.
6. `state.actionable.kind === 'lobby_navigation'` → use the offered options
   to drive through main lobby → friendly landing → create room → room
   lobby → start. In `room_lobby` the options also include per-seat
   `add_ai` (host only), `start_match`, `leave_room`, and
   `open_character_panel`. Read `state.room` for the seat layout.
7. `state.actionable.kind === 'modal_close'` and `scene ===
   'create_room_dialog'` → `state.room_settings.groups[]` lists every
   toggle row. To change a setting, call
   `inspect({do:'set_room_setting', group_id, option_label})`. To accept
   the dialog and create the room, click `btn_create` (`confirm_modal`).
   Settings don't persist across re-opens — re-apply each time.

Tanyao / dora / shanten / safety — those are **your** reasoning. Don't put
them in the scripts.

## Hard rules

1. Never paste user credentials or share the buffer entries for
   `prepareLogin` / `oauth*` / `loginVerifyCode` / `enterGame` — they
   contain Yostar `access_token`s.
2. The agent only ever needs **one** Playwright tool per turn:
   `playwright-browser_run_code_unsafe` carrying `scripts/inspect.js`.
   (Plus the one-time bootstrap evaluate calls.) If you are reaching for
   `take_screenshot` or hand-rolled `evaluate`s during a match, stop —
   either `inspect` already gives you the info, or `inspect` needs to be
   fixed to surface it.
3. Re-run `init.js` and `hook_events.js` after every `navigate` or full
   page reload — `window.__mj` and the network hooks are wiped.
4. Do not call `app.NetAgent.sendReq2MJ` to FABRICATE STATE (fake an
   opponent's discard, mutate `GameMgr.Inst` fields, etc.). The server
   cross-validates every action.
   It IS safe to use `sendReq2MJ` to dispatch YOUR OWN action with the
   correct body — those are the same packets the UI buttons send. See
   the "Wire-level dispatch" section of `docs/action-vocabulary.md`.
5. The human owns the account. Confirm major actions (real-money ranked
   queue, surrendering, leaving a paid table) with `ask_user` first.

## Reference

- [docs/state-model.md](docs/state-model.md) — globals, the `O` match
  controller path, coord transforms, network hook detail.
- [docs/action-vocabulary.md](docs/action-vocabulary.md) — verified
  `btn_*` names, server notify events, tile encoding.
- [docs/troubleshooting.md](docs/troubleshooting.md) — recovery recipes.
