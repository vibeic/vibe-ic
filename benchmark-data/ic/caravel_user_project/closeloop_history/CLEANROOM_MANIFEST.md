# Caravel User Project — 7th Benchmark IC — Clean-Room Manifest

- **Benchmark IC #7:** caravel_user_project (joins bench6's ibex / opentitan_aes /
  sha256 / spm / subservient / u_hawaii_adc).
- **Upstream source:** https://github.com/chipfoundry/caravel_user_project @ main
  (b510613), Apache-2.0. Fresh shallow clone in `_src/caravel_upstream/`.
- **NOT inherited:** the prior `spm_pilot_v0144/caravel_work` checkout was the *spm*
  design packaged into a caravel wrapper — explicitly NOT used. This run uses the
  stock `user_proj_example` counter only.
- **Plugin version under test:** root tree `vibe-ic-marketplace/plugins/vibe-ic`
  (the tree the core-agent edits and `flow_compliance_check.py` audits).

## Shape (per open-benchmark-methodology §2)
**Shape A / D — full runner, SoC integration.** The design (a Wishbone/LA/GPIO
counter) is small; the benchmark value is the Caravel SoC integration + OpenLane
PnR + sign-off + mpw_precheck. Driven through `vibe_ic_one_shot_runner.py`, not a
hand-rolled harness.

## Clean-room blindness rules (§4.1)
- Phase 1 ingests ONLY `caravel/input/docs/L1-L9.md` (authored from the upstream
  README + RTL + Caravel harness facts) and `caravel/input/design_src/` (the stock
  upstream RTL + OpenLane config = the design's own spec).
- No prior run samples, no agent memory, no cached storage, no host scorer query
  mid-loop. AI judgment is used ONLY to recover a failing runner step (close-loop),
  and every recovery is captured via benchmark-enhancement-capture.

## Run command (root-tree runner, cwd = repo root)
```bash
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py \
    _bench7_caravel_v1034_cleanroom/caravel \
    --pdk sky130A --ic-name caravel_user_project \
    --top-name user_project_wrapper --die-um 2920x3520
```

## Acceptance (SOLE CRITERION, CLAUDE.md rule 11)
```bash
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py \
    _bench7_caravel_v1034_cleanroom/caravel --strict
```
Verdict ∈ {PASS, PASS_WITH_WAIVERS, FAIL}.

## Loop
run → capture chip-AGNOSTIC gaps → file ORGANIC backlog → core-agent fixes →
verify on real caravel → re-run, until no new capture AND no open backlog filed.
