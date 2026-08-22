# Method — how this run was produced, and how to reproduce it

Tree under test: `land/ppa-tf` @ `bb90724dc` (v1.11.32), unmodified. Nothing in
`vibe-ic-marketplace/plugins/vibe-ic/` was edited by this lane; every adaptation
lives under `ppa-e2e/tools/` and is named in `FINDINGS.md`.

## Environment

| | |
|---|---|
| EDA image | `ghcr.io/vibeic/vibeic-eda@sha256:24b5074b686386084f87a03712b5f76e475201fbf2f2583b112d6e2c3eb55f3d` (tag `0.3.13`) |
| place-and-route | OpenROAD `26Q3-1535-g543c33894f` |
| static timing / power | OpenSTA `2.7.0 f21d4a3878` |
| synthesis | Yosys `0.68+ 0048145dd` |
| sign-off DRC | KLayout, deck `/foss/pdks/sky130A/libs.tech/klayout/drc/sky130A.lydrc` |
| LVS | netgen, power-aware gate netlist |
| host | 32 cores, 125 GB RAM |

Each trial ran in its **own** container, created and destroyed around it, so the
CPU and peak-RSS figures come from that trial's own cgroup (`cpu.stat
usage_usec`, `memory.peak`) and belong to no other trial. Wall time is measured
around the runner invocation. Concurrency 8, `VIBEIC_OPENROAD_THREADS=3`.

## The two PDK refusals that came first, and why the run is on `sky130A`

The first invocation named the PDK explicitly and was refused:

```
[FAIL] phase3 PDK resolution REFUSED — resolved PDK contradicts the PDK this
       DESIGN declares.
  declared by the design : a PDK target recorded by Phase 1
  actually resolved      : gf180mcuD (open-source, in-container)
```

The design's own Phase-1 record says `pdk_target: "sky130"`
(`phase1/generated_docs/L19_CONSTRAINTS_PDK.json`). Rather than pass
`--allow-pdk-target-mismatch`, this run was moved onto the PDK the design
declares. `--pdk auto` was then refused a second time, because a commercial PDK
is configured for this host and an open-source fallback would have emitted
authoritative-looking sign-off reports under a false PDK belief. The runner's own
printed remedy — "re-run with an explicit `--pdk <oss-name>` if an open-source
run was intended" — was followed: `--pdk sky130A`.

**Both refusals were correct and both were useful.** They are recorded here
because a reader should know the run reached its PDK by being refused twice, not
by choosing one.

## Pipeline

```
phase3_one_shot_runner.py  --pdk sky130A --die-um D --util U --spare-density S
        |
        v   (per arm)
tools/extract_run.py       drives the SHIPPED library:
                             _ppa/backends/openroad.py  --run-dir  (physical)
                             _ppa/timing.py             --json     (per-view)
                             _ppa/power.py              power_document()
                             _ppa/backends/yosys.py     records_from_stat()
        |
        v
tools/adapt_records.py     F-4 re-wrap, F-9/F-10 collision resolution
tools/signoff_records.py   F-3 bridge: the nine-axis namespace
tools/gen_declaration.py   -> ppa_contract_build.py -> ppa_contract_check.py
        |
        v
ppa_feasibility_check.py   twice: shipped-records-only, and bridged
ppa_search_run.py          build manifest, then --verify it
tools/pick_winner.py       the declared objective, with every exclusion named
tools/head_to_head.py      -> ppa_head_to_head_check.py
ppa_report_gen.py          -> ppa_page_claim_check.py --cite-numbers
```

## Reproducing

```bash
# one arm
python3 programs/phase3_one_shot_runner.py <project> --top-name spm \
        --pdk sky130A --container <eda-container> \
        --die-um auto --util 0.30 --spare-density 0.02

# the sweep (60 points, 8 at a time, one container each)
cat ppa-e2e/search/trial_args.txt | xargs -P 8 -n 4 bash ppa-e2e/tools/run_trial.sh

# everything downstream
python3 ppa-e2e/tools/analyze.py
python3 ppa-e2e/tools/build_trials.py
python3 ppa-e2e/tools/pick_winner.py
python3 ppa-e2e/tools/head_to_head.py
```

`search/plan.json` fixes the candidate order: it is produced by the shipped
`_ppa.search.propose` at `seed=1121` over `search/space.json`, so the same space
and seed reproduce the same 60 points in the same order, with the baseline first.

## A note on the paths in the published records

Artefact paths in the records are as the producing tool reported them: relative
to the project root where the tool reported relative (`_ppa/timing.py`,
`_ppa/power.py`), absolute where it reported absolute
(`_ppa/backends/openroad.py`). They were not rewritten, because a `source.path`
that is not the path that was read is not provenance. That the absolute ones
carry a host home directory at all is the same shape as F-14.

## What this lane did NOT do

No GDS was hand-edited. No violating geometry was deleted. No pin was moved. No
rule deck was relaxed. No baseline was written with `--write-baseline`. No
`programs/` file was modified — the two places where a shipped module had to be
worked around (F-4, F-8) are worked around by CALLING it differently, through
hooks it already exposes, and both are written down.
