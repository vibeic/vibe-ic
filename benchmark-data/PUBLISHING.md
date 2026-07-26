# Publishing converged evidence to `benchmark-data/ic/` — the canonical structure

This is **program-first**: every converged `(IC × PDK)` result is staged into one
canonical layout by a deterministic, chip-AGNOSTIC program and validated by a
companion gate. You do **not** hand-assemble an evidence folder, and you never
push a lone `RESULT.md` or a messy directory again.

Two programs own this (both under `plugins/vibe-ic/programs/`):

| program | role |
|---|---|
| `benchmark_evidence_publish.py` | **STAGES** a completed run's evidence into the canonical folder (excludes large files, generates `GDS_MANIFEST`, **refuses a non-converged run**). Stages only — it never commits. |
| `benchmark_evidence_structure_check.py` | **VALIDATES** any published folder against the rules below. Run it in CI (`--changed-since`) so a malformed publish is caught. |

## The canonical layout (one converged cell)

```
benchmark-data/ic/<IC>/
    input/                              # SHARED design input — staged ONCE per IC
        docs/                           #   the L* design documents (spec, not RTL)
    v<plugin-version>_<PDK>/            # ONE folder per converged (version × PDK)
        RESULT.md                       # independent-audit verdict (required)
        provenance.jsonl                # tool provenance (if the run produced it)
        phase1/generated_docs/          # the L* JSON design docs
        phase1/input_doc/  phase1/*.json
        phase2/stage1/                  # RTL
        phase2/stage2/synth/            # synthesis netlist + reports
        phase2/stage2/constraints/
        phase3/reports/                 # phase-3 rpt (drc/sta) — if present
        phase3/stage4/gds/GDS_MANIFEST.txt   # <name> <bytes>B sha256:<hash>
        reports/                        # reports/phase3 (drc/lvs/sta/ir/em/perc
                                        #   rpt+json), reports/{audit,orchestrator,
                                        #   phase1,phase2}
```

**Folder name = plugin VERSION first, then PDK** — e.g. `v1.5.66_gf180mcuD`,
`v1.5.65_sky130A`, `v1.5.58_ihp-sg13g2`. It is **not** prefixed with `pass_` /
`clean_run_` (the verdict lives in `RESULT.md`, and `clean_run_*` is a
`.gitignore`d prefix that would strip the committed phase folders).

### Excluded by construction

The raw geometry is **gitignored / too large** and is **never committed**:
`*.gds`, `*.def`, `*.spef`, `*.oas`. The streamed **GDS is instead recorded** as
`phase3/stage4/gds/GDS_MANIFEST.txt` — one line per GDS:

```
<filename> <bytes>B sha256:<64-hex>
```

so the GDS stays cryptographically verifiable without being stored. (Other
gitignored artifacts, e.g. `*.log`, are copied to the staged tree for local
inspection but git drops them at commit — the committed set stays clean.)

## How to publish

After a run reaches an **independently re-derived** Overall `PASS` /
`PASS_WITH_WAIVERS` and you have written its `RESULT.md`:

```bash
python3 plugins/vibe-ic/programs/benchmark_evidence_publish.py \
    --run-dir /path/to/completed_run \
    --ic <IC> --pdk <PDK> --plugin-version <X.Y.Z> \
    --dest-root benchmark-data
```

The program:

1. **Refuses to publish a run that is not converged.** It reads the machine
   verdict from the run's own
   `reports/audit/phase23_completion_audit.json` (produced by
   `flow_compliance_check.py --strict`). No audit artifact, a `FAIL` verdict, a
   missing/`FAIL` `RESULT.md`, or no streamed GDS → it **REFUSES** and stages
   nothing. A failing run can never be staged as if it passed.
2. Stages the canonical layout, excluding the raw geometry and generating the
   `GDS_MANIFEST`.
3. Stages the shared `ic/<IC>/input/` **once** (left untouched on the 2nd/3rd PDK
   for the same IC).
4. Runs `benchmark_evidence_structure_check.py` on the result as a **self-check**.
5. Prints the exact `git add` command — **but never commits.** Committing stays a
   deliberate human/agent act.

Then review the staged folder and commit it yourself.

## Validation (CI + local)

```bash
# one folder
python3 plugins/vibe-ic/programs/benchmark_evidence_structure_check.py \
    benchmark-data/ic/<IC>/v<X.Y.Z>_<PDK>

# every published cell in the tree
python3 .../benchmark_evidence_structure_check.py --tree benchmark-data

# CI shape — enforce ONLY the folders this push touched (pre-existing folders
# are grandfathered, so an unrelated PR is never failed by legacy evidence)
python3 .../benchmark_evidence_structure_check.py --tree benchmark-data \
    --changed-since origin/main
```

The gate enforces, per folder, each as a **named** nonconformance on failure:

- **NAMING** — basename is exactly `v<major>.<minor>.<patch>_<PDK>`; `clean_run_*`
  and verdict prefixes (`pass_*`/`fail_*`) are rejected with a specific message.
- **RESULT_PRESENT** / **CONVERGED** — `RESULT.md` exists, non-empty, and its
  verdict is `PASS` or `PASS_WITH_WAIVERS` (a `FAIL` run is not publishable).
- **PHASE1_DOCS** — `phase1/generated_docs/` present.
- **PHASE2** — `phase2/` present.
- **PHASE3_REPORTS** — `phase3/reports/` or `reports/phase3/` present.
- **GDS_MANIFEST** — `phase3/stage4/gds/GDS_MANIFEST.txt` present and every line is
  `<file> <int>B sha256:<64hex>`.
- **NO_RAW_GEOMETRY** — no `*.gds/*.def/*.spef/*.oas` **above the 50 MB commit
  ceiling** is committed under the folder (#419). Under it they SHIP: a 0.8 MB
  GDS is evidence a reviewer can open, and rejecting it by extension in order
  to avoid a 105 MB one failed all three reference cells while `.gitignore`
  accepted the very files they carry. Above the ceiling, route to git-lfs or a
  GitHub Release and keep the sha256 in `GDS_MANIFEST.txt` — which is required
  either way, and is what keeps an artefact verifiable without being stored.

chip-AGNOSTIC: the IC, PDK and version are parameters/path components; no IC / PDK
/ vendor / SKU literal appears in either program's logic.
