// Parity verifier: runs the original Riichi-Trainer engine on a set of
// test hands and emits JSON expected values. Compare against the Python
// port via tools/check_parity.py.
//
// Run with: node tools/parity_export.js > tools/parity_expected.json
//
// We use a require hook to (a) strip image/css/svg imports the trainer's
// JS pulls in, and (b) transpile the trainer's ESM-style code to CJS via
// a minimal regex-based rewrite — avoids needing babel.

const path = require('path');
const Module = require('module');

const REPO = path.resolve(__dirname, '..');
const TRAINER_SRC = path.join(REPO, 'third_party', 'Riichi-Trainer', 'src');

require.extensions['.png'] = function (mod) { mod.exports = ''; };
require.extensions['.css'] = function (mod) { mod.exports = ''; };
require.extensions['.svg'] = function (mod) { mod.exports = ''; };

const origCompile = Module.prototype._compile;
Module.prototype._compile = function (content, filename) {
  if (filename.startsWith(TRAINER_SRC)) {
    content = transform(content);
  }
  return origCompile.call(this, content, filename);
};

function transform(src) {
  src = src.replace(
    /import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"];?/g,
    'const $1 = require("$2");'
  );
  src = src.replace(
    /import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"];?/g,
    'const {$1} = require("$2");'
  );
  src = src.replace(
    /import\s+(\w+)\s+from\s+['"]([^'"]+)['"];?/g,
    'const $1 = (require("$2").default || require("$2"));'
  );
  src = src.replace(
    /export\s+default\s+(\w+);?/g,
    'module.exports.default = $1;'
  );
  // export function/const/let/var name ... -> strip "export ", then
  // append module.exports.name = name at the end.
  const exported = [];
  src = src.replace(
    /export\s+(function|const|let|var)\s+(\w+)/g,
    (_, kw, name) => { exported.push(name); return `${kw} ${name}`; }
  );
  if (exported.length) {
    src += '\n' + exported.map(n => `module.exports.${n} = ${n};`).join('\n') + '\n';
  }
  return src;
}

const Shanten = require(path.join(TRAINER_SRC, 'scripts/ShantenCalculator.js'));
const Ukeire = require(path.join(TRAINER_SRC, 'scripts/UkeireCalculator.js'));
const Evals = require(path.join(TRAINER_SRC, 'scripts/Evaluations.js'));

const calculateMinimumShanten = Shanten.calculateMinimumShanten || Shanten.default;
const calculateStandardShanten = Shanten.calculateStandardShanten;
const calculateUkeire = Ukeire.calculateUkeire;
const calculateDiscardUkeire = Ukeire.calculateDiscardUkeire;
const evaluateBestDiscard = Evals.evaluateBestDiscard;

const ALL_TILES_REMAINING = [
  0,4,4,4,4,4,4,4,4,4,
  0,4,4,4,4,4,4,4,4,4,
  0,4,4,4,4,4,4,4,4,4,
  0,4,4,4,4,4,4,4,
];

function parseTile(name) {
  let s = name.trim();
  let red = false;
  if (s.endsWith('*')) { red = true; s = s.slice(0, -1); }
  if (s.length !== 2) throw new Error('bad tile ' + name);
  const v = parseInt(s[0]);
  const suit = s[1];
  const base = { m: 0, p: 10, s: 20, z: 30 }[suit];
  if (base === undefined) throw new Error('bad suit ' + name);
  if (suit === 'z') return 30 + v;
  if (red) { if (v !== 5) throw new Error('bad red ' + name); return base; }
  return base + v;
}

function tileCounts(tiles) {
  const c = new Array(38).fill(0);
  for (const t of tiles) c[parseTile(t)]++;
  return c;
}

function remainingFromVisible(visibleStrs, handStrs) {
  const v = new Array(38).fill(0);
  for (const t of visibleStrs) v[parseTile(t)]++;
  for (const t of handStrs) v[parseTile(t)]++;
  for (const i of [0, 10, 20]) { v[i + 5] += v[i]; v[i] = 0; }
  const r = new Array(38).fill(0);
  for (let i = 0; i < 38; i++) r[i] = Math.max(0, ALL_TILES_REMAINING[i] - v[i]);
  return r;
}

const CASES = [
  {
    name: 'tenpai_shanpon',
    hand: ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '1z', '1z', '2z', '2z'],
    visible: [],
  },
  {
    name: 'discard_basic',
    hand: ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '1z', '1z', '5m', '5m*', '3z'],
    visible: [],
  },
  {
    name: 'chiitoi_1shanten',
    hand: ['1m', '1m', '3m', '3m', '5p', '5p', '7p', '7p', '2s', '2s', '4s', '9s', '9s', '3z'],
    visible: [],
  },
  {
    name: 'kokushi_1shanten',
    hand: ['1m', '9m', '1p', '9p', '1s', '9s', '1z', '2z', '3z', '4z', '5z', '6z', '7z', '5m'],
    visible: [],
  },
  {
    name: 'complete_standard',
    hand: ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '1z', '1z', '2z', '2z', '2z'],
    visible: [],
  },
  {
    name: 'limited_ukeire',
    hand: ['1m', '2m', '3m', '4p', '5p', '6p', '7s', '8s', '9s', '1z', '1z', '5m', '5m', '3m'],
    visible: ['3z', '3z', '3z', '3z'],
  },
];

const out = [];
for (const c of CASES) {
  const hand = tileCounts(c.hand);
  const remaining = remainingFromVisible(c.visible, c.hand);

  const minShan = calculateMinimumShanten(hand);
  const stdShan = calculateStandardShanten(hand);

  let perDiscard = null;
  let bestIdx = null;
  let curUkeire = null;
  if (c.hand.length === 14) {
    const d = calculateDiscardUkeire(hand, remaining, calculateMinimumShanten, minShan);
    perDiscard = d.map((r, i) => ({ index: i, value: r.value, tiles: r.tiles }));
    bestIdx = evaluateBestDiscard(d);
    curUkeire = perDiscard[bestIdx] ? perDiscard[bestIdx].value : 0;
  } else {
    const u = calculateUkeire(hand, remaining, calculateMinimumShanten, minShan);
    curUkeire = u.value;
  }

  out.push({
    name: c.name,
    shanten: minShan,
    shanten_standard: stdShan,
    current_ukeire: curUkeire,
    best_discard_index: bestIdx,
    per_discard: perDiscard,
  });
}

console.log(JSON.stringify(out, null, 2));
