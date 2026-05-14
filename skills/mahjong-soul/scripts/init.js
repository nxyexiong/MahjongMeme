// MahjongSoul skill — init helpers.
//
// This file is one arrow-function expression. Pass the entire file contents as
// the `function` argument of `playwright-browser_evaluate`. Idempotent: a second
// call returns 'already installed' and does nothing.
//
// Installs window.__mj with the primitives every other skill script uses.

() => {
  if (window.__mj && window.__mj._installed) return 'already installed';

  const designW = 1920;
  const designH = 1080;

  function canvas() {
    return document.getElementById('layaCanvas');
  }

  // Convert Laya design coords (1920x1080) to viewport (client) coords.
  function designToClient(x, y) {
    const c = canvas();
    if (!c) return null;
    const r = c.getBoundingClientRect();
    return {
      x: r.x + (x / designW) * r.width,
      y: r.y + (y / designH) * r.height,
    };
  }

  // Convert viewport coords back to Laya design coords (handy for screenshots).
  function clientToDesign(x, y) {
    const c = canvas();
    if (!c) return null;
    const r = c.getBoundingClientRect();
    return {
      x: ((x - r.x) / r.width) * designW,
      y: ((y - r.y) / r.height) * designH,
    };
  }

  // Walk a Laya display object and return the first descendant matching `pred`.
  function walk(root, pred, out, depth) {
    if (!root) return;
    if (depth === undefined) depth = 0;
    if (depth > 40) return;
    try { if (pred(root)) out.push(root); } catch (e) {}
    const kids = root._childs || root._children || [];
    for (let i = 0; i < kids.length; i++) walk(kids[i], pred, out, depth + 1);
  }

  // Find UI nodes under Laya.stage by predicate or name.
  function find(predOrName, max) {
    const out = [];
    const pred =
      typeof predOrName === 'string'
        ? (n) => n && n.name === predOrName
        : predOrName;
    walk(Laya.stage, pred, out);
    return max ? out.slice(0, max) : out;
  }

  // Compute a Laya display object's global (stage-space) center point.
  // Uses Laya's own localToGlobal to honor pivot/anchor/scale.
  function globalCenter(node) {
    if (!node || !node.localToGlobal) return null;
    const p = new Laya.Point((node.width || 0) / 2, (node.height || 0) / 2);
    const g = node.localToGlobal(p);
    return { x: g.x, y: g.y };
  }

  // Briefly summarize any object for cross-process inspection.
  function summarize(obj, maxKeys) {
    if (obj === null || obj === undefined) return obj;
    const t = typeof obj;
    if (t !== 'object' && t !== 'function') return obj;
    const r = { _kind: (obj.constructor && obj.constructor.name) || t };
    try {
      const keys = Object.keys(obj);
      r._keys = keys.slice(0, maxKeys || 40);
      if (keys.length > r._keys.length) r._truncated = keys.length;
    } catch (e) {
      r._err = String(e);
    }
    return r;
  }

  // High-level "where am I" guess. Cheap; refined further by inspect.js.
  function scene() {
    const g = window.GameMgr && GameMgr.Inst;
    if (!g) return 'unknown';
    if (!g.logined) return 'login';
    if (g.ingame) return 'match';
    if (g._current_scene === g._scene_lobby) return 'lobby';
    return 'transition';
  }

  // Dispatch a synthetic PointerEvent sequence to the canvas at viewport
  // coords. This works for Laya 2D UI (buttons, dialogs, lobby) but is
  // ignored by the 3D scene's raycaster — tile picks during a match WILL
  // NOT work via this path. For in-match actions use Playwright's native
  // mouse from `playwright-browser_run_code_unsafe`:
  //
  //   await page.mouse.move(x, y); await page.waitForTimeout(300);
  //   await page.mouse.down(); await page.waitForTimeout(150);
  //   await page.mouse.up();
  async function clickViewport(vx, vy, opts) {
    const c = canvas();
    if (!c) throw new Error('layaCanvas not found');
    const hold = (opts && opts.hold) || 120;
    const base = { bubbles: true, cancelable: true, composed: true, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1, clientX: vx, clientY: vy };
    c.dispatchEvent(new PointerEvent('pointerdown', base));
    c.dispatchEvent(new MouseEvent('mousedown', base));
    await new Promise((f) => setTimeout(f, hold));
    const up = { ...base, buttons: 0 };
    c.dispatchEvent(new PointerEvent('pointerup', up));
    c.dispatchEvent(new MouseEvent('mouseup', up));
    c.dispatchEvent(new MouseEvent('click', up));
    return { vx, vy };
  }

  // Click using Laya design coordinates.
  async function clickDesign(dx, dy, opts) {
    const p = designToClient(dx, dy);
    if (!p) throw new Error('cannot resolve canvas');
    return clickViewport(p.x, p.y, opts);
  }

  // Wait until predicate returns truthy, polling every `interval` ms.
  async function waitFor(pred, { timeout = 15000, interval = 250 } = {}) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      try {
        const v = pred();
        if (v) return v;
      } catch (e) {}
      await new Promise((f) => setTimeout(f, interval));
    }
    throw new Error('waitFor timed out');
  }

  window.__mj = {
    _installed: true,
    designW,
    designH,
    canvas,
    designToClient,
    clientToDesign,
    find,
    globalCenter,
    summarize,
    scene,
    clickViewport,
    clickDesign,
    waitFor,
  };
  return 'installed';
}
