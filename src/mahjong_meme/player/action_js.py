"""JS snippets used by the executor â€” all direct wire-level API calls.

After investigating the Mahjong Soul match controller, we found that
**every** in-match decision (not just discards) can be sent via the
WebSocket sender ``app.NetAgent.sendReq2MJ`` â€” no DOM clicks needed.

Two wire methods:

- ``.lq.FastTest.inputOperation``  â€” discard / riichi / tsumo / ankan
- ``.lq.FastTest.inputChiPengGang`` â€” chi / pon / kan / ron / pass-on-discard

Operation type enum (``mjcore.E_PlayOperation``):
    1 dapai     5 ming_gang   9 rong
    2 eat       6 add_gang   11 babei
    3 peng      7 liqi
    4 an_gang   8 zimo
"""
from __future__ import annotations


# --------------------------------------------------------------------------
# Discard via direct controller API (was already click-free).
# --------------------------------------------------------------------------

# Args: { tile: "5m*" }
# Returns: { ok: bool, reason?: string }
DISCARD_JS = r"""
(args) => {
  function getMatchCtrl() {
    try {
      const h = game.MJNetMgr.Inst.netMJ.notifyHander.handlers['.lq.ActionPrototype'];
      return h && h['0'] && h['0'].caller;
    } catch (e) { return null; }
  }
  try {
    const O = getMatchCtrl();
    if (!O || !O.mainrole) {
      return { ok: false, reason: 'match_or_mainrole_missing' };
    }
    const me = O.mainrole;
    if (!me.can_discard) {
      return { ok: false, reason: 'cannot_discard_right_now' };
    }
    if (!me.hand || !me.hand.length) {
      return { ok: false, reason: 'hand_empty' };
    }
    function norm(s) {
      if (!s) return s;
      if (s.length === 2 && s[0] === '0' && 'mps'.includes(s[1])) {
        return '5' + s[1] + '*';
      }
      return s;
    }
    const want = norm(args.tile);
    let target = null;
    for (let i = 0; i < me.hand.length; i++) {
      const t = me.hand[i];
      if (!t || !t.val) continue;
      let s = '';
      try { s = t.val.toString(); } catch (e) { continue; }
      if (s.length === 2 && s[0] === '0' && 'mps'.includes(s[1])) {
        s = '5' + s[1] + '*';
      }
      if (s === want) { target = t; break; }
    }
    if (target === null) {
      return { ok: false, reason: 'tile_not_in_hand',
               want: want, hand: me.hand.map((t) => t && t.val ? t.val.toString() : '?') };
    }
    const isDrawn = (target === me.last_tile);
    me.setChoosePai(target, isDrawn);
    me.DoDiscardTile();
    return { ok: true, tile: want, isDrawn: isDrawn };
  } catch (e) {
    return { ok: false, reason: 'exception', message: String(e && e.message || e) };
  }
}
"""


# --------------------------------------------------------------------------
# Chi/Pon/Kan/Ron â€” direct wire call via inputChiPengGang.
# --------------------------------------------------------------------------
#
# Args:
#   { type: "chi" | "pon" | "kan_open" | "kan_added" | "ron",
#     partner_tiles?: ["3p","4p"],   // chi only; matches against
#                                    // mainrole.operation.operation_list
#     tile?: "5m"                    // for kan, the tile to declare on
#   }
# Returns: { ok: bool, reason?: string, type: int, index: int }
CALL_JS = r"""
(args) => {
  function getMatchCtrl() {
    try {
      const h = game.MJNetMgr.Inst.netMJ.notifyHander.handlers['.lq.ActionPrototype'];
      return h && h['0'] && h['0'].caller;
    } catch (e) { return null; }
  }
  try {
    const O = getMatchCtrl();
    if (!O) return { ok: false, reason: 'match_missing' };

    const TYPE_BY_NAME = {
      'chi': 2, 'eat': 2,
      'pon': 3, 'peng': 3,
      'an_gang': 4, 'kan_closed': 4,
      'ming_gang': 5, 'kan_open': 5,
      'add_gang': 6, 'kan_added': 6,
      'liqi': 7, 'riichi': 7,
      'zimo': 8, 'tsumo': 8,
      'rong': 9, 'ron': 9, 'hu': 9,
      'babei': 11, 'kita': 11,
    };
    const TYPE_TO_KEY = {
      2: 'chi', 3: 'peng', 4: 'gang', 5: 'gang', 6: 'gang',
      7: 'liqi', 8: 'zimo', 9: 'hu', 11: 'babei',
    };
    const wantType = TYPE_BY_NAME[(args.type || '').toLowerCase()];
    if (wantType === undefined) {
      return { ok: false, reason: 'unknown_call_type', type: args.type };
    }

    function normRank(s) {
      if (!s) return s;
      if (s.length === 2 && s[0] === '0' && 'mps'.includes(s[1])) {
        return '5' + s[1];
      }
      return s.endsWith('*') ? s.slice(0, -1) : s;
    }

    // Resolve the legal combination list. Prefer the caller-supplied
    // combinations (from state.actionable.chi/pon/kan_combinations) so we
    // don't depend on the UI panel being up at the moment of dispatch.
    let combos = Array.isArray(args.combinations) ? args.combinations.slice() : null;
    if (!combos) {
      try {
        const ui = uiscript.UI_ChiPengHu && uiscript.UI_ChiPengHu.Inst;
        if (ui && ui._data) {
          const key = TYPE_TO_KEY[wantType];
          if (key && Array.isArray(ui._data[key])) combos = ui._data[key].slice();
        }
      } catch (e) {}
    }
    combos = combos || [];

    let subIndex = 0;
    let combination = null;

    if (wantType === 2 && args.partner_tiles && args.partner_tiles.length) {
      const want = args.partner_tiles
        .map(normRank).filter(Boolean).sort().join('|');
      let found = -1;
      for (let j = 0; j < combos.length; j++) {
        const parts = String(combos[j]).split('|').map(normRank).sort().join('|');
        if (parts === want) { found = j; break; }
      }
      if (found < 0) {
        if (combos.length === 1) {
          subIndex = 0;
          combination = combos[0];
        } else if (combos.length === 0) {
          // No data — assume index 0 (the click would pick the same).
          subIndex = 0;
        } else {
          return { ok: false, reason: 'no_matching_chi_combo',
                    want: want, combos: combos };
        }
      } else {
        subIndex = found;
        combination = combos[found];
      }
    } else if (wantType === 4 || wantType === 5 || wantType === 6) {
      const wantTile = normRank(args.tile);
      let found = 0;
      if (wantTile && combos.length > 1) {
        for (let j = 0; j < combos.length; j++) {
          const c = String(combos[j]).split('|').map(normRank);
          if (c[0] === wantTile) { found = j; break; }
        }
      }
      subIndex = found;
      combination = combos[found] || null;
    } else {
      subIndex = 0;
      combination = combos[0] || null;
    }

    const body = { type: wantType, index: subIndex, timeuse: 1 };
    // Ankan (type 4) is dispatched via inputOperation (own-turn self
    // action), while chakan/minkan/chi/pon/ron go via inputChiPengGang
    // (response to or after a discard). Mahjong Soul rejects ankan
    // sent over inputChiPengGang.
    const method = (wantType === 4) ? 'inputOperation' : 'inputChiPengGang';
    app.NetAgent.sendReq2MJ('FastTest', method, body, function (resp) {});
    try { O.ClearOperationShow && O.ClearOperationShow(); } catch (e) {}
    return { ok: true, type: wantType, index: subIndex,
              combination: combination,
              method: method,
              source: args.combinations ? 'state_actionable'
                : (combos.length ? 'UI_ChiPengHu._data' : 'fallback_zero') };
  } catch (e) {
    return { ok: false, reason: 'exception', message: String(e && e.message || e) };
  }
}
"""


# --------------------------------------------------------------------------
# Pass on an opponent's discard (call window cancel).
# --------------------------------------------------------------------------
PASS_CALL_JS = r"""
() => {
  function getMatchCtrl() {
    try {
      const h = game.MJNetMgr.Inst.netMJ.notifyHander.handlers['.lq.ActionPrototype'];
      return h && h['0'] && h['0'].caller;
    } catch (e) { return null; }
  }
  try {
    const O = getMatchCtrl();
    if (!O) return { ok: false, reason: 'match_missing' };
    app.NetAgent.sendReq2MJ('FastTest', 'inputChiPengGang',
      { cancel_operation: true, timeuse: 1 },
      function (resp) {});
    try { O.ClearOperationShow && O.ClearOperationShow(); } catch (e) {}
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: 'exception', message: String(e && e.message || e) };
  }
}
"""


# --------------------------------------------------------------------------
# Riichi declaration (inputOperation type=liqi).
# --------------------------------------------------------------------------
# Args: { tile: "5m*" } -- the tile being discarded as the riichi tile.
RIICHI_JS = r"""
(args) => {
  function getMatchCtrl() {
    try {
      const h = game.MJNetMgr.Inst.netMJ.notifyHander.handlers['.lq.ActionPrototype'];
      return h && h['0'] && h['0'].caller;
    } catch (e) { return null; }
  }
  try {
    const O = getMatchCtrl();
    if (!O || !O.mainrole) return { ok: false, reason: 'match_missing' };
    const me = O.mainrole;
    function norm(s) {
      if (!s) return s;
      if (s.length === 2 && s[0] === '0' && 'mps'.includes(s[1])) {
        return '5' + s[1] + '*';
      }
      return s;
    }
    const want = norm(args.tile);
    let target = null;
    for (let i = 0; i < me.hand.length; i++) {
      const t = me.hand[i];
      if (!t || !t.val) continue;
      let s = '';
      try { s = t.val.toString(); } catch (e) { continue; }
      if (s.length === 2 && s[0] === '0' && 'mps'.includes(s[1])) {
        s = '5' + s[1] + '*';
      }
      if (s === want) { target = t; break; }
    }
    if (!target) return { ok: false, reason: 'tile_not_in_hand', want: want };
    const moqie = (target === me.last_tile);
    const ok = O.Action_LiQi(target.val, moqie, false);
    if (!ok) return { ok: false, reason: 'Action_LiQi_returned_false' };
    return { ok: true, tile: want, moqie: moqie };
  } catch (e) {
    return { ok: false, reason: 'exception', message: String(e && e.message || e) };
  }
}
"""


# --------------------------------------------------------------------------
# Win on own draw (tsumo) â€” inputOperation type=zimo.
# --------------------------------------------------------------------------
TSUMO_JS = r"""
() => {
  function getMatchCtrl() {
    try {
      const h = game.MJNetMgr.Inst.netMJ.notifyHander.handlers['.lq.ActionPrototype'];
      return h && h['0'] && h['0'].caller;
    } catch (e) { return null; }
  }
  try {
    const O = getMatchCtrl();
    if (!O) return { ok: false, reason: 'match_missing' };
    app.NetAgent.sendReq2MJ('FastTest', 'inputOperation',
      { type: 8, index: 0, timeuse: 1 },
      function (resp) {});
    try { O.ClearOperationShow && O.ClearOperationShow(); } catch (e) {}
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: 'exception', message: String(e && e.message || e) };
  }
}
"""


# --------------------------------------------------------------------------
# Kita (sanma north pull) â€” inputOperation type=babei.
# --------------------------------------------------------------------------
KITA_JS = r"""
() => {
  try {
    app.NetAgent.sendReq2MJ('FastTest', 'inputOperation',
      { type: 11, index: 0, timeuse: 1 },
      function (resp) {});
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: 'exception', message: String(e && e.message || e) };
  }
}
"""


# --------------------------------------------------------------------------
# Pass on own turn (when the only legal action is to do nothing â€” rare).
# --------------------------------------------------------------------------
PASS_OWN_JS = r"""
() => {
  try {
    app.NetAgent.sendReq2MJ('FastTest', 'inputOperation',
      { cancel_operation: true, timeuse: 1 },
      function (resp) {});
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: 'exception', message: String(e && e.message || e) };
  }
}
"""

