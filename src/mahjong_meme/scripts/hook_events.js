// MahjongSoul skill — install network event hook.
//
// Single arrow expression. Wrap with `() => (<body>)({})` for evaluate.
// Requires init.js.
//
// Patches the prototype of `MJNetMgr.Inst.netMJ`'s class so every outbound
// `sendRequest` and inbound `onRouteNotifyProto` is captured into a ring
// buffer at `window.__mj.events.buffer[]` and mirrored to the browser console
// as `[mj] dir name {summary}`. The hook covers BOTH route instances (lobby
// and mj) because they share the prototype.
//
// `app.NetAgent.sendReq2Lobby` is also wrapped so lobby-side requests that
// don't go through netMJ are still seen.
//
// Idempotent: a second call returns `{ ok: true, already: true }` and does
// nothing.
//
// Options:
//   { limit: 500,            // max events kept in the ring buffer
//     summaryDepth: 1,       // how deep to JSON-summarize non-Action bodies
//     console: true,         // mirror to console.log
//     summaryMaxLen: 800 }   // cap on JSON.stringify length per event
//
// Pre-login the inner classes may not exist yet; the hook installer
// auto-retries every 2 s until netMJ becomes reachable (max 20 min).
//
// Returns:
//   { ok: true, installed: { send_mj, recv_mj, send_lobby }, buffered: N }
//   { ok: false, reason: 'init_missing' }

(opts) => {
  if (!window.__mj || !window.__mj._installed) {
    return { ok: false, reason: 'init_missing' };
  }
  const o = opts || {};
  const limit = o.limit || 500;
  const summaryDepth = o.summaryDepth === undefined ? 1 : o.summaryDepth;
  const summaryMaxLen = o.summaryMaxLen || 800;
  const toConsole = o.console !== false;

  if (window.__mj._eventsHooked) {
    return { ok: true, already: true, buffered: __mj.events.buffer.length };
  }

  function summarize(obj, depth) {
    if (obj === null || obj === undefined) return obj;
    const t = typeof obj;
    if (t === 'string' || t === 'number' || t === 'boolean') return obj;
    if (obj instanceof Uint8Array || obj instanceof ArrayBuffer) return `<bytes:${obj.byteLength}>`;
    if (depth <= 0) return Array.isArray(obj) ? `[len ${obj.length}]` : `{${(obj.constructor && obj.constructor.name) || 'obj'}}`;
    if (Array.isArray(obj)) {
      const out = [];
      for (let i = 0; i < Math.min(obj.length, 20); i++) out.push(summarize(obj[i], depth - 1));
      if (obj.length > 20) out.push(`...+${obj.length - 20}`);
      return out;
    }
    if (t === 'object') {
      const out = {};
      let n = 0;
      for (const k in obj) {
        if (n++ >= 24) { out['...'] = true; break; }
        try { out[k] = summarize(obj[k], depth - 1); } catch (e) { out[k] = `<err:${e}>`; }
      }
      return out;
    }
    return null;
  }
  function safeJson(v) {
    try { const s = JSON.stringify(v); return s.length > summaryMaxLen ? s.slice(0, summaryMaxLen) + '...' : s; }
    catch (e) { return '<unstringifiable>'; }
  }

  // Decode an inner Mahjong Soul protobuf message (e.g. lq.ActionDealTile)
  // from raw bytes. Returns null if the proto isn't loaded yet or the bytes
  // are encrypted (opponents' draws often are).
  function tryDecode(typeFqn, bytes) {
    try {
      if (!window.net || !net.ProtobufManager) return null;
      const T = net.ProtobufManager.lookupType(typeFqn);
      if (!T) return null;
      const msg = T.decode(bytes);
      return T.toObject(msg, { defaults: true, longs: Number, bytes: Array });
    } catch (e) { return null; }
  }

  // The match server wraps every notify in lq.ActionPrototype: { name, step,
  // data: Uint8Array }. The `name` is e.g. 'ActionNewRound', and the data is
  // the actual encoded action body. Decode it inline so the agent doesn't
  // have to.
  function unwrapAction(body) {
    if (!body || typeof body.name !== 'string' || !body.data) return null;
    const decoded = tryDecode('lq.' + body.name, body.data);
    if (decoded) return { inner_name: body.name, step: body.step, action: decoded };
    return { inner_name: body.name, step: body.step, action: '<undecoded>' };
  }

  __mj.events = {
    seq: 0,
    buffer: [],
    enabled: true,
    push(ev) {
      ev.seq = ++this.seq;
      ev.t = Date.now();
      this.buffer.push(ev);
      while (this.buffer.length > limit) this.buffer.shift();
      if (toConsole && this.enabled) {
        try { console.log('[mj]', ev.dir, ev.name, ev.summary_json || ''); } catch (e) {}
      }
    },
    since(seq) { return this.buffer.filter((e) => e.seq > (seq || 0)); },
    clear() { this.buffer = []; this.seq = 0; },
    pause() { this.enabled = false; },
    resume() { this.enabled = true; },
  };

  function record(dir, name, body) {
    let summary;
    let displayName = String(name || '');
    if (dir === 'recv' && displayName === '.lq.ActionPrototype') {
      const u = unwrapAction(body);
      if (u) {
        displayName = '.lq.' + (u.inner_name || 'Action?');
        summary = summarize(u, 4);
      } else {
        summary = summarize(body, 1);
      }
    } else {
      summary = summarize(body, 2);
    }
    __mj.events.push({ dir, name: displayName, summary, summary_json: safeJson(summary) });
  }

  function hookFn(target, method, wrapper) {
    if (!target || typeof target[method] !== 'function') return false;
    const orig = target[method];
    if (orig.__mj_hooked) return true;
    const replacement = function () {
      try { wrapper.apply(this, arguments); } catch (e) {}
      return orig.apply(this, arguments);
    };
    replacement.__mj_hooked = true;
    replacement.__mj_orig = orig;
    target[method] = replacement;
    return true;
  }

  function attempt() {
    const status = { send_mj: false, recv_mj: false, send_lobby: false, classes_patched: 0 };

    // Collect every net-route class we can reach. They are minified to the
    // same constructor name ('v') but are different classes; each has its
    // own prototype, so we must patch each individually.
    const candidates = [];
    const seenProto = new Set();
    function addProto(proto) {
      if (!proto || seenProto.has(proto)) return;
      if (typeof proto.sendRequest !== 'function' && typeof proto.onRouteNotifyProto !== 'function') return;
      seenProto.add(proto);
      candidates.push(proto);
    }
    function add(obj) {
      if (!obj) return;
      addProto(obj.constructor && obj.constructor.prototype);
    }
    function addClass(cls) {
      if (typeof cls !== 'function') return;
      addProto(cls.prototype);
    }
    try {
      add(window.game && game.MJNetMgr && game.MJNetMgr.Inst && game.MJNetMgr.Inst.netMJ);
    } catch (e) {}
    try {
      if (window.net) {
        for (const k of Object.keys(net)) {
          const v = net[k];
          if (!v) continue;
          if (v.Inst) add(v.Inst);
          // Also try the class itself in case it's not a singleton.
          addClass(v);
        }
      }
    } catch (e) {}

    for (const P of candidates) {
      const a = hookFn(P, 'sendRequest', function (name, methodFqn, body, cb) {
        record('send', methodFqn || name, body);
        if (typeof cb === 'function' && !cb.__mj_wrapped) {
          const origCb = cb;
          const wrapped = function (err, rsp) {
            try { record('recv_rsp', methodFqn || name, rsp); } catch (e) {}
            return origCb.apply(this, arguments);
          };
          wrapped.__mj_wrapped = true;
          arguments[3] = wrapped;
        }
      });
      const b = hookFn(P, 'onRouteNotifyProto', function (route, name, body) {
        record('recv', name, body);
      });
      if (a || b) status.classes_patched++;
      status.send_mj = status.send_mj || a;
      status.recv_mj = status.recv_mj || b;
    }

    // Hook NetAgent statics for symmetry (lobby requests issued via NetAgent).
    if (window.app && app.NetAgent) {
      status.send_lobby = hookFn(app.NetAgent, 'sendReq2Lobby', function (name, methodFqn, body, cb) {
        record('send_lobby', methodFqn || name, body);
      });
    }

    return status;
  }

  const status = attempt();
  // Keep retrying for up to 20 minutes if netMJ isn't ready yet.
  const tStart = Date.now();
  const timer = setInterval(() => {
    const st = attempt();
    if ((st.send_mj && st.recv_mj) || Date.now() - tStart > 20 * 60 * 1000) {
      clearInterval(timer);
    }
  }, 2000);
  __mj._eventsHookTimer = timer;
  __mj._eventsHooked = true;

  return { ok: true, installed: status, buffered: __mj.events.buffer.length };
}
