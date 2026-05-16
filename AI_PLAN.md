# AI Integration Master Plan (Two-Part)

End goal: the observer's per-turn output shows THREE side-by-side
recommendations on every actionable state:

```
[trainer]  discard 3z   (shanten=1, ukeire=15, safety=87)
[myai]     discard 3z   (p=0.82, top-3: 3z/8m/9p)
[mortal]   discard 8m   (p=0.61, top-3: 8m/3z/9p)
```

User chooses what to trust; agreement between sources is itself a
signal.

---

## PART A — `src/mahjong_meme/myai/` (from-scratch CNN-ResNet)

Framework: **PyTorch**. Targets behavioral cloning on the JSON dumps
from `tools/dump_replay.py`.

### A1. Feature encoder — `myai/features.py`

```text
encode_state(state_dict) -> {
    "planes":  Tensor shape (C, 34)   # ~200 binary tile planes
    "scalars": Tensor shape (S,)      # ~40 dense scalars
    "mask":    {head_name: bool}      # which heads are valid here
}
```

Plane groups (each 34 cells = one cell per tile-type 0..33):

- hand-count planes (4): 1 plane per copy threshold
- own meld planes (~12): chi/pon/kan/added/closed split
- 4× discard planes (4 × ~30): one per opponent's river with turn
  index encoded as plane depth (early/mid/late)
- 4× called-meld planes (4 × ~12)
- 4× riichi-flag planes (4 binary)
- dora-indicator planes (5 max, one per kan-level)
- round-wind planes (4: E/S/W/N) and seat-wind planes (4)
- last-discard tile plane (binary 34) + last-discard moqie flag
- drawn-tile plane (binary 34) if any

Scalars:

- turn count, `left_tile_count`
- 4× normalized score (current/25000), 4× rank
- 4× riichi sticks, ben count
- **trainer features** (huge for sample efficiency):
  - shanten (-1..6), ukeire count (0..150), has-yaku (binary)
  - per-opponent safety score (4 floats)
  - best-discard-from-trainer (one-hot over 34)

Reuse tile parsing from `trainer/tiles.py` for consistency. Red fives
(`5m*`/`5p*`/`5s*`) collapse to the normal-five cell with a separate
red-flag plane.

### A2. Action encoder — `myai/actions.py`

```text
encode_choice(record) -> (head_id, label)
```

Heads + label spaces:

| head | name      | classes |
|------|-----------|---------|
| 0    | discard   | 34 (tile types) |
| 1    | call      | 5 {chi-low, chi-mid, chi-high, pon, pass} |
| 2    | kan       | 2 {kan, pass} — covers ankan/chakan/openkan |
| 3    | riichi    | 2 {riichi, pass} |
| 4    | win       | 2 {win, pass} — covers ron + tsumo |

Active-head selection:

- `event.kind == 'discard'` → head 0 (discard)
- `event.kind == 'call'` → head 1 if chi/pon, head 2 if kan
- `event.kind == 'riichi'` → head 3
- `event.kind == 'agari'` → head 4
- `state.kind == 'observe'` → SKIPPED (no learning signal)
- skip-with-options state → use head matching the option type, label = the `pass` class

Records with `choice == 'skip'` AND no real options → drop from training.

### A3. Model — `myai/model.py`

```text
class MyAI(nn.Module):
    - input projection: Conv1d(C_planes -> 256, kernel=1)
    - body: N=30 ResNet1d blocks (kernel=3, padding=1, BN+ReLU)
    - scalar projection: MLP(scalars -> 256)
    - fusion: trunk_pool || scalar_emb -> 512
    - heads: nn.Linear(512, 34), 5, 2, 2, 2
    - forward(planes, scalars, head_id) -> logits
```

~5–7M params target. Optional: light cross-attention between scalars
and per-tile features instead of pooling, for shape-aware decisions.

### A4. Dataset — `myai/dataset.py`

```text
class ReplayDataset(torch.utils.data.Dataset):
    - lazy-loads from demo/parsed/**/seat*.json (or jsonl)
    - filters records: keep only those with an active head
    - returns (planes, scalars, head_id, label, sample_weight)
    - sample_weight = 1/class_freq within each head (rebalance skip vs act)
```

Train/val split: by replay file, not by record (avoid leakage).

### A5. Training loop — `myai/train.py`

- Optimizer: AdamW lr=3e-4, weight_decay=0.01, cosine schedule
- Loss: per-head cross-entropy, summed (only active head contributes)
- Mixed precision (`torch.cuda.amp`) if GPU available
- Eval: top-1 accuracy per head vs human-pro choice, plus
  agreement-with-trainer for sanity
- Checkpoint: best-val per head + last; save under
  `artifacts/myai/checkpoint-NNN.pt` (gitignored)
- CLI: `python -m mahjong_meme.myai train --epochs 30 --batch 256`

### A6. Inference adapter — `myai/predict.py`

```text
class MyAIPredictor:
    - __init__(checkpoint_path) loads model + freezes
    - recommend(state_dict) -> {
        'head': 'discard'|'call'|...,
        'action': <choice dict matching observer schema>,
        'prob': float,
        'topk': [(action, prob), ...]
      }
    - Masks invalid actions using state.actionable.options before softmax.
```

### A7. CLI entry point — `myai/__main__.py`

```bash
python -m mahjong_meme.myai train --data demo/parsed --epochs 30
python -m mahjong_meme.myai eval  --checkpoint artifacts/myai/best.pt
python -m mahjong_meme.myai predict --checkpoint ... --state state.json
```

### A8. Smoke / setup

- Add `torch` to `setup.py` / requirements.
- Smoke-train on the 8 existing replays for 1 epoch → verify pipeline
  runs end-to-end (loss goes down, no NaN). Real training needs ~10k
  replays; scaling `demo/download.py` is a separate task.

---

## PART B — `src/mahjong_meme/mortalai/` (Mortal integration) — **DROPPED**

> **Status (2026-05-16): SKIPPED.** Mortal cannot be integrated under
> current constraints. Two hard blockers:
>
> 1. **License**: Mortal is AGPL-3.0-or-later. Vendoring + importing
>    its modules would force this project to AGPL too.
> 2. **Weights**: per the author's
>    [gist](https://gist.github.com/Equim-chan/cf3f01735d5d98f1e7be02e94b288c56)
>    (2022-08-19), pretrained weights are **not** publicly distributed
>    and there are no plans to release them. Self-training takes
>    days of GPU compute, out of scope here. No fork has published
>    weights.
>
> Reopen this section if (a) project licensing changes, or
> (b) shareable Mortal-style weights become available, or
> (c) `mjai.ekyu.moe` publishes a stable API.

The original B1–B5 task spec is retained below for reference; the
work was never started.

### B1. Vendor Mortal

```bash
git submodule add https://github.com/Equim-chan/Mortal third_party/Mortal
```

Pin to a known-good commit. README will note version + license.

### B2. State adapter — `mortalai/adapter.py`

Mortal's input format is a tenhou-style "paifu" event stream. Two paths:

(a) **Live**: maintain a per-round event log inside the observer; whenever
`computeState` is called, replay our own event log into Mortal's
stateful engine and ask for a recommendation.

(b) **Per-call**: build a minimal Mortal-compatible state object
directly from our observer state dict.

**Recommended**: (a) — mirror events from `observer.hook_events.js`
into a Mortal-format buffer; pass cumulative buffer to Mortal at
decision time. Requires reading Mortal's input schema (libriichi crate
/ mjai).

### B3. Pretrained weights

Mortal ships checkpoints via Hugging Face / project releases. Add a
`mortalai/download.py` helper that fetches a configured release into
`artifacts/mortal/` (gitignored). Document the exact version and SHA.

### B4. Inference wrapper — `mortalai/predict.py`

```text
class MortalPredictor:
    - __init__(checkpoint_dir) loads Mortal model via its public API
    - recommend(state_dict_or_event_buffer) -> same schema as MyAIPredictor
```

Mortal output maps to our action vocabulary via a translation table in
`mortalai/translate.py` (e.g. Mortal action `d5m` → our `discard 5m`).

### B5. CLI

```bash
python -m mahjong_meme.mortalai predict --state state.json
python -m mahjong_meme.mortalai download   # fetch weights
```

---

## PART C — Observer integration: tri-recommendation panel

### C1. Refactor advisor

`observer.py`: rename `_trainer_advice` → `_advisors(state)`. Returns a
list of strings: one per available advisor that has an opinion.

### C2. Lazy advisor registry

Build a list `ADVISORS = [TrainerAdvisor(), MyAIAdvisor(), MortalAdvisor()]`
where `MyAIAdvisor` and `MortalAdvisor` lazy-import torch+model on
first use. Missing model file → log once, return `None` thereafter
(graceful degrade).

### C3. Output format

Print three aligned lines per actionable state, with disagreement flag:

```
[trainer]  discard 3z   (shanten=1, ukeire=15)
[myai]     discard 3z   (p=0.82) AGREES
[mortal]   discard 8m   (p=0.61) DISAGREES
```

Also surface top-3 for myai/mortal so the user sees their confidence.

### C4. Config knobs

CLI flag: `--advisors trainer,myai,mortal` (default all available).
Env vars: `MAHJONG_MEME_MYAI_CHECKPOINT`, `MAHJONG_MEME_MORTAL_DIR`.

---

## Execution order

Part A is independent of B and C. Start there.
C wraps both A and B with graceful fallback, so it can land before B
if `MyAIAdvisor` is the only new opinion at first.

**Recommended order**:

```
A1 → A2 → A3 → A4 → A5 (smoke) → A6 → C1 → C2 (with stub MortalAdvisor
returning None) → C3 → B1 → B2 → B3 → B4 → B5 → enable MortalAdvisor
in C2.
```

Stop and re-plan after A5 smoke if the loss/data pipeline reveals
schema problems (likely: feature dim mismatches, class imbalance,
trainer feature integration bugs).

---

## Todo tracking

Todos are tracked in the session SQL store with the prefixes
`myai-A*`, `mortal-B*`, `obs-C*` and a dependency graph in
`todo_deps`. The session `plan.md` mirrors this document in long form.
