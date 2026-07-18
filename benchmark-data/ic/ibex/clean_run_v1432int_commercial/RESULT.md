# ibex — real-node re-verify (clean_run_v1432int_commercial)

- **Design:** lowRISC Ibex RV32IMC core (reused-IP), documented 'small' config
  (2-stage pipeline, RV32MFast 3-cycle mult, no I-cache, FF register file,
  machine-mode only).
- **Toolchain image:** vibeic-eda 0.2.20-int (image id fa8cb832daf2).
- **PDK:** commercial 180nm (staged out-of-repo by path; NDA — never committed).
- **Baseline compared against:** vibeic-eda 0.2.19.
- **Entry:** `/vibe-ic-all` (Phase 1 → Phase 2) + direct Phase 3.
- **RTL path:** REUSED-IP (catalog-glue-author) — vendor SystemVerilog closure
  staged into `phase2/stage1/rtl/` + AI-authored `chip_top` wrapper (dual
  reset/clock variant). A duplicate-module defect (`prim_clock_gating`,
  `prim_assert`) in the nested vendor subdirs was pruned so the synth closure is
  single-definition.
- **DRC engine:** native SVRF. **LVS engine:** KLayout-native.

---

## Headline A/B — functional-LEC slang gold-read (the 0.2.20-int enhancement)

Numbers taken ONLY from `reports/lec.json` structured fields and a controlled
`read_slang` probe — never from any cell-level report.

| metric | 0.2.19 baseline | 0.2.20-int **as-run (plugin)** | 0.2.20-int **read_slang (forced probe)** |
|---|---|---|---|
| gold-read frontend | read_verilog -sv | read_verilog -sv | read_slang (SV-2017) |
| compared_points (miter) | 0 | **0** | **2141** |
| verdict | FAIL (false) | FAIL (false) | real miter built |
| gold_frontend field | verilog | verilog | slang |

**Honest reading:** as-run by the plugin, ibex is **STILL a false-FAIL** —
`compared_points = 0`, `gold_frontend = verilog`. **NO flip; the 24-step
downstream cascade is NOT unblocked as-run.**

**But the image capability is present and functional:** forcing the gold read
through `read_slang` elaborates the ibex SV closure (package enums, unpacked
arrays) and `equiv_make` builds a **real 2141-point miter** — i.e. `0 → 2141`
compared points — versus the built-in `read_verilog -sv` reader's 0-point
false-FAIL. So the enhancement works; it is simply **not being triggered** for
this design.

**Root cause — chip-AGNOSTIC plugin trigger gap (NOT an image gap):**
`lec_run.is_frontend_parse_abort()` only recognizes syntax / `TOK_*` /
"failed to parse" signatures. On ibex the built-in reader parses the syntax fine
but aborts at **elaboration**:
`chip_top.sv:85: ERROR: Parameter u_ibex_core.RV32M with non-constant value!`
(an SV package enum used as a parameter value). That signature is absent from the
regex, so `is_frontend_parse_abort` returns False, the
`parse_error && is_frontend_parse_abort` retry gate is never taken, `read_slang`
is never attempted, and the verdict falls through to a false FAIL.

**Fix status:** the plugin trigger gap is being fixed back into the plugin
(widen `is_frontend_parse_abort` to include elaboration-abort signatures, e.g.
"Parameter … with non-constant value" / package-scope elaboration aborts) with a
no-leak negative proof, so the slang retry fires for this signature class. No
plugin edits were made from this re-verify run.

---

## Six-pillar status

| pillar | status | notes |
|---|---|---|
| 1. Functional verification | N/A-as-emitted | processor_cpu / generic_full_stack track emitted a CONNECTIVITY-ONLY top TB (30 top ports → 30 DUT pins, 0 opcode vectors) — no functional pass-rate number. |
| 2. LEC / equivalence | see headline | as-run false-FAIL (0 pts); capability proven present (read_slang → 2141-pt miter). |
| 3. Synthesis | PASS | yosys produced a real mapped netlist after the duplicate-module prune. |
| 4. STA (signoff) | INCOMPLETE | only the intermediate post-hold hold-timing stage was reached — **hold: MET**. Final signoff worst-slack not produced (see Phase 3 note). |
| 5. DRC / LVS | INCOMPLETE | not reached — GDS streamout did not complete (see Phase 3 note). |
| 6. Dynamic IR-drop | INCOMPLETE | not reached — depends on routed DEF + SPEF that did not complete. |
| Analog | N/A | pure-digital core. |

### Phase 3 completion note (why backend pillars are INCOMPLETE)

Phase 3 ran the full PnR: floorplan → placement → CTS → hold-fix (hold MET) →
detailed routing **completed** (`routed_preantenna.def` produced). The run then
entered post-route (antenna repair / final route) and did **not** produce the
final `routed.def` / GDS / sign-off DRC/LVS/STA/IR within the wind-down window;
the run was bounded (terminated) to quiesce the tree for the release clean-pass.
Die auto-sized to 1045 × 1045 µm; 13663 placed cells; target util 0.25.
Consequently the DRC-count / LVS-verdict / final worst-slack / dynamic-IR mV
A/B numbers are **not available** from this run.

- AUP-skipped (cell-level detail, NDA-excluded): per-cell LEC point list, sign-off
  netlist cell names, layer/rule DRC detail — none read, none compared.

---

## Verdict

- **Primary A/B (LEC slang gold-read):** delivered and definitive — as-run **no
  flip** (plugin trigger gap), capability **proven present** (0 → 2141-point
  miter under forced read_slang). Fix dispatched into the plugin.
- **Backend pillars (DRC/LVS/STA/IR):** not delivered — Phase 3 sign-off did not
  complete within the wind-down window.
- **Overall:** FAIL as-run (LEC false-FAIL cascade + incomplete Phase 3), with
  the root cause diagnosed to a fixable chip-agnostic plugin gap.
