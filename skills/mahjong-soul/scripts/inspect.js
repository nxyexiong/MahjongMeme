// MahjongSoul skill — inspect (the SOLE agent tool).
//
// Run via `playwright-browser_run_code_unsafe` (this whole file is the script).
// Edit OPTIONS to attach an action. inspect will:
//   1. Execute the action (discard or click), if any.
//   2. Block, polling __mj.computeState(), until a decision is needed
//      (needs_my_action === true) or scene === 'match_end' or timeout.
//   3. Return that state snapshot.
//
// State shape, action vocabulary, and the agent loop are documented in
// SKILL.md and docs/. Do NOT use any other Playwright tool mid-match.
//
// REQUIRES bootstrap: init.js + hook_events.js + state.js must be loaded
// once per page. state.js installs window.__mj.computeState which this
// script polls.

(async (page) => {
  const OPTIONS = {
    // action: { do: 'discard', tile: '5m*' },
    // action: { do: 'discard', slot: 12 },
    // action: { do: 'click', button_name: 'btn_peng' },
    // action: { do: 'click', client: { x: 729, y: 481 } },
    // wait_max_seconds: 180,
  };

  if (OPTIONS.action && OPTIONS.action.do && OPTIONS.action.do !== 'noop') {
    const a = OPTIONS.action;
    if (a.do === 'discard') {
      const r = await page.evaluate((act) => {
        const O = window.__mj && window.__mj.match;
        if (!O || !O.mainrole) return { ok: false, err: 'no match controller' };
        const me = O.mainrole;
        if (!me.can_discard) return { ok: false, err: 'cannot discard right now' };
        function ts(v) { return v.index + ['m','p','s','z'][v.type] + (v.dora ? '*' : ''); }
        let pick = null;
        if (act.slot !== undefined && act.slot !== null) pick = me.hand[act.slot];
        else if (act.tile) {
          for (let i = me.hand.length - 1; i >= 0; i--) {
            if (ts(me.hand[i].val) === act.tile) { pick = me.hand[i]; break; }
          }
        }
        if (!pick) return { ok: false, err: 'tile not found', hand: me.hand.map(t => ts(t.val)) };
        me.setChoosePai(pick, pick === me.last_tile);
        me.DoDiscardTile();
        return { ok: true };
      }, a);
      if (!r.ok) return { error: 'discard_failed', details: r };
    } else if (a.do === 'click') {
      let cx = a.client && a.client.x;
      let cy = a.client && a.client.y;
      if (cx == null && a.button_name) {
        const coords = await page.evaluate((act) => {
          const mj = window.__mj;
          function cv(n) { let c = n; while (c && c !== Laya.stage) { if (c.visible === false) return false; c = c.parent; } return true; }
          function vis(f) { const o = []; function w(r, d) { if (!r || d > 40) return; if (r.visible && cv(r) && f(r)) o.push(r); const k = r._childs || r._children || []; for (let i = 0; i < k.length; i++) w(k[i], d + 1); } w(Laya.stage, 0); return o; }
          const btns = vis(n => n.name === act.button_name && n.mouseEnabled);
          if (!btns.length) return null;
          const d = mj.globalCenter(btns[0]);
          return mj.designToClient(d.x, d.y);
        }, a);
        if (!coords) return { error: 'button_not_found', button_name: a.button_name };
        cx = coords.x; cy = coords.y;
      }
      if (cx == null || cy == null) return { error: 'click_missing_target' };
      await page.mouse.move(cx, cy);
      await page.waitForTimeout(80);
      await page.mouse.down();
      await page.waitForTimeout(80);
      await page.mouse.up();
    } else if (a.do === 'set_room_setting') {
      // Set a Create Room dialog toggle programmatically by writing to the
      // corresponding `tabGroup.selectedIndex` on the matching line. This
      // is the same code path the game uses internally when the user
      // clicks an option; it triggers cascade refreshes (e.g. changing
      // Mode rebuilds the player-count / time / handicap rows). Works
      // for hidden advanced groups too.
      //
      // Requires {group_id, option_index} OR {group_id, option_label}.
      const r = await page.evaluate((act) => {
        const ui = window.uiscript && window.uiscript.UI_Create_Room && window.uiscript.UI_Create_Room.Inst;
        if (!ui || !Array.isArray(ui.allLines)) return { ok: false, err: 'create_room_ui_not_open' };
        function findText(node){const stk=[node];let cnt=0;while(stk.length&&cnt++<50){const c=stk.pop();if(c&&typeof c.text==='string'&&c.text)return c.text;const k=(c&&(c._childs||c._children))||[];for(const x of k)stk.push(x);}return '';}
        // Filter to groups that have a tabGroup (skips numeric/splice rows).
        const groups = ui.allLines.filter(L => L && L.tabGroup);
        const L = groups[act.group_id];
        if (!L) return { ok: false, err: 'group_not_found', group_count: groups.length };
        // Resolve option index.
        let idx = (act.option_index != null) ? act.option_index : -1;
        if (idx < 0 && act.option_label) {
          const tmpls = (L.toggleObjs && L.toggleObjs.length)
            ? L.toggleObjs
            : ((L.toggleParent._childs || L.toggleParent._children || []).filter(c => c.name === 'template').slice(1));
          idx = tmpls.findIndex(t => findText(t) === act.option_label);
        }
        if (idx < 0) return { ok: false, err: 'option_not_in_group' };
        try { L.tabGroup.selectedIndex = idx; }
        catch (e) { return { ok: false, err: 'tabgroup_set_failed: ' + e.message }; }
        return { ok: true };
      }, a);
      if (!r.ok) return { error: 'set_room_setting_failed', details: r };
    } else {
      return { error: 'unknown_action', action: a };
    }
  }

  // Post-action settle window. In-match decisions are turn-based so any
  // call/discard prompt that re-fires is a real new decision — return as
  // soon as state.needs_my_action is true. Outside the match, scenes like
  // 'lobby' / 'modal_close' / 'create_room_dialog' immediately set
  // needs_my_action=true again after every click; enforce a 3-second
  // minimum from action time so the agent doesn't spam.
  const actionedAt = (OPTIONS.action && OPTIONS.action.do && OPTIONS.action.do !== 'noop') ? Date.now() : 0;
  const NON_MATCH_SETTLE_MS = 3000;

  const maxMs = (OPTIONS.wait_max_seconds || 180) * 1000;
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < maxMs) {
    last = await page.evaluate('window.__mj && window.__mj.computeState ? window.__mj.computeState() : { ok:false, reason:"state_not_installed" }');
    if (!last || !last.ok) return last || { error: 'no_state' };
    if (last.scene === 'match_end') return last;
    if (last.needs_my_action) {
      if (last.scene === 'match' || !actionedAt || Date.now() - actionedAt >= NON_MATCH_SETTLE_MS) return last;
    }
    await page.waitForTimeout(900);
  }
  return Object.assign({ timeout: true }, last || {});
})
