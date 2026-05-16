// MahjongSoul skill — installs window.__mj.computeState.
//
// Run once during the page-load bootstrap (after init.js, after
// hook_events.js). Run via `playwright-browser_run_code_unsafe` with this
// file as the script — it is already an `async (page) => { ... }` wrapper.
// Re-running is safe: it just replaces the function.
//
// `inspect.js` polls window.__mj.computeState() inside the page.

(async (page) => {
  const installed = await page.evaluate(() => {
    if (!window.__mj || !window.__mj._installed) return { ok: false, reason: 'init_missing' };

    window.__mj.computeState = function () {
      const mj = window.__mj;
      const g = (window.GameMgr && GameMgr.Inst) || {};
      const events = window.__mj.events;
      const eventSeq = events ? events.seq : 0;

      function chainVisible(node) {
        let cur = node;
        while (cur && cur !== Laya.stage) {
          if (cur.visible === false) return false;
          cur = cur.parent;
        }
        return true;
      }
      function visibleNodes(filter) {
        const out = [];
        function walk(root, depth) {
          if (!root || depth > 40 || out.length > 400) return;
          if (root.visible && chainVisible(root) && filter(root)) out.push(root);
          const kids = root._childs || root._children || [];
          for (let i = 0; i < kids.length; i++) walk(kids[i], depth + 1);
        }
        walk(Laya.stage, 0);
        return out;
      }
      function descendantsOf(root, filter) {
        const out = [];
        function walk(r, depth) {
          if (!r || depth > 40) return;
          if (r.visible && filter(r)) out.push(r);
          const kids = r._childs || r._children || [];
          for (let i = 0; i < kids.length; i++) walk(kids[i], depth + 1);
        }
        walk(root, 0);
        return out;
      }
      function clientCoord(d) { return mj.designToClient(d.x, d.y); }
      function actNode(action, node, label, extra) {
        const d = mj.globalCenter(node);
        const o = { action, label, button_name: node.name || null, client: clientCoord(d) };
        if (extra) o.extra = extra;
        return o;
      }
      function actXY(action, design, label, extra) {
        const o = { action, label, client: clientCoord(design) };
        if (extra) o.extra = extra;
        return o;
      }
      function tileStr(v) {
        if (!v) return null;
        // Use Mahjong Soul's canonical Tile.val.toString() — it knows the
        // internal `type` encoding (which is NOT `0=m, 1=p, 2=s, 3=z` —
        // hand-mapping `['m','p','s','z'][v.type]` mis-classified pin as
        // man on some builds). toString() returns e.g. "5p" / "3z" / "0m"
        // (Tenhou-style: "0m"/"0p"/"0s" = red five). We normalize red
        // fives to our "5m*"/"5p*"/"5s*" form for downstream consistency.
        // Accepts either a tile-wrapping object (has .val), a val object,
        // or a string already in tile form.
        let val = v;
        if (typeof val === 'object' && val.val) val = val.val;
        try {
          if (val && typeof val.toString === 'function') {
            const s = val.toString();
            if (typeof s === 'string' && /^[0-9][mpsz]$/.test(s)) {
              const digit = s.charAt(0);
              const suit = s.charAt(1);
              if (digit === '0' && suit !== 'z') return '5' + suit + '*';
              return s;
            }
          }
        } catch (e) {}
        return null;
      }

      const popViews = visibleNodes((n) => /^pop_/.test(n.name || ''));
      const gameendRoots = visibleNodes((n) => n.name === 'gameend');
      const containerCR = visibleNodes((n) => n.name === 'container_create_room');
      const afkNodes = visibleNodes((n) => typeof n.text === 'string' && /^I'?m back$/i.test(n.text));
      // Root-level confirm dialog: e.g. "Do you wish to leave this room?".
      // Recognized by btn_confirm + btn_cancel both direct children of root.
      const rootConfirm = visibleNodes((n) => n.name === 'btn_confirm' && n.mouseEnabled && n.parent && n.parent.name === 'root');
      const rootCancel = visibleNodes((n) => n.name === 'btn_cancel' && n.mouseEnabled && n.parent && n.parent.name === 'root');
      let modal = null;
      if (afkNodes.length) modal = { kind: 'afk', node: afkNodes[0] };
      else if (gameendRoots.length) modal = { kind: 'gameend', node: gameendRoots[0] };
      else if (containerCR.length) modal = { kind: 'create_room_dialog', node: containerCR[0] };
      else if (rootConfirm.length && rootCancel.length) modal = { kind: 'confirm_dialog', confirm: rootConfirm[0], cancel: rootCancel[0] };
      else if (popViews.length) modal = { kind: 'pop', node: popViews[popViews.length - 1] };

      let scene = 'unknown';
      if (!g.logined) scene = 'login';
      else if (gameendRoots.length) scene = 'match_end';
      else if (g.ingame) scene = 'match';
      else if (visibleNodes((n) => n.name === 'page_friend').length) scene = 'friendly_landing';
      else if (containerCR.length) scene = 'create_room_dialog';
      else if (
        visibleNodes((n) => n.name === 'btn_start' && n.parent && n.parent.name === 'root' && n.mouseEnabled).length
        || visibleNodes((n) => n.name === 'btn_suit' && n.parent && n.parent.name === 'root' && n.mouseEnabled).length
      ) scene = 'room_lobby';
      else if (g._current_scene === g._scene_lobby) scene = 'main_lobby';
      else scene = 'transition';

      let O = null;
      try {
        const h = game.MJNetMgr.Inst.netMJ.notifyHander.handlers['.lq.ActionPrototype'];
        if (h && h['0']) O = h['0'].caller;
      } catch (e) {}
      if (O) window.__mj.match = O;

      let matchState = null;
      if (O && (scene === 'match' || scene === 'match_end')) {
        const me = O.mainrole;
        const hand = me && Array.isArray(me.hand) ? me.hand.map(t => tileStr(t.val)) : null;
        const players = Array.isArray(O.players) ? O.players : [];
        // Mahjong Soul indexes `O.players[]` by LOCAL position (0=me,
        // 1=shimocha, 2=toimen, 3=kamicha) but `O.seat` is the SERVER
        // seat (E/S/W/N = 0..3). Find me by reference so per-seat arrays
        // (melds/discards/liqi/scores) and my_seat use the same indexing.
        let my_local = 0;
        if (me) {
          for (let i = 0; i < players.length; i++) {
            if (players[i] === me) { my_local = i; break; }
          }
        }
        const scores = [], melds = [], discards = [], liqi = [];
        for (let i = 0; i < players.length; i++) {
          const p = players[i];
          scores.push(p && typeof p.score === 'number' ? p.score : null);
          const mc = p && p.container_ming;
          if (mc && Array.isArray(mc.mings)) {
            const blocks = [];
            for (const meld of mc.mings) {
              const tiles = [];
              if (Array.isArray(meld.pais)) for (const t of meld.pais) tiles.push(tileStr(t.val || t));
              blocks.push({ type: meld.type, tiles });
            }
            melds.push(blocks);
          } else melds.push([]);
          const qc = p && p.container_qipai;
          if (qc && Array.isArray(qc.pais)) {
            // Mahjong Soul splits a player's discard pile across two
            // fields: `pais` holds every prior discard, and `last_pai`
            // holds the MOST RECENT discard (with `last_pai_count > 0`).
            // When the player discards again, the old `last_pai` rolls
            // into `pais`. Concatenate them to get the full pile.
            const tiles = qc.pais.map(t => tileStr(t.val || t));
            if (qc.last_pai_count > 0 && qc.last_pai) {
              const lt = tileStr(qc.last_pai.val || qc.last_pai);
              if (lt) tiles.push(lt);
            }
            discards.push(tiles);
          } else discards.push([]);
          liqi.push(!!(p && p.lichi));
        }
        // `O.lastpai_seat` is the SERVER seat of the discarder; translate
        // back to local position so it indexes consistently with our
        // arrays. The relation server_seat ↔ local_position is:
        //   local = (server_seat - my_server_seat + N) % N
        // We have my_server_seat = O.seat and my_local known, so:
        let last_discard = null;
        if (O.lastqipai && O.lastqipai.val) {
          const n = players.length || 4;
          const myServer = typeof O.seat === 'number' ? O.seat : 0;
          const srvDiscarder = typeof O.lastpai_seat === 'number' ? O.lastpai_seat : 0;
          const localDiscarder = ((srvDiscarder - myServer + n) % n + my_local) % n;
          last_discard = {
            seat: localDiscarder,
            tile: tileStr(O.lastqipai.val),
            is_moqie: !!O.lastqipai.ismoqie,
          };
        }
        matchState = {
          my_seat: my_local,
          my_server_seat: typeof O.seat === 'number' ? O.seat : null,
          scores,
          chang: O.index_change,
          ju: O.index_ju,
          ben: O.index_ben,
          left_tile_count: O.left_tile_count,
          dora_indicators: Array.isArray(O.dora) ? O.dora.map(d => tileStr(d)) : [],
          hand,
          melds,
          discards,
          liqi,
          last_discard,
          can_discard: !!(me && me.can_discard),
        };
      }

      let needs = false;
      let actionable = { kind: null, options: [] };

      if (modal && modal.kind === 'afk') {
        needs = true; actionable.kind = 'afk';
        actionable.options.push(actNode('dismiss_afk', modal.node, 'Dismiss AFK'));
      } else if (modal && modal.kind === 'confirm_dialog') {
        needs = true; actionable.kind = 'confirm_dialog';
        // Find a nearby question text for the agent.
        let question = '';
        const allText = visibleNodes((n) => typeof n.text === 'string' && n.text && n.text.length < 200 && !/^btn_/.test(n.name || ''));
        for (const t of allText) {
          if (/\?$/.test(t.text) || /wish|leave|surrender|quit|confirm/i.test(t.text)) { question = t.text; break; }
        }
        actionable.options.push(actNode('confirm', modal.confirm, 'Confirm: ' + question));
        actionable.options.push(actNode('cancel', modal.cancel, 'Cancel: ' + question));
      } else if (modal && modal.kind === 'gameend') {
        needs = true;
        const overlay = visibleNodes((n) => n.name === 'btn_click' && (n.width || 0) > 1500 && n.mouseEnabled);
        if (overlay.length) {
          actionable.kind = 'gameend_dismiss';
          actionable.options.push(actXY('dismiss_gameend_overlay', { x: 1745, y: 990 }, 'Dismiss gameend overlay'));
        } else {
          actionable.kind = 'reward_confirm';
          const btns = visibleNodes((n) => /^(btn_confirm|btn_next|btn_close|btn_finish)$/.test(n.name || '') && n.mouseEnabled);
          for (const b of btns) actionable.options.push(actNode('confirm_post_match', b, b.name));
          if (!btns.length) {
            const txt = visibleNodes((n) => typeof n.text === 'string' && /^Confirm$/.test(n.text));
            for (const t of txt) actionable.options.push(actNode('confirm_post_match', t, 'Confirm'));
          }
        }
      } else if (modal && (modal.kind === 'pop' || modal.kind === 'create_room_dialog')) {
        needs = true; actionable.kind = 'modal_close';
        const inside = descendantsOf(modal.node, (n) => /^btn_/.test(n.name || '') && n.mouseEnabled && n.localToGlobal);
        for (const b of inside) {
          const nm = (b.name || '').toLowerCase();
          let act = 'click_modal_button';
          if (/close|cancel|back|quxiao/.test(nm)) act = 'close_modal';
          else if (/confirm|ok|yes|create|enter|start/.test(nm)) act = 'confirm_modal';
          actionable.options.push(actNode(act, b, b.name));
        }
        // For Create Room: read settings from the canonical
        // `uiscript.UI_Create_Room.Inst.allLines[]` source. Each "line"
        // with a tabGroup is a one-of-N radio. Hidden advanced toggles
        // appear here too — they're just below the scrollable viewport.
        if (modal.kind === 'create_room_dialog') {
          const ui = window.uiscript && window.uiscript.UI_Create_Room && window.uiscript.UI_Create_Room.Inst;
          if (ui && Array.isArray(ui.allLines)) {
            function findText(node){const stk=[node];let cnt=0;while(stk.length&&cnt++<50){const c=stk.pop();if(c&&typeof c.text==='string'&&c.text)return c.text;const k=(c&&(c._childs||c._children))||[];for(const x of k)stk.push(x);}return '';}
            const radioLines = ui.allLines.filter(L => L && L.tabGroup);
            const groups = [];
            for (let gi = 0; gi < radioLines.length; gi++) {
              const L = radioLines[gi];
              const tmpls = (L.toggleObjs && L.toggleObjs.length)
                ? L.toggleObjs
                : ((L.toggleParent && (L.toggleParent._childs || L.toggleParent._children) || []).filter(c => c.name === 'template').slice(1));
              const labels = tmpls.map(t => findText(t));
              const selIdx = (L.tabGroup && typeof L.tabGroup.selectedIndex === 'number') ? L.tabGroup.selectedIndex : -1;
              groups.push({
                group_id: gi,
                is_advance: !!L.isAdvanceSetting,
                options: labels.map((lbl, i) => ({ label: lbl, selected: i === selIdx })),
                selected_index: selIdx,
                selected_label: (selIdx >= 0 && selIdx < labels.length) ? labels[selIdx] : null,
              });
            }
            actionable.room_settings = { groups };
            // Surface one actionable option per (group, non-selected) option.
            for (const g of groups) {
              for (let i = 0; i < g.options.length; i++) {
                if (i === g.selected_index) continue;
                actionable.options.push({
                  action: 'set_room_setting',
                  label: 'Group ' + g.group_id + ' → ' + g.options[i].label,
                  extra: { group_id: g.group_id, option_index: i, option_label: g.options[i].label },
                });
              }
            }
          }
        }
      }else if (scene === 'match' && O) {
        const callBtns = visibleNodes((n) =>
          /^btn_(chi|chii|peng|pon|gang|kan|minkan|ankan|lizhi|liqi|riichi|hu|ron|zimo|tsumo|babei|kita|quxiao|pass|cancel|skip)$/i.test(n.name || '')
          && n.mouseEnabled
          && n.parent && /^container_btns?$/.test(n.parent.name || ''));
        // Classify each visible button. Two distinct modes:
        //
        //   (A) `can_discard === true`: it's the player's own turn, the
        //       buttons are POST-DRAW SELF-ACTIONS (riichi, tsumo,
        //       ankan, chakan, kita). The hand tiles ARE ALSO
        //       discardable. Emit kind='discard' with hand-tile options
        //       AND the special-action options merged in.
        //
        //   (B) `can_discard === false`: an opponent just discarded;
        //       the buttons are CALL RESPONSES (chi, pon, kan_open,
        //       ron). Emit kind='call_window' with those + pass.
        //
        // The previous logic short-circuited to call_window whenever
        // ANY of these buttons were visible, which dropped the hand
        // tiles on a riichi prompt and confused the executor.
        function classifyBtn(b) {
          const nm = (b.name || '').toLowerCase();
          if (/chi/.test(nm)) return 'chi';
          if (/peng|pon/.test(nm)) return 'pon';
          if (/gang|kan/.test(nm)) return 'kan';
          if (/lizhi|liqi|riichi/.test(nm)) return 'lizhi';
          if (/zimo|tsumo/.test(nm)) return 'zimo';
          if (/hu|ron/.test(nm)) return 'hu';
          if (/babei|kita/.test(nm)) return 'kita';
          if (/quxiao|cancel|pass|skip/.test(nm)) return 'pass';
          return null;
        }
        // Pull the call-combination data either way; the UI panel
        // exposes it consistently as long as a call window is open.
        function attachCombinations(target) {
          try {
            const cp = window.uiscript && window.uiscript.UI_ChiPengHu
              && window.uiscript.UI_ChiPengHu.Inst;
            if (cp && cp._data) {
              if (Array.isArray(cp._data.chi))  target.chi_combinations  = cp._data.chi.slice();
              if (Array.isArray(cp._data.peng)) target.pon_combinations  = cp._data.peng.slice();
              if (Array.isArray(cp._data.gang)) target.kan_combinations  = cp._data.gang.slice();
              if (cp._data.hu  !== undefined)   target.hu_combinations   = cp._data.hu;
              if (cp._data.liqi !== undefined)  target.liqi_combinations = cp._data.liqi;
            }
          } catch (e) {}
        }

        if (matchState && matchState.can_discard) {
          needs = true; actionable.kind = 'discard';
          if (callBtns.length) attachCombinations(actionable);
          // Pre-compute kan subtype options for own-turn. The Mahjong
          // Soul UI uses a single "btn_gang" button regardless of
          // whether the player has ankan (closed kan from drawn or
          // hand quad) or chakan (added kan onto an existing open
          // pon). The wire `type` differs: 4 for ankan, 6 for chakan
          // (5 is minkan from an opponent's discard, which CANNOT
          // happen on own-turn — passing type=5 here silently locks
          // up the round).
          //
          // Distinguish per kan_combinations[] tile by checking
          // whether the player already has an open pon of that tile.
          // We do this by tile content (not `meld.type`, whose
          // numeric encoding has varied across mjcore builds):
          // a pon's `pais` is exactly 3 IDENTICAL tiles, whereas
          // a chi has 3 differing tiles and a kan has 4 tiles.
          const myMelds = (matchState.melds && matchState.melds[matchState.my_seat]) || [];
          function normTile(t) {
            if (!t || typeof t !== 'string') return t;
            return t.replace(/\*$/, '').replace(/^0([mps])$/, '5$1');
          }
          function ponTiles() {
            const out = {};
            for (const m of myMelds) {
              if (!m || !Array.isArray(m.tiles) || m.tiles.length !== 3) continue;
              const a = normTile(m.tiles[0]);
              const b = normTile(m.tiles[1]);
              const c = normTile(m.tiles[2]);
              if (a && a === b && b === c) out[a] = true;
            }
            return out;
          }
          function firstTileOf(combo) {
            if (!combo) return null;
            return normTile(String(combo).split('|')[0] || '');
          }
          const pons = ponTiles();
          let kanOpts = [];
          if (Array.isArray(actionable.kan_combinations) && actionable.kan_combinations.length) {
            for (const combo of actionable.kan_combinations) {
              const tile = firstTileOf(combo);
              const subtype = pons[tile] ? 'kan_added' : 'kan_closed';
              kanOpts.push({ tile, subtype, combo });
            }
          }
          // Surface any post-draw self-action buttons FIRST so they
          // show up at the top of the option list.
          for (const b of callBtns) {
            const act = classifyBtn(b);
            if (act === 'lizhi' || act === 'zimo' || act === 'kita') {
              actionable.options.push(actNode(act, b, b.name));
            } else if (act === 'kan') {
              if (kanOpts.length) {
                for (const k of kanOpts) {
                  actionable.options.push(actNode('kan', b, b.name,
                    { subtype: k.subtype, tile: k.tile, combination: k.combo }));
                }
              } else {
                // No combinations data — emit a single closed-kan
                // option (most common own-turn case) so the executor
                // doesn't fall back to kan_open.
                actionable.options.push(actNode('kan', b, b.name,
                  { subtype: 'kan_closed' }));
              }
            }
          }
          // Then one option per hand tile.
          for (let i = 0; i < matchState.hand.length; i++) {
            actionable.options.push({ action: 'discard', tile: matchState.hand[i], slot: i });
          }
        } else if (callBtns.length) {
          needs = true; actionable.kind = 'call_window';
          attachCombinations(actionable);
          for (const b of callBtns) {
            const act = classifyBtn(b) || 'pass';
            actionable.options.push(actNode(act, b, b.name));
          }
        }
      } else if (scene === 'main_lobby' || scene === 'friendly_landing' || scene === 'room_lobby') {
        needs = true; actionable.kind = 'lobby_navigation';
        if (scene === 'main_lobby') {
          const modes = visibleNodes((n) => /^btn_(yibanchang|dajiangsai|yourenfang)$/.test(n.name || '') && n.parent && n.parent.name === 'page0' && n.mouseEnabled);
          for (const b of modes) actionable.options.push(actNode('click_button', b, b.name));
          const aux = visibleNodes((n) => /^btn_(set|help|mail|achievement|camera|xinshouyindao|qiri|roleset)$/.test(n.name || '') && n.mouseEnabled);
          for (const b of aux) actionable.options.push(actNode('click_button', b, b.name));
        } else if (scene === 'friendly_landing') {
          const cards = visibleNodes((n) => /^btn[01]$/.test(n.name || '') && n.mouseEnabled).filter((n) => {
            let cur = n.parent; while (cur) { if (cur.name === 'page_friend') return true; cur = cur.parent; } return false;
          });
          for (const c of cards) actionable.options.push(actNode(c.name === 'btn0' ? 'open_create_room' : 'open_join_room', c, c.name));
          const back = visibleNodes((n) => n.name === 'btn_back' && n.mouseEnabled && n.parent && n.parent.name === 'container_title');
          for (const b of back) actionable.options.push(actNode('back', b, 'btn_back'));
        } else if (scene === 'room_lobby') {
          // Read canonical room state from UI_WaitingRoom.Inst.
          const wr = window.uiscript && window.uiscript.UI_WaitingRoom && window.uiscript.UI_WaitingRoom.Inst;
          const myAccountId = g.account_id;
          let room = null;
          if (wr) {
            const seats = (wr.players || []).map((p, i) => ({
              seat: i,
              account_id: p ? p.account_id : 0,
              nickname: p ? p.nickname : '',
              is_me: !!(p && p.account_id && p.account_id === myAccountId),
              is_empty: !p || p.account_id === 0,
              is_ai: !!(p && p.category === 1 && p.account_id !== myAccountId && p.account_id !== 0)
                || !!(p && p.category === 2),
              ready: !!(p && p.ready),
            }));
            const filled = seats.filter(s => !s.is_empty).length;
            const all_ready = seats.every(s => s.is_empty || s.ready);
            room = {
              room_id: wr.room_id,
              owner_id: wr.owner_id,
              is_host: wr.owner_id === myAccountId,
              max_player_count: wr.max_player_count,
              seats,
              seats_filled: filled,
              seats_open: wr.max_player_count - filled,
              all_ready,
              mode: wr.room_mode || null,
              public_live: !!wr.public_live,
            };
          }
          actionable.room = room;
          const start = visibleNodes((n) => n.name === 'btn_start' && n.parent && n.parent.name === 'root' && n.mouseEnabled);
          const leave = visibleNodes((n) => n.name === 'btn_leave' && n.parent && n.parent.name === 'top' && n.mouseEnabled);
          const suit = visibleNodes((n) => n.name === 'btn_suit' && n.parent && n.parent.name === 'root' && n.mouseEnabled);
          for (const b of start) actionable.options.push(actNode('start_match', b, 'Start the match (host)'));
          for (const b of leave) actionable.options.push(actNode('leave_room', b, 'Leave the room'));
          for (const b of suit) actionable.options.push(actNode('open_character_panel', b, 'Open character/skin panel'));
          // Per-seat add-AI buttons. Each seat object exposes a named
          // `btn_add_robot` field (the underlying Laya node is `ai_btn`).
          // It's NOT a direct child of the seat node in the display tree.
          if (room && room.is_host) {
            for (const s of room.seats) {
              if (!s.is_empty) continue;
              const seatNode = wr.playerSeats && wr.playerSeats[s.seat];
              if (!seatNode || !seatNode.btn_add_robot) continue;
              const aiBtn = seatNode.btn_add_robot;
              if (!aiBtn.visible || !aiBtn.mouseEnabled || !chainVisible(aiBtn)) continue;
              actionable.options.push(actNode('add_ai', aiBtn, 'Add AI to seat ' + s.seat, { seat: s.seat }));
            }
          }
        }
      } else if (scene === 'login') {
        needs = true; actionable.kind = 'login';
        actionable.options.push({ action: 'human_login' });
      }

      // ---------------- meta_actions ----------------
      // Always-available out-of-flow buttons that the agent can choose to
      // press regardless of what the game is currently demanding. These
      // never set `needs_my_action` on their own; they appear so the agent
      // never has to probe the scene graph for "exit" or "settings".
      const meta_actions = [];
      if (scene === 'match' && O) {
        const leave = visibleNodes((n) => n.name === 'btn_leave' && n.mouseEnabled && n.parent && n.parent.name === 'container_righttop');
        const settings = visibleNodes((n) => n.name === 'btn_set' && n.mouseEnabled && n.parent && n.parent.name === 'container_righttop');
        for (const b of leave) meta_actions.push(actNode('leave_match', b, 'Open leave-match confirm dialog'));
        for (const b of settings) meta_actions.push(actNode('open_settings', b, 'Open settings'));
      }

      const account = {
        logined: !!g.logined,
        name: (g.account_data && g.account_data.nickname) || g.player_name || '',
        id: g.account_id !== undefined ? g.account_id : -1,
      };

      return {
        ok: true,
        scene,
        modal: modal ? { kind: modal.kind, name: modal.node && modal.node.name || null } : null,
        needs_my_action: needs,
        actionable,
        room_settings: actionable.room_settings || null,
        room: actionable.room || null,
        meta_actions,
        account,
        match: matchState,
        event_seq: eventSeq,
      };
    };

    return { ok: true, installed: true };
  });
  return installed;
})
