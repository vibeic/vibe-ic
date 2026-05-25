# Phase-1 Fact-UUID Threading → Phase 2/2b (v0.74, DESIGN + PoC + C3)

**Status**: v0.74 ships **Stage C1 (render emits fact_index.json)** and
**Stage C3 (K5 consumes markers)**. Stage C2 (spec-to-rtl emits markers)
is the remaining piece; specified here but NOT implemented.

**Authored**: 2026-04-25 during v0.74 phase1 plugin enhancement.

**Prior memory reference**: `memory/phase1_fact_graph.md` — "Known drift
/ follow-ups → Fact-level feedback: Phase-2/3 RTL generation doesn't
yet carry fact UUIDs in comments; K5 still rule-based."

---

## 1 · Problem

Today when Phase 2 fails (synth error, sim mismatch, FPGA timing), K5
(`phase1_k5_quality_check.py`) classifies the failure into a handful of
rule patterns: missing_fact, pm_didnt_ask, wrong_default, inconsistency.
These are good heuristics but coarse — K5 can say "something about L3's
CRC is wrong" but cannot point to a specific Phase-1 fact like
`L3.frame_format.crc.poly` with its provenance ("user_stated, 2026-04-12,
reasoning: user picked MAXIM-1-Wire style").

When Phase 2 generates RTL, the fact identity that drove each line of
RTL is lost: a `localparam BIT_PERIOD_CYCLES = 200;` line in
`otp_ctrl.v` is just a number — nothing in the RTL points back to the
Phase-1 fact that authored it (`L8R.bit_period_cycles` with UUID
`7f3a1d42`, source `derived`, derives_from `L8.aid_bit_timing.bit_period_us`).

Without a fact→RTL trace, K5 cannot:
- Pinpoint WHICH fact caused a synth error
- Auto-suggest changing `L8.aid_bit_timing.bit_period_us` upstream vs
  patching `L8R.bit_period_cycles` downstream (the latter is a
  dead-letter fix — next render overwrites it)
- Feed targeted corrections back into K3 defaults / K4 rules

---

## 2 · v0.74 PoC (landed in this release)

**New: `fact_index.json`** — a stable `path → uuid` JSON map emitted by
`render` (via `--fact-index <path>`) and auto-emitted by `run-all`
alongside `PROVENANCE.md`.

```json
{
  "L1.part_number": "a1b2c3d4...",
  "L3.commands[0].opcode": "e5f6a7b8...",
  "L3.frame_format.crc.poly": "7f3a1d42...",
  "L8R.bit_period_cycles": "9c2e5f10...",
  ...
}
```

This is sufficient machine-readable anchor for any downstream consumer
to do: "given a fact path, what is its stable UUID?" and vice versa.

**What the PoC does NOT yet do** (design §3-§5):

- RTL-side: no `// fact:<uuid>` comments are emitted by `spec-to-rtl`
- K5-side: `phase1_k5_quality_check.py` still uses rule-pattern
  classification; doesn't read RTL comments
- Training: `phase1_k5_autopatch.py` still patches K1-K4 by pattern,
  not by fact-UUID lookup

---

## 3 · Full design — fact-UUID threading

### 3.1 Convention

For every RTL construct (module, localparam, wire, always block,
comment block) that derives from a single Phase-1 fact, emit a
comment marker immediately before that construct:

```verilog
// phase1-fact: <uuid>  path=<L*.<path>>  source=<provenance.source>
localparam BIT_PERIOD_CYCLES = 200;
```

Rules:
- Marker lives on a line by itself, immediately above the construct
- Marker format is machine-parseable (fixed regex, described §3.3)
- If a construct derives from multiple facts (e.g. a conditional
  generate block), emit multiple `phase1-fact:` lines in order of
  precedence (primary-source fact first)
- Facts with no direct RTL manifestation (e.g. L2 functional
  requirements, L7 documentation-only test modes) do NOT get markers
  anywhere; their UUIDs live only in `fact_index.json`

### 3.2 Where spec-to-rtl emits markers

Source of truth: `vibe-ic-marketplace/plugins/vibe-ic-{core,d}/skills/spec-to-rtl/`.

spec-to-rtl must be extended to:
1. Load `fact_index.json` (and the full facts.yaml for provenance
   detail) alongside the L*.json layer files.
2. When rendering an RTL line whose content is determined by a specific
   fact path, consult the index and emit the comment marker.
3. When the content is synthesized from multiple facts (e.g. a MUX
   whose case labels come from L3.commands[*].opcode), emit one marker
   per fact in the order they feed the synthesis.
4. When the content is boilerplate not traceable to any fact
   (register decoder skeleton, clock-gate insertion), emit no marker.

### 3.3 Marker regex

```python
FACT_MARKER_RE = re.compile(
    r"//\s*phase1-fact:\s*([0-9a-f]{8,})\s+"
    r"path=([^\s]+)\s+"
    r"source=(\w+)"
)
```

Design constraint: the marker must be on a comment-only line so it
survives every downstream transformation (lint, Yosys synth, GTKWave
extraction) as-is.

### 3.4 K5 consumer side

`phase1_k5_quality_check.py` extended with a new classification kind:

- **`missing_fact_uuid`** — Phase 2 fail traces to a specific fact UUID
  that doesn't exist in facts.yaml (fact deleted / renamed since render)
- **`fact_value_mismatch`** — RTL line says `BIT_PERIOD_CYCLES = 200`
  with marker pointing at fact UUID `9c2e...` whose current value in
  facts.yaml is `250`. Source of truth drifted.
- **`multi_fact_conflict`** — two markers on same construct point at
  facts with mutually-inconsistent values (K4 rule violation, but
  detected at RTL instead of at L-level render).

K5 then emits patches:
- For `missing_fact_uuid`: hint the K5 autopatch to add the fact (K3
  default if available) or to remove the RTL construct.
- For `fact_value_mismatch`: re-render L*.json + re-run spec-to-rtl
  (the RTL is stale, not the fact).
- For `multi_fact_conflict`: route to K4 for a new consistency rule.

### 3.5 Provenance propagation

`PROVENANCE.md` already captures per-fact source / origin / reasoning.
The new `fact_index.json` does NOT duplicate this — it's just path→uuid.
K5 / Phase-2 consumers needing full provenance load the facts.yaml.

---

## 4 · Migration path

### Stage C1 — PoC (v0.74, landed)
- `render_fact_index()` emits `fact_index.json`
- `cli.py`: `render --fact-index <path>` + `run-all` auto-emit
- No consumer changes yet

### Stage C2 — spec-to-rtl emits markers (proposed — next iteration)
- Update both `vibe-ic-core/skills/spec-to-rtl` and
  `vibe-ic-d/programs/spec_to_rtl` to read `fact_index.json` and
  emit `// phase1-fact:` markers per §3.1
- No K5 change yet — markers land but nobody reads them
- Verify: BENCH-A common round-trip through spec-to-rtl still passes
  its Phase-2 regression; new RTL has markers; markers don't break
  Yosys synth (Verilog comments are pass-through)

### Stage C3 — K5 consumes markers (proposed)
- Extend `phase1_k5_quality_check.py` to scan failing RTL for markers
- Add the 3 new classification kinds per §3.4
- Update `phase1_k5_autopatch.py` to emit fact-path-keyed patches
  instead of rule-pattern-keyed

### Stage C4 — training loop closes the loop
- Next training epoch (E15+) logs K5-fact-level-events as training
  signals alongside the existing K5-rule-level events
- Corpus autopatch now operates at fact level, not pattern level

---

## 5 · Risks and open questions

**R1 — marker surface expands RTL diff noise.** Every fact-derived RTL
line gains a comment. Reviewers see 2× the line count of "meaningful"
RTL changes during review. Mitigation: markers use a stable prefix
that most diff tools can fold.

**R2 — UUID collision on re-render.** The fact UUID is deterministic
over `(path, value)`. If the user fixes a typo in the value (no path
change), the UUID shifts. Every RTL marker pointing at the old UUID
becomes a `missing_fact_uuid`. Workaround: allow K5 to look up by
path (not only UUID) as a fallback match; emit a warning when the
match-by-path finds a UUID-drifted fact.

**R3 — spec-to-rtl ownership fragmentation.** The skill lives in two
plugins (core + d). Both must learn to emit markers. If either
forgets, RTL is partially-annotated and K5 has ambiguous trace
coverage. **OPEN**: should we enforce marker emission via a compliance
rule in `spec-to-rtl/compliance.yaml`?

**R4 — what about facts that don't map to a single RTL site?** L2
functional requirements inform testbench assertions, not RTL
directly. These facts should still appear in `fact_index.json` (they
exist), but no `// phase1-fact:` marker will ever reference them.
K5's coverage model needs to distinguish "fact expected to have a
marker but doesn't" from "fact not expected to have a marker." **OPEN**:
add a `has_rtl_manifestation: bool` field per K1 template entry?

---

## 6 · Deliverable checklist

- [x] Stage C1 (PoC, v0.74)
  - [x] `render_fact_index()` in `tools/phase1_fg/render.py`
  - [x] `--fact-index` flag on `render` CLI verb
  - [x] `run-all` auto-emits `fact_index.json` in out_dir
  - [x] This design note
- [ ] Stage C2 (spec-to-rtl marker emission) — next iteration
- [x] Stage C3 (K5 consumer, v0.74)
  - [x] `check_fact_uuid_markers()` in `phase1_k5_quality_check.py`
  - [x] New flags `--rtl`, `--fact-index`, `--facts` on the K5 CLI
  - [x] Three new issue IDs: K5-T (unknown UUID), K5-U (value mismatch),
        K5-V (multi-fact conflict)
  - [x] `_coerce_value_for_compare()` handles Verilog sized literals
        (`8'h31`), C-style hex (`0x31`), and ints — so the same fact
        value compares equal whether it's authored as `"0x31"` in
        facts.yaml or emitted as `8'h31` in RTL.
  - [x] 7 new pytest cases using synthetic RTL fixtures (spec-to-rtl
        does NOT yet emit real markers, so hand-authored RTL is the
        only available test surface until C2 lands).
- [ ] Stage C4 (training-loop fact-level patches) — after C2 lands

**Blocking C2**: design answer to §5-R3 (cross-plugin compliance
enforcement) + §5-R4 (marker-expected bit per K1 fact — needed to
distinguish "marker missing, expected" from "marker missing, not
expected" once C3 starts checking for marker coverage).

**C3 without C2 caveat**: K5 can consume markers as soon as any RTL
has them, but the full closed loop (Phase-2 failure → fact-UUID
trace → K3/K4 patch) stays inert until spec-to-rtl starts emitting
markers. In v0.74, C3 is a ready consumer — no producer yet.
