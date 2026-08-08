# opentitan_aes — sky130A — plugin `1.10.2 + 8c2527182`

## VERDICT: **NOT CONVERGED — RUN PAUSED IN PHASE 3 (RETAINED FAILURE / INCOMPLETE)**

This cell **must not be counted as a convergence**, and it is not publishable as one
regardless of what Phase 3 would eventually have returned. Two independent
disqualifying facts are recorded in §3 and §4. The run was wound down deliberately
(owner re-prioritisation to gate hardening), not because it failed at a specific gate.

- Plugin under test: **`1.10.2 + 8c2527182`** — NOT plain `1.10.2`. See §6.
- PDK: `sky130A` · Top: `chip_top` · IC class detected: `crypto_accelerator` (REUSED-IP path)
- Run dir: `192.168.1.114:/home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808/`
- Container: `vibeic-eda-otaes3`, image `ghcr.io/vibeic/vibeic-eda:0.2.76` (pinned `--require-image`)

---

## 1. Where the flow actually got to

| phase | verdict | note |
|---|---|---|
| Phase 1 | PASS | 28/28 L-docs, coverage 100% (curated + hands_on), 10/10 input docs read, 0 `__TODO__` |
| Phase 2 | **PASS_WITH_WAIVERS** | thin — see §3 |
| Phase 3 | **INCOMPLETE (paused)** | reached DFT: SAT-based **transition-delay-fault ATPG**; wound down after that step |

Real synthesis did occur: `yosys_synth PASS — netlist=netlist_yosys.v cells=94966
synth_top=chip_top frontend=yosys_slang` (11.8 MB netlist). **No PnR, no GDS, no
DRC/LVS/STA** — Phase 3 never reached them.

Phase 3 was stopped by an explicit graceful wind-down (`_ot_aes_run/winddown.sh`):
the in-flight ATPG batch was allowed to finish and the runner was then SIGTERM'd
**before it dispatched the next step**. No process was killed mid-solve.

---

## 2. Tool substitution / environment disclosure

- Synthesis: `yosys` + `yosys-slang` frontend (substituting a commercial SV frontend).
- LEC: `yosys equiv_*` ladder (`equiv_make` → `equiv_struct` → `equiv_simple` →
  `equiv_induct -seq 4/16/64`) on the flattened design, external SAT via `kissat`
  (each call capped at 180 s).
- ATPG: yosys-based TDF ATPG inside an ephemeral container that mounts the run dir
  at `/work` (`docker run --rm --name vibeic_tdf_<pid>_* -v <rundir>:/work`).
- All EDA work containerised; no commercial tools were used at any point.

---

## 3. DISQUALIFYING FACT (a) — Phase 2's `PASS_WITH_WAIVERS` is thin

The verdict rests on elaboration + manifests + gates. It does **not** rest on any
functional or equivalence evidence:

| claim | actual artefact |
|---|---|
| functional verification | **NONE.** `phase2/stage1/sim/results.xml`: `<verdict>CONNECTIVITY_PASS</verdict>` `<functional_verified>false</functional_verified>`, `capability_gap = cap:cpu_functional_oracle`. `pass.flag` = `CONNECTIVITY_PASS` (not `PASS`). |
| generated TB | `full_stack_tb_gen` SKIP — "CONNECTIVITY-ONLY skeleton (14 L9.top_ports → 14 DUT pins, **0 L3 opcodes driven**). Functional correctness UNVERIFIED" |
| unit TBs | `l10_unit_tb_gen` SKIP — L10 carries **103 verification cases**; none ran |
| reference TB | `reference_tb` WAIVED on class routing (`crypto_accelerator` / `generic_full_stack` / `half_duplex_bus=False`) — the AID half-duplex TB cannot bind this interface family |
| equivalence | `lec_equivalence` SKIP — **`verdict=INCONCLUSIVE` (RTL vs netlist.v, rc=0)** after ~75 min of yosys+kissat. Equivalence was NOT proven. |
| DFT / stuck-at ATPG | never ran in Phase 2 (`dft_scan_insertion` rc=2 → disclosed-skip) |
| gates inside the WAIVED `final_audit` | **3 FAILED**: `l8_clock_period_actionability_check` (rc=1), `l_doc_cross_consistency_check` (rc=1), `spec_review_lint` (rc=1) |

**The design brief's own oracles were never exercised.** `input/phase1_prompt.md`
names two hard oracles: §2 register-map conformance vs `input/golden/aes.hjson`, and
§6 NIST FIPS-197 / SP 800-38A vectors driven through the TL-UL register interface.
Neither ran. `input/golden/` is **absent by construction** — it was excluded at
staging to keep authoring blind (§4.05), which is correct for blindness but means
the register-map oracle cannot be scored from this run at all.

Credit where due: the runner did **not** fabricate a pass. The top-level
`sim/results.xml` reads `verdict: SKIP — "no substantiating reference-TB evidence —
refusing a verdict-only PASS (#433)"`. The anti-fabrication gates worked. The problem
is that a `PASS_WITH_WAIVERS` headline can still be read as convergence when
everything load-bearing underneath it is a SKIP or a WAIVE.

---

## 4. DISQUALIFYING FACT (b) — the provenance is contaminated

This run cannot represent a hands-off deterministic runner result:

1. **Parameterization was applied OUTSIDE the runner.** Between round 1 (ended 21:45)
   and round 2 (started 21:50:56), `phase2/stage1/rtl/chip_top.sv` was hand-edited:
   `SecMasking 1 → 0` and `SecSBoxImpl SBoxImplDom → SBoxImplLut`, leaving a
   `chip_top.sv.pre_glue_param_bak` backup. **No plugin program creates that backup**
   (`grep -r pre_glue_param` over the whole plugin returns zero hits).
   The *content* of the edit is spec-faithful — `input/phase1_prompt.md` §3 mandates
   "SecMasking 停用 (masking disabled, unmasked datapath)" and §4 names the expected
   work as "catalog-glue：選檔、參數化（`SecMasking=0`）". So this is **not** a design
   cheat. But it was performed by an agent, not by the runner, which makes the result
   agentic (catalog-glue-author handoff), not deterministic.

2. **Round 2 re-ran in a dirty directory.** The runner documented this itself:
   `SKIP reused_ip_consume — phase2/stage1/rtl/ already holds 126 RTL file(s) — a
   deterministic generator / author owns it; CONSUME skipped`. Round 2 inherited
   round 1's staged tree plus the out-of-runner `chip_top.sv` edit instead of staging
   its own.

Round 1, for the record, FAILED at `yosys_synth` with
`aes_sbox.sv:71: error: unknown module 'aes_sbox_dom'` — the vendor default
`SecSBoxImpl=SBoxImplDom` selects a module deliberately excluded from the staged input.

**Not** a contamination (checked and cleared): `input/vendor_rtl/aes/aes_sbox_dom.sv.unused-masked-scan-excluded`
is a pre-existing property of the staged benchmark input, not this session's doing —
it carries the same `2026-07-04 19:54:24` mtime as every other input file and appears
identically in ~10 unrelated run dirs on the host.

---

## 5. What a CLEAN re-run requires

1. **Fresh run directory** — never re-enter a dir that already holds a previous
   round's `phase2/stage1/rtl/`, or `reused_ip_consume` will SKIP and inherit it.
2. **Parameterization inside the runner** — the brief-mandated configuration
   (`SecMasking=0`, and the S-box implementation that follows from it) must be applied
   by the runner/catalog-glue program from the L-docs, not by an agent editing
   `chip_top.sv` after a failure. As long as a human/agent edits the wrapper between
   rounds, the number measures the agent, not the runner.
3. **Decide the functional oracle before starting.** With `input/golden/` withheld for
   §4.05 blindness there is no register-map oracle, and the class routing leaves
   `cap:cpu_functional_oracle` unfilled, so a re-run will again produce
   `functional_verified=false` unless a per-IC oracle TB is authored.
4. Expect Phase 3 to be long: 94,966 cells, SAT-based ATPG with 180 s-capped `kissat`
   calls, and a flattened-AES LEC that already returned INCONCLUSIVE once at ~75 min.

**Exact resume point**

| item | value |
|---|---|
| host | `192.168.1.114` |
| run dir | `/home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808/` (**dirty — do not resume in place**) |
| container | `vibeic-eda-otaes3` (image `ghcr.io/vibeic/vibeic-eda:0.2.76`) |
| plugin | **`1.10.2 + 8c2527182`** |
| invocation | `vibe_ic_one_shot_runner.py <fresh-dir> --container <c> --require-image ghcr.io/vibeic/vibeic-eda:0.2.76 --pdk sky130A --ic-name opentitan_aes --top-name chip_top` |
| stopped at | Phase 3 DFT — transition-delay-fault ATPG (step allowed to complete) |

---

## 6. Plugin identity — why the label is `1.10.2 + 8c2527182`

All 3528 deployed `programs/*.py` were hash-compared against the repo's `[v1.10.2]`
commit `3184ab1f2`. Exactly two files differ, and both match commit **`8c2527182`**
— *"fix(sta-rigor): sta_signoff_rigor_check only verified check_types COVERAGE, never
CONTENT [v1.10.3]"*:

- `sta_signoff_rigor_check.py` — repo v1.10.2 `6a2ac6ff…` vs deployed `80e5f1b4…` (= `8c2527182`)
- `test_sta_signoff_rigor.py` — likewise

Every blob traces to a landed commit; nothing was hand-edited. The deployed tree is
**v1.10.2 plus one landed v1.10.3 fix**, and because that fix changes an STA *signoff*
gate it is verdict-relevant. Reporting this run as plain "1.10.2" would be inaccurate.

---

## 7. Residual triage + carried-forward finding

| # | item | class | disposition |
|---|---|---|---|
| R1 | No functional oracle for `crypto_accelerator` class; TB is connectivity-only | plugin capability gap, **self-disclosed** by the runner as `cap:cpu_functional_oracle` | not filed — already disclosed by the plugin, not a new defect |
| R2 | `lec_equivalence` INCONCLUSIVE on flattened 94,966-cell AES | tool/scale limit | honest SKIP; not a floor claim |
| R3 | iverilog rejects `parameter logic [3:0] AES_PERMIT [35]` ("sorry: unpacked array parameters are not supported yet") and `parameter ctrl_reg_t CTRL_RESET = '{…}` | would be Category-D fork-fixable | **NOT filed.** In round 2 `reference_tb` was WAIVED on class routing and never attempted the compile, so there is no reproducible gap in this run's actual execution path. Filing it would be an unverified-gap PR. |
| R4 | `sdc_gen` clock-period provenance | **candidate false-certificate defect — see below** | not filed; needs verification against the code |

### R4 (carried forward — do not lose this)

`sdc_gen` reports **PASS** with:

> `emitted chip_top.sdc (NOTE: clock port(s) taken from L8's DECLARED clock contract: clk_i@20ns on 'clk_i')`

But `phase1/generated_docs/L8_RTL_CONSTANTS.json` declares **no period at all**:

```json
"clock_mhz": null,
"no_clock_mhz_in_input": true,
"clock_domains": [{ "name": "clk_i", "source": "synthesised-from-L9.top_ports",
                    "freq_hz": null, "freq_mhz": null, "period_ns": null }]
```

So a nominal 20 ns (50 MHz) is presented as *"L8's DECLARED clock contract"* when L8
declares `null`. Independently corroborating that the brief really is silent:
`input/phase1_prompt.md` states no clock period, and the staged reference SDC
(`input/reference_flow/pre_syn/aes.nangate.sdc`) carries only a driving-cell + load
spec, no `create_clock`. The only frequency literal anywhere in L8 is an
`auto_discovered_literals` entry of `100MHz` from `aes_README.md` — which is not 20 ns
either.

The deterministic gate **did** catch it: `l8_clock_period_actionability_check` returned
`rc=1 FAIL`. The concern is narrower and is about *reporting*: a step reports PASS while
asserting a provenance ("taken from L8's DECLARED clock contract") that its own L-doc
contradicts. That is the same **false-certificate family** as the gate work now being
prioritised — a check whose message claims more than its evidence supports. It is
recorded here rather than filed because it has not been verified against the `sdc_gen`
source; whoever picks up gate hardening should verify and, if confirmed, file it as a
chip-AGNOSTIC version-less PR with a §4.05 no-leak regression.

---

## 8. Check-in status

- **NO-MIX honoured**: this is a pure `benchmark-data/` record. No plugin or MCP file
  was modified by this run; no fix was bundled with a result.
- **Not pushed.** Committed locally only; landing is the gatekeeper's call.
- Nothing was published via `benchmark_evidence_publish.py` — that program refuses a
  non-converged run, and this run is correctly refused.

---

## 9. Artefact note — READ BEFORE USING THE JSONs

This record holds the small, high-value artefacts only (544 KB). The large ones stay
on the host: `phase2/stage2/synth/netlist.v` (11.8 MB) and `yosys.log` (8.8 MB) at
`192.168.1.114:/home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808/`.

**The two orchestrator JSONs come from DIFFERENT rounds — do not read them as one run:**

| file | round | verdict |
|---|---|---|
| `reports/orchestrator/vibe_ic_one_shot.json` | **round 1** (21:45, STALE) | `FAIL`, halted at phase2 |
| `reports/orchestrator/phase2_one_shot.json` | **round 2** (23:07) | `PASS_WITH_WAIVERS` |

Round 2 never wrote a top-level `vibe_ic_one_shot.json` because it was wound down
during Phase 3. There is therefore **no machine verdict for round 2 as a whole**, and
no `reports/audit/phase23_completion_audit.json` — so this cell is an *unaudited
record*, and any claim in this file is backed by the cited step artefacts, not by an
audit gate. That is stated here so the absence cannot later be mistaken for a pass.

`phase1/generated_docs/L8_RTL_CONSTANTS.json` is the primary evidence for the R4
finding in §7.
