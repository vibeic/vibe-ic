# spm pilot — chipignite signoff waivers

Two waiver entries documenting the **2 of 7 precheck FAILs** that
remain after the Phase C cleanup pass (5 → 2 FAIL). Both are validated
by the plugin program `programs/signoff_waiver_emit.py` (33 pytest
cases) and conform to the chipignite-submission shape it codifies.

## What's here

| File | Failed check | Reason class | Risk |
|---|---|---|---|
| `consistency_layout.json` | `Consistency` (LAYOUT sub-check) | `blackbox-macro-signoff-limit` | medium |
| `xor_blackbox.json` | `XOR` (30 deltas vs stock empty) | `stock-empty-vs-user-content-xor-delta` | low |

5 of 6 Consistency sub-checks PASS (ports, complexity, modeling, power
connections, port types). The LAYOUT sub-check is a hard-macro
limitation. The XOR delta IS the user content the submission is meant
to add — empirically confirmed by the Phase B PnR (0 DRC, 0 antenna,
384 well-tap cells, 2229 decap cells, WNS 0.0 ns).

## Why a waiver (and not a fix)

Path-1 (flatten flow) and path-2 (LEF-with-obs) were empirically
attempted in the pilot:

- **Path 1 (flatten)** — 5 escalating attempts; **closes Consistency
  LAYOUT** (proved at attempt 4) but hits TritonRoute `DRT-0302
  Unsupported multiple pins on bterm vccd1` at Caravel's intentional
  multi-bterm power-net design. NOT a fixable config — it's at Caravel's
  design intent. See `PHASE_C_FLATTEN_EXPERIMENT.md`.

- **Path 2 (LEF-with-obs)** — regenerated spm.lef with
  `write_abstract_lef -bloat_occupied_layers`. Does not move precheck
  XOR delta because Phase B streams the macro `spm.gds` (not the LEF
  abstract) into the wrapper area. The wrapper GDS bytes don't change.

- **Path 3 (waiver)** — the industry-standard path for hard-macro
  Caravel user projects. eFabless reviewers consume the waiver as
  policy.

The 2-of-7 FAIL count is **the empirical open-source-flow Caravel
hard-macro signoff floor**, and waiver is the practical chipignite
route.

## Schema

Generated and validated by `signoff_waiver_emit.py`:

```jsonc
{
  "id":               "<project>__<check>__<sha256[:8]>",  // auto, stable
  "project_name":     "spm",
  "failed_check":     "<one of CHIPIGNITE_PRECHECK_FAIL_NAMES>",
  "sub_check_detail": "<optional free text>",
  "reason_class":     "<one of REASON_CLASSES>",
  "mitigation":       "<>= 40 chars; no TODO/FIXME>",
  "evidence_files":   ["<paths>"],
  "expected_remediation_path": "<free text>",
  "risk_assessment":  "low | medium | high",
  "risk_justification": "<required if medium/high; >= 40 chars>",
  "approver":         "<real id, NOT 'ai'/'agent'/'self'>",
  "signed_at":        "<YYYY-MM-DD, auto>",
  "emitted_by":       "<auto>"
}
```

## Validate

```bash
PLUGIN=vibe-ic-marketplace/plugins/vibe-ic
for f in *.json; do
  echo "=== $f ==="
  python3 $PLUGIN/programs/signoff_waiver_emit.py \
      --project-name x --failed-check x --reason-class blackbox-macro-signoff-limit \
      --mitigation x --approver x \
      --validate-only --strict < "$f" && echo OK
done
```

## Provenance

| Item | Source |
|---|---|
| Emitter program | `vibe-ic-marketplace/plugins/vibe-ic/programs/signoff_waiver_emit.py` (v0.1.49) |
| Schema tests | `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_signoff_waiver_emit.py` (33 cases) |
| Pilot evidence | `benchmark_clean/spm_pilot_v0144/{RESULT_tier4_lvs.md, caravel_integration/PHASE_*.md}` |
| External-review confirmation | LVS net-level analysis (Chinese) cross-walked in `RESULT_tier4_5_v0149_supplement.md` |

## For a chipignite reviewer

Read this README first. Each waiver file is independently validatable;
both reference the pilot writeups for orthogonal evidence. The
remediation paths column shows what a real submitter would do given
commercial tooling or a non-blackbox-macro flow. No silent gaps; every
PASS came from real PnR, every FAIL is decomposed with cited evidence.

End of waiver package.
