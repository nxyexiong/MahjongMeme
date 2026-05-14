// MahjongSoul skill — login waiter.
//
// Single arrow expression. Playwright MCP's evaluate calls it with no args, so
// wrap to supply opts:
//
//   () => (<this file body>)({ timeoutMs: 600000 })
//
// Polls inside the page every 1s for up to `timeoutMs` (default 10 min) until
// the user logs in.
//
// Returns:
//   { ok: true,  nickname, account_id, scene }                on success
//   { ok: false, reason: 'timeout' | 'no_gamemgr', scene }    on failure
//
// The agent should call ask_user BEFORE invoking this script so the human
// knows they need to interact with the visible browser.

(opts) => {
  const o = opts || {};
  const timeoutMs = typeof o.timeoutMs === 'number' ? o.timeoutMs : 600000;
  const intervalMs = typeof o.intervalMs === 'number' ? o.intervalMs : 1000;
  const t0 = Date.now();

  return new Promise((resolve) => {
    function check() {
      const g = window.GameMgr && GameMgr.Inst;
      if (!g) {
        if (Date.now() - t0 > timeoutMs) {
          return resolve({ ok: false, reason: 'no_gamemgr', scene: 'unknown' });
        }
        return setTimeout(check, intervalMs);
      }
      if (g.logined) {
        return resolve({
          ok: true,
          nickname: g.player_name || null,
          account_id: g.account_id || null,
          scene: (window.__mj && __mj.scene && __mj.scene()) || 'lobby',
        });
      }
      if (Date.now() - t0 > timeoutMs) {
        return resolve({
          ok: false,
          reason: 'timeout',
          scene: (window.__mj && __mj.scene && __mj.scene()) || 'login',
        });
      }
      setTimeout(check, intervalMs);
    }
    check();
  });
}
