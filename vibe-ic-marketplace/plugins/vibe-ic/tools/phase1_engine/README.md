# phase1_engine — Fact-Graph-First Phase 1

Replaces the v0.51 serial L1..L9 doc-gen pipeline with:

```
  user input  ─►  facts.yaml  ─►  gap report  ─►  L1..L9 JSON
```

## Why

v0.51 had 11 skills (`prompt-intake`, `datasheet-gen`, `frs-gen`,
`cmd-protocol-gen`, `regmap-gen`, `adi-spec-gen`, `control-logic-gen`,
`test-debug-gen`, `timing-waveform-gen`, `rtl-constants-gen`,
`integration-spec-gen`) walking the user layer-by-layer. Problems:

1. Same fact re-asked across layers (CRC polynomial appears in L3 + L8R).
2. Users with structured spec still forced through 11-step dialogue.
3. L8/L8R and L9 contain facts that are purely derived, but generation
   was LLM-authored, allowing drift.
4. K5 feedback loop operated at rule-level, so a failing RTL bug couldn't
   be traced back to the offending fact.

## Architecture

### Schema (`schema.py`)

One `Fact` = one atomic truth:
- `path`: dotted path in the unified design namespace
- `value`: scalar / dict / list
- `views`: list of layer codes this fact renders into (`["L3","L8R"]`)
- `provenance`: source + origin + confidence + trust_score + auto_decided
- `uuid`: stable `f-<hex8>` derived from `(path, value)`

A `FactGraph` = unordered collection of facts plus IC metadata.

### CLI verbs

| Verb | Input | Output |
|---|---|---|
| `ingest-docs` | existing L*.json dir | `facts.yaml` (reverse-extract) |
| `ingest-yaml` | structured YAML (layer-keyed) | `facts.yaml` |
| `nl-ingest` | free-text description + class | `facts.yaml` (calls Anthropic API if key set; else prints prompt) |
| `nl-prompt` | free-text | extraction prompt only (for external LLM callers) |
| `ingest-extracted` | facts JSON produced externally by an LLM | `facts.yaml` |
| `gaps` | `facts.yaml` | gap list vs K1 class template + spec_floor |
| `set-fact` | `facts.yaml` + path + value | updates one fact (gap dialogue drop-in) |
| `render` | `facts.yaml` | `L1..L9.json` (pure Python, no LLM) |
| `run-all` | structured YAML or docs dir | ingest + gaps + render in one step |
| `retrieve` | `facts.yaml` | top-K similar trained ICs |
| `round-trip` | docs dir | reverse-extract + re-render for diff testing |

### Why layer-prefixed paths (MVP)

Currently every fact has `path = "L<N>.<sub-path>"` and exactly one view.
This gives trivial round-trip: reverse-extract then re-render produces
byte-identical output. Future iterations will migrate to a unified
namespace with cross-layer `views` (e.g. one CRC-poly fact with
`views = [L3, L8R]` rendered twice).

## Status

- ✅ Round-trip validated on BENCH-A HIGH: 10/10 layers byte-identical,
  all 4 existing gates PASS.
- ✅ Gap detection for required facts, spec_floor minimums, CRC
  whitelist, required submodules.
- ⚠ K1 class template paths have some drift vs benchmark L*.json paths;
  gap detector flags a couple of advisory gaps on the full graph. Fix
  in a follow-up (align K1 template paths to actual render paths).
- ⏳ Bulk parsers (`pin_table`, `reg_map_csv`, `otp_hex`) — not yet
  implemented.
- ⏳ Free-text ingest via LLM — delegated to the IC Expert Agent for now.
- ⏳ Fact-level feedback from Phase 2/3 failures — not yet wired.

## CLI

```bash
# Fast-path: structured YAML → full output
python3 -m tools.phase1_engine.cli run-all spec.yaml ./out

# Step by step
python3 -m tools.phase1_engine.cli ingest-yaml spec.yaml --out facts.yaml
python3 -m tools.phase1_engine.cli gaps facts.yaml --out-json gaps.json
python3 -m tools.phase1_engine.cli render facts.yaml ./generated_docs \
    --provenance-report ./PROVENANCE.md

# Regression: reverse-extract + re-render any existing output for diff test
python3 -m tools.phase1_engine.cli round-trip path/to/generated_docs/
```

## Files

```
tools/phase1_engine/
├── __init__.py       # module exports
├── schema.py         # Fact, FactGraph, Provenance, layer codes
├── ingest.py         # from_existing_docs, from_structured_yaml, merge
├── gap_detect.py     # detect_gaps against K1 class template + spec_floor
├── render.py         # render_layers, render_provenance_report
├── retrieve.py       # top_k_for_graph (wraps ic_similarity_index)
├── cli.py            # argparse entry: ingest-docs/ingest-yaml/gaps/render/run-all/retrieve/round-trip
└── README.md         # this
```

## Integration

- **Skill**: `vibe-ic-marketplace/plugins/vibe-ic/skills/phase1/` (+
  mirror in `vibe-ic-d`) — single entry point invoking the CLI above.
- **Legacy 11 skills**: archived at `legacy/skills_phase1_v051/` — not
  invoked by the new flow but kept for reference / regression tests.
- **Gate suite**: existing programs under `vibe-ic-d/programs/`
  (`phase1_doc_presence_check.py`, `phase1_consistency_check.py`,
  `phase1_quality_parity_check.py`, `json_schema_check.py`) run
  unchanged on the rendered `generated_docs/`.
