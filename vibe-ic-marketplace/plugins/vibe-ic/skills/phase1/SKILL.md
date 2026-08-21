---
name: phase1
description: Phase 1 = the **prompt / dialogue entry point** to the Vibe-IC platform. Takes natural language (Chinese or English), runs the IC Expert Agent dialogue (it faces the user in a plain-language register and owns silicon depth), produces both (a) machine-readable L1-L27 JSON layer docs that feed Phase 2 directly AND (b) human-readable Markdown views of the same content for stakeholder review. Skips Phase 1 entirely — the L1-L27 JSON is the universal handoff format and Phase 1 emits it directly. Triggers when the user says "start a new IC design", "run Phase 1", "design a chip in natural language", provides only a prompt or wants AI to author the spec from scratch.
---

# Phase 1 — prompt / dialogue entry point

This is **one of two entry points** to the Vibe-IC platform. See "Two
entry points" below for the complete picture.

```
   Phase 1 (this skill):  Prompt / Dialogue ──► L1-L27 JSON     ──┐
                                              + Human Readable .md │
                                                                   ▼
                                                            Phase 2 → Phase 3
```

Phase 1 emits the L1-L27 JSON directly — **Phase 1 is NOT in this
path**. The JSON files are the universal handoff format consumed by
Phase 2. The Markdown views are for human review only and have no
load-bearing downstream consumer.

## Two entry points to the platform

| Entry | Skill chain | When to use |
|-------|-------------|-------------|
| **A. Prompt / Dialogue** | this `phase1` skill (`+ spec-review` for final confirm) | User has only an idea, wants AI to author the spec via dialogue |
| **B. Existing Design Documents** | Phase 1's 17 doc-gen skills (`datasheet-gen`, `frs-gen`, `cmd-protocol-gen`, `regmap-gen`, `adi-spec-gen`, `control-logic-gen`, `test-debug-gen`, `timing-waveform-gen`, `rtl-constants-gen`, `integration-spec-gen`, `test-cases-gen`, `calibration-gen`, `behavioral-sequences-gen`, `lab-calibration-gen`, `doc-consistency-check`, `schematic-gen`, `otp-content-gen`) | User already has vendor PDFs / hand-authored markdown spec, wants per-layer extraction |

Both entry points converge at L1-L27 JSON, then enter Phase 2 → Phase 3.

## What Phase 1 (this skill) does

1. Ingest a prompt (NL) or structured YAML into a `facts.yaml` (UUID-tagged, provenance-tracked fact graph)
2. Detect gaps against the IC class template
3. Run the IC Expert Agent dialogue (the merged front-door role asks the user about gaps in its plain-language register)
4. The same IC Expert Agent fills residual gaps from K3 industry defaults / class reference / retrieved-neighbour ICs
5. **Render**:
   - `generated_docs/L*.json` — the canonical machine-readable form (fed to Phase 2)
   - `human_docs/L*.md` — Markdown views of the same content (for stakeholder review; added v0.60)
6. Emit a per-fact provenance audit (`PROVENANCE.md`)

A fact graph is a single source of truth; both the JSON and the Markdown
are just views over it.

## Layer scope

| Layer  | Filename                       | Phase | Notes |
|--------|--------------------------------|-------|-------|
| L1     | L1_DATASHEET.json              | 1     | core  |
| L2     | L2_FRS.json                    | 1     | core  |
| L3     | L3_CMD_PROTOCOL.json           | 1     | core; sentinel `protocol_present:false` legal for memory/analog ICs |
| L4     | L4_REGMAP.json                 | 1     | core  |
| L5     | L5_ADI_SPEC.json               | 1     | core  |
| L6     | L6_CONTROL_LOGIC.json          | 1     | core  |
| L7     | L7_TEST_DEBUG.json             | 1     | core  |
| L8     | L8_TIMING_WAVEFORM.json        | 1     | core  |
| L8R    | L8_RTL_CONSTANTS.json          | 1     | core  |
| L9     | L9_INTEGRATION_SPEC.json       | 1     | core  |
| **L10** | **L10_TEST_CASES.json**       | **1** | extension — CMD→RSP byte vectors used by `cmd_response_conformance_check` |
| **L11** | **L11_CALIBRATION.json**      | **1** | extension — platform-specific tuning tables; required `domain_clock` / `source_clock` / `scale_factor` |
| **L12** | **L12_BEHAVIORAL_SEQUENCES.json** | **1** | extension — multi-step protocols (engineer mode unlock, CC reset, etc.) |
| **L13** | **L13_LAB_CALIBRATION.json**  | **1+2b** | extension — Phase 1 fills the **contract** (criterion / criterion_params / tester); Phase 2 appends **evidence** (known_pass_bitstream + known_pass_transcript) |

## Why This Supersedes The v0.51 Serial Pipeline

- **Dialogue is no longer the input format.** Users paste what they have
  — YAML, tables, OTP hex — and only the remaining gaps go through PM
  Agent dialogue. Expert users skip dialogue entirely.
- **L1..L9 are render views, not authoring steps.** No layer can be
  silently skipped; if a fact needed for L3 is missing, the gap detector
  surfaces it before rendering.
- **Provenance is per-fact, not per-layer.** Every fact carries a UUID,
  source (user_stated / defaulted / retrieved / derived / class_floor /
  class_required / inferred), origin citation, and trust score.
  Phase 2/3 failures trace back to offending facts.
- **No LLM in render.** `facts.yaml → L*.json` is pure Python. The only
  LLM calls happen in ingest (parsing free-text user input) and in the
  optional PM dialogue for unfilled gaps.

## Input modes (all land in the same facts.yaml)

| User gives you … | How Phase 1 runs |
|---|---|
| A paragraph in plain language | **NL mode** — IC Expert Agent (plain-language register) calls `nl-ingest`, runs gap dialogue, then renders |
| A structured `spec.yaml` | **Fast-path** — one `run-all` call, no dialogue, renders |
| A pin-table CSV (v0.74) | `ingest-pins` → L1.pinout.* facts (optionally `--merge-into` an existing facts.yaml) |
| A register-map CSV (v0.74) | `ingest-regmap-csv` → L4.registers.* facts |
| An OTP hex image — Intel HEX or raw hex (v0.74) | `ingest-otp-hex` → L4.otp.* facts |
| Existing L1..L9 JSON docs | `ingest-docs` — reverse-extracts facts |

Both NL and fast-path modes finish at the same output shape
(`generated_docs/L1..L9.json` + optional L10-L13).
The NL mode preserves the "design a chip in natural language" product promise.

NL-mode extraction is **model-neutral** (v0.74): the caller must specify
an Anthropic model via `--model <id>` or the `$PHASE1_NL_MODEL` env var.
There is no default model — the skill does not prefer any specific one.

## Usage

### NL mode (common / medium user — "design a chip in natural language")

Invoked by the IC Expert Agent (see `../../agents/ic-expert-agent.md`). Minimal end-to-end:

```bash
# 1. NL → seed facts (calls Anthropic API if ANTHROPIC_API_KEY set)
python3 -m tools.phase1_engine.cli nl-ingest \
    --text "I want to build an ID IC inside a USB-C cable; the handset must be able to tell whether the cable is genuine..." \
    --class-path cable-side-id-ic \
    --out facts.yaml

# 2. detect gaps
python3 -m tools.phase1_engine.cli gaps facts.yaml --out-json gaps.json

# 3. IC Expert Agent iterates: for each gap, pick K2 qbank variant, ask user, then:
python3 -m tools.phase1_engine.cli set-fact facts.yaml \
    --path "L3.frame_format.crc.poly" --value "0x31" --source user_stated

# 4. render when gaps resolved (IC Expert fills residual with defaults)
python3 -m tools.phase1_engine.cli render facts.yaml ./out/generated_docs/ \
    --provenance-report ./out/PROVENANCE.md
```

If `ANTHROPIC_API_KEY` is not set, `nl-ingest --prompt-only` emits the
extraction prompt so a calling agent can run the LLM externally, then
feed facts JSON back via `ingest-extracted`.

### Fast-path (expert: structured YAML)

```bash
python3 -m tools.phase1_engine.cli run-all path/to/spec.yaml ./out
```

`spec.yaml` format:

```yaml
ic_name: MY_IC
class_path: cable-side-id-ic
L1:
  ic_name: MY_IC
  pinout: { VBUS: "Pin 1 — ...", ... }
  electrical_characteristics: { supply_vbus: { min: 4.5, typ: 5.0, max: 5.5, unit: V } }
  ...
L3:
  protocol_name: ...
  commands: [ { opcode: "0x70", name: CMD_PING, ... } ]
  ...
```

Output:
```
out/
├── facts.yaml            # fact graph (YAML)
├── gaps.json             # gap report
├── PROVENANCE.md         # per-fact audit trail
└── generated_docs/
    ├── L1_DATASHEET.json
    ├── L2_FRS.json
    ├── ...
    └── L9_INTEGRATION_SPEC.json
```

### From existing docs (regression / refactor)

```bash
python3 -m tools.phase1_engine.cli ingest-docs path/to/generated_docs/ --out facts.yaml
python3 -m tools.phase1_engine.cli render facts.yaml ./out/generated_docs/ --provenance-report ./out/PROVENANCE.md
```

## Phase 1 sibling skills (used by Entry B, optionally invokable after Phase 1)

Phase 1's 17 doc-gen skills are the alternative entry path for users
who already have Design Documents. After Phase 1 renders, these skills
can ALSO be invoked to refine a single layer (e.g. "regenerate just L4
with this new register added") without re-running the whole pipeline.

| Skill | Layer | Notes |
|---|---|---|
| `datasheet-gen` | L1 | restored to active in v0.60 |
| `frs-gen` | L2 | restored v0.60 |
| `cmd-protocol-gen` | L3 | restored v0.60 |
| `regmap-gen` | L4 | restored v0.60 |
| `adi-spec-gen` | L5 | restored v0.60 |
| `control-logic-gen` | L6 | restored v0.60 |
| `test-debug-gen` | L7 | restored v0.60 |
| `timing-waveform-gen` | L8 | restored v0.60 |
| `rtl-constants-gen` | L8R | restored v0.60 |
| `integration-spec-gen` | L9 | restored v0.60 |
| `test-cases-gen` | L10 | always active |
| `calibration-gen` | L11 | always active |
| `behavioral-sequences-gen` | L12 | always active |
| `lab-calibration-gen` | L13 (contract) | always active |
| `doc-consistency-check` | cross-layer | always active |
| `schematic-gen` | L9-derived | always active; produces block diagram |
| `otp-content-gen` | L4-derived | always active; produces `.ver` OTP image when L4 declares OTP |

The v0.51 `prompt-intake` and `phase1-orchestrate` skills are NOT
restored — their function is fully subsumed by this `phase1` skill's
ingest + IC Expert Agent dialogue + render pipeline. They remain archived at
`legacy/skills_phase1_v051/` for reference.

### Dialogue-driven (common / medium user)

The IC Expert Agent (see `../../agents/ic-expert-agent.md`) drives an
interactive session in its plain-language register,
calling `tools/phase1_engine/cli.py` internally:

1. `prompt-intake` gathers initial free-text.
2. Whatever facts can be parsed from the text become the seed fact graph.
3. `gaps` reports remaining required-but-missing facts.
4. IC Expert Agent asks the user about each gap in its plain-language register (using the Q-bank, K2).
5. Unanswered gaps → IC Expert fills from K3 / class_reference / retrieved
   neighbour with `source=defaulted` or `source=retrieved`.
6. `render` emits the **14 layer JSONs** — 10 core (L1-L9 + L8R) plus
   4 extension (L10-L13). The extension layers are skipped silently when
   no facts under their prefix exist (e.g. an IC with no L12 sequences
   simply doesn't get an `L12_BEHAVIORAL_SEQUENCES.json`).

## Gates

After render, the orchestrator runs the existing gate suite. Run the
core four for every project; the extension gates fire only when the
matching extension layer was rendered (or, for `no_protocol_consistency`,
when L3 declares the sentinel).

**Core (always run)**

1. `phase1_doc_presence_check.py` — all 10 core L*.json present (L3 + L8R
   skip cleanly when L1/L3 declares `protocol_present:false`, v0.57 D2).
2. `phase1_consistency_check.py` — cross-layer consistency (K4 rules).
3. `phase1_quality_parity_check.py` — spec_floor minimums met
   (auto-resolves `--class-path` from `L1.class_path`, v0.56 A1).
4. `json_schema_check.py` — each L*.json conforms to its skill profile.

**Extension (conditional)**

5. `layer_extension_presence_check.py` — required L10/L11/L12 categories
   per the class template's `spec_floor`.
6. `cmd_response_conformance_check.py` — each L10 vector drives RTL via
   iverilog and matches expected response byte-for-byte (Phase 2).
7. `clock_scale_consistency_check.py` — every L11 calibration entry
   declares `domain_clock` / `source_clock` / `scale_factor`.
8. `no_protocol_consistency_check.py` — when L3 sentinel is in effect,
   verify no contradicting `command_set` / `crc` / L8R CRC constants
   / class-floor opcode-count mismatches (v0.56 C3 / v0.57 D1).
9. `hardware_pass_attestation_check.py` — Phase 1 reads the L13
   **contract**; Phase 2 appends and re-reads with the real-tester
   evidence (5 criterion types, v0.56 B4).

All four core gates must exit 0 before Phase 2 can start. Extension
gates that fire must also exit 0; gates whose trigger artefact is
absent skip cleanly.

## Agents

ONE agent operates in two registers on the fact graph (not on layer docs):

- **External register** translates user intent into fact-level updates (one
  fact per dialogue turn). Never asks a technical question the user cannot
  answer at their level — plain product language only, no silicon jargon.
- **Internal register** reviews the fact graph for consistency, fills gaps
  from K3 / retrieved neighbours, flags high-impact conflicts for user
  confirmation (surfaced back through the external register).

See `../../agents/ic-expert-agent.md`.

## Where Things Live

| What | Where |
|---|---|
| Fact-graph schema + dataclasses | `tools/phase1_engine/schema.py` |
| Ingesters (docs, YAML, bulk paste) | `tools/phase1_engine/ingest.py` |
| Gap detector | `tools/phase1_engine/gap_detect.py` |
| Renderer (JSON + Markdown) | `tools/phase1_engine/render.py` (`render_layers` + `render_human_docs`) |
| Retrieval (top-K similar ICs) | `tools/phase1_engine/retrieve.py` |
| CLI | `tools/phase1_engine/cli.py` (`run-all` / `render --human-docs-dir`) |
| Class templates (K1) | `vibe-ic/agents/class_kb/templates/` |
| Q-bank (K2) | `vibe-ic/agents/qbank/` |
| Defaults (K3) | `vibe-ic/agents/defaults/` |
| Consistency rules (K4) | `vibe-ic/programs/phase1_consistency_check.py` |
| Runtime feedback (K5) | `vibe-ic/programs/phase1_k5_quality_check.py` + `tools/training/phase1_k5_autopatch.py` |

## Legacy

The v0.51 `prompt-intake` and `phase1-orchestrate` skills are archived
at `legacy/skills_phase1_v051/` and are no longer invoked — their
function is subsumed by this `phase1` skill.

The 10 v0.51 doc-gen skills (`datasheet-gen` through `integration-spec-gen`)
were briefly archived in v0.58 but **restored to active in v0.60** as
the Phase 1 Entry B path (existing-Design-Documents → L1-L27). They
were never legacy in spirit — only in v0.58 placement.

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/phase1/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
