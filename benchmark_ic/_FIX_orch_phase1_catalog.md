# Fix Report — orchestrator + Phase-1-ingestion + catalog-query

Date: 2026-05-26
Scope (owned files only):
- `programs/vibe_ic_one_shot_runner.py`
- `programs/phase1_one_shot_runner.py` (verified intact, no edit needed)
- `programs/phase1_doc_one_shot_runner.py`
- `programs/ip_catalog_query.py`
- `programs/tests/test_orch_phase1_catalog_fixes.py` (NEW)

All fixes are REAL, chip-AGNOSTIC, minimal, and preserve honesty (no
fabrication, no masking of real failures). `ast.parse` passes on every
edited file.

---

## Fix 1 — Orchestrator auto-runs Phase 1 (docs mode) for Path-B vendor docs

File: `vibe_ic_one_shot_runner.py`

Problem: `_need_phase1()` SKIPPED phase1 when only vendor docs were
present (no structured/free-text prompt), but phase2 hard-requires the
L-docs, so every Path-B run dead-ended at the phase2 precondition.

Change:
- Replaced `_need_phase1()` with `_phase1_decision(project, force_skip)
  -> (run: bool, mode: str)`. `_need_phase1` is kept as a thin
  back-compat boolean wrapper.
- New decision logic:
  - 13+ L*.json already present → `(False, "")` (unchanged skip).
  - Path-A inputs (`phase1_structured.yaml` / `phase1_prompt.md`) →
    `(True, "prompt")`.
  - Populated `input/docs/` OR `phase1/input_doc/` and no L docs yet →
    `(True, "docs")`  ← the fix.
  - Nothing present → `(False, "")` (phase1 SKIPs gracefully).
- `main()` now reads the decision and, for Path-B, passes
  `--mode docs` to `phase1_one_shot_runner.py` so the doc-extraction
  track runs before phase2 instead of being skipped.

Tested via the pure decision function (no docker run).

## Fix 2 — Phase-1 input-mode detector (raw docs = docs unless layer-JSON)

File: `phase1_one_shot_runner.py`  (existing in-session fix VERIFIED intact)

`_detect_input_mode()` already routes a populated `input/docs/` to
`"docs"` mode UNLESS the directory contains layer-JSON (`L<n>.json`),
in which case it routes to `"prompt"` (reverse-extract path). No code
change required; locked in with regression tests. Also confirmed the
`_V1_6_566_RE_RST_GRID_4COL_ANY` greedy/non-overlapping regex fix in
`phase1_doc_one_shot_runner.py` (line ~23433) remains intact and NOT
reverted.

## Fix 3 — memmap prose RANGE constants (L8/L4 ingestion)

File: `phase1_doc_one_shot_runner.py`

Added a range-aware regex and a pure, testable helper:
- `_RE_MEMMAP_RANGE = 0x[0-9A-Fa-f]{1,8}\s*[-–—]\s*0x[0-9A-Fa-f]{1,8}`
  (ASCII hyphen + en-dash + em-dash).
- `_extract_memmap_range_constants(extracted)` scans extracted doc text
  line-by-line, and for each valid range (low < high) emits BOTH
  endpoints as L4 register-style constants with
  `kind="indexed_register_address"`, `endpoint` (low/high), `range`,
  `evidence` (source file) + `evidence_line` (verbatim source line).
  Inverted/equal pairs are skipped; endpoints deduped on address_int.
- Wired into `gen_l4_regmap()` after the table-row walkers, deduping
  against already-emitted register addresses so a range endpoint that
  coincides with a discrete register row is not duplicated.

No AI used — pure hex-range grammar.

## Fix 4 — ip_catalog_query SoC-top / structured-L2 matching

File: `ip_catalog_query.py`

4a) Scoped structured-L2 fallback + lowered confidence:
- `load_project_facts()` now also captures per-layer text into
  `facts["_layer_text"]` (keyed by bare layer id, e.g. "L2").
- For predicates keying on a STRUCTURED L2 field
  ({cpu_family, cpu_isa, cpu_arch, cpu_extensions, memory_topology,
  submodule_required}) with no discrete key, the `starts with` /
  `contains` branches now fall back to a keyword search SCOPED to the
  relevant layer section only — not the whole-doc `_full_text`.
- Substring-only hits are lowered: scoped `0.45`, full-text `0.3`,
  so they rank below structured discrete-key hits (`0.9`–`1.0`).

4b) depends_on auto-include + SoC-top preference:
- `query_catalog()` now transitively auto-includes a matched IP's
  `depends_on` IPs (pulled at threshold confidence) so the integration
  set is complete without manual help.
- `_is_soc_top()` heuristic detects an integration-top IP via explicit
  `top_module`/`is_soc_top` keys, `implements.architecture` containing
  soc/integration/chip-top, or an rtl_file matching
  `*_top|*_soc|chip_top|soc_top`. A small additive sort bias (`0.05`)
  ranks SoC-top IPs above leaf cores at equal/near confidence (bias
  only re-orders matched IPs, never promotes a non-match).

4c) Extension-negation guard:
- `_extension_excluded()` suppresses an ISA/extension "contains '<ext>'"
  rule when the spec is integer-only / no-FPU (for F/D/Q) or explicitly
  negates that extension ("no F", "without F", "F not supported", etc.).
  Verified load-bearing: a stray 'F' substring in "FPU"/"rv32i" would
  otherwise falsely fire the scoped fallback.

---

## Test results

Command:
`cd .../plugins/vibe-ic && python3 -m pytest programs/tests/ -q`

- Baseline (suite without new file): 1281 passed, 4 skipped, 1 xfailed,
  4 xpassed.
- With new tests: 1304 passed, 4 skipped, 1 xfailed, 4 xpassed.
- New file `test_orch_phase1_catalog_fixes.py`: 23 tests, all PASS.
- No NEW failures; skip/xfail/xpass counts unchanged.

New-test coverage: Path-B docs-mode decision + Path-A/skip cases (6),
input-mode detector raw-vs-layer-JSON (3), memmap range both-endpoints
incl. en/em-dash + inverted-skip (5), catalog scoped fallback +
no-cross-layer-leak (3), F-extension negation guard incl. real-F still
matches (3), SoC-top detection + preference + depends_on auto-include (3).
