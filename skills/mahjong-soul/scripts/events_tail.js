// MahjongSoul skill — read recent events.
//
// Single arrow expression. Wrap with `() => (<body>)({ sinceSeq, max })`
// for evaluate. Requires hook_events.js was run first.
//
// Returns:
//   { ok: true, latest_seq: N, events: [{ seq, t, dir, name, summary }, ...] }
//   { ok: false, reason: 'hook_missing' }
//
// Typical poll loop in the agent:
//   sinceSeq = 0
//   loop:
//     r = events_tail.js({ sinceSeq, max: 100 })
//     for each ev in r.events: decide
//     sinceSeq = r.latest_seq
//     wait 2 seconds

(opts) => {
  const o = opts || {};
  if (!window.__mj || !window.__mj.events) {
    return { ok: false, reason: 'hook_missing' };
  }
  const since = o.sinceSeq || 0;
  const max = o.max || 100;
  const all = __mj.events.since(since);
  const events = all.length > max ? all.slice(-max) : all;
  return {
    ok: true,
    latest_seq: __mj.events.seq,
    truncated: all.length > max,
    events: events.map((e) => ({
      seq: e.seq,
      t: e.t,
      dir: e.dir,
      name: e.name,
      summary: e.summary,
    })),
  };
}
