# Corpus PERC sweep (Shape A) — RESULT (v0.2.11)

> Run-shape per `open-benchmark-methodology` §2 (A = full runner) + §4 triage rubric + §6
> RESULT sections. Corpus = the `benchmark_ic/` directory; control = a fresh full-runner re-run.

### Headline
The current **v0.2.11 Phase-3 PERC-equivalent sign-off chain is sound**. A fresh full-runner control
(spm re-run through `phase3_one_shot_runner.py` on the shipped plugin) **inserts 67 well/substrate-tap
cells and emits `PERC_EQUIV_PASS`**. The **14/14 `WELLTAP_GAP`** seen across the `benchmark_ic/`
corpus is **not** a current-runner defect — it is the well-tap presence check **correctly** flagging
real 0-tap latch-up exposure baked into **stale DEFs that predate the v0.1.46/v0.1.49
tapcell-insertion fix**. The ESD-presence `N/A 14/14` and the cross-voltage-domain `12 N/A + 2
INCOMPLETE` are likewise the honest, physically-grounded verdicts — not classifier misses.

### Corpus accounting (honest count)
**21 `benchmark_ic/` directories** (latest `4th__` generation: 13 + `2nd__`: 8). Of these,
**14 have a routed DEF** (swept) and **7 do not** (excluded honestly — the U_Hawaii_DeltaSigma
ADCs are analog; `2nd__ibex`, `2nd__neorv32`, `2nd__serv`, `4th__sha256_rerun`, `4th__spm`,
`4th__U_Hawaii` lack a routed DEF). Absence is reported, never a silent pass.

### Shape & tool substitution (mandatory disclosure)
- **Run-shape A** (full runner) for the **control**; a **deterministic structural DEF sweep** (the
  shipped pure functions run on each IC's existing routed DEF) for the **corpus arm** — the corpus
  arm is NOT a full-runner run, it measures check behavior on pre-existing DEFs.
- **No commercial PERC (Calibre PERC) was run** — environment-blocked. The PERC-equivalent chain
  uses open-source structural screens: antenna/IR/EM/floating AUTOMATED; ESD presence + topology;
  latch-up **well-tap presence** via a DEF COMPONENTS tap-cell scan; cross-voltage-domain via DEF
  power-domain resolution. ESD physics / latch-up device-physics / cross-voltage-domain confirmation
  are explicitly deferred to MANUAL and are NEVER reported as automated PASS.

### Corpus table summary (14 DEF-bearing ICs, 901→47503 components)
| Check | Corpus result | Verdict (§4) |
|---|---|---|
| Well-tap (latch-up tap presence) | 14/14 `WELLTAP_GAP` (0 valid taps despite thousands of placed std cells) | **STALE_ARTIFACT** (check correct) |
| ESD presence | 14/14 `N/A` (core macros, no chip pad ring) | **EXPECTED_NA** (honest) |
| Cross-voltage-domain | 12/14 `N/A` (single supply) + 2/14 `INCOMPLETE` (sha256_v2, sha256_v2variant — 0 power/0 ground resolvable) | **HONEST_DEGRADE** (correct) |

ICs swept: subservient, darkriscv×2, picorv32×2, VexRiscv×2, serv, ibex, sha256_v2,
sha256_v2variant, cv32e40p×2, neorv32.

### Fresh control (B) — DECISIVE, verified on disk
`/home/reyerchu/AI_IC_design/spm_benchmark_v0211/phase3/stage3/pnr/`: `floorplan.def taps=0` →
`placed/post_cts/post_hold/`**`routed.def all = 67`** (the `tapcell` step inserts them).
`_welltap_presence_check` on the routed DEF → `WELLTAP_PRESENT (n_tap=67)`. The
`reports/phase3/perc_equivalent.json` → **`verdict: PERC_EQUIV_PASS`**, with Antenna/IR/EM AUTOMATED,
Floating REVIEW, ESD `N/A (core macro)`, well-tap `WELLTAP_PRESENT`, x-domain `N/A (single supply)`.
The v0.2.6 real-SPEF SI coupling screen also fired in-runner (507 nets, max ratio 0.988, 86
coupling-dominated). This is the **first time the full PERC chain ran end-to-end inside the actual
runner on a freshly-generated benchmark IC**, and it passes.

### §4 triage of every finding
1. **Well-tap 14/14 `WELLTAP_GAP` → STALE_ARTIFACT (check value PROVEN).** The 0-tap is real
   structural truth (corpus DEFs carry thousands of `sky130_fd_sc_hd` std cells but literally 0
   tap-token masters). The **current runner inserts taps** — `_build_tapcell_tcl`
   (`phase3_one_shot_runner.py:529`) emits `tapcell -distance 14 -tapcell_master
   sky130_fd_sc_hd__tapvpwrvgnd_1`, ordered before `write_def placed.def` (header "v0.1.46"), wired
   via sky130A `PdkConfig`. Corpus DEFs are pre-v0.1.46 vintage. So the GAP is **not** a current
   runner bug and **not** a §4 Category-A-E benchmark FLOOR — it is the check **correctly**
   auto-FAILing a conclusive 0-tap latch-up exposure (zero substrate/well ties = categorical
   latch-up) that genuinely exists in those old artifacts. The check is general (NA/GAP/PRESENT
   trichotomy, PDK-allowlisted `_WELLTAP_RATED`, token regex `(?:^|_)tap(?:\d|_|$)` excluding
   bootstrap/captune, no literal chip names), presence-scoped (spacing → DRC deck, device-physics →
   MANUAL), 10 pytest cases.
2. **ESD presence 14/14 `N/A` → EXPECTED_NA (true honest-N/A row).** Grounded in physical fact:
   the corpus routed DEFs contain no pad-ring token (`fd_io|ef_io|gpiov2|_pad|clamp|hvc|lvc|_esd`);
   the populations are pure `sky130_fd_sc_hd` std cells. A core-only macro has no chip pad frame, so
   ESD has nothing to apply to (it is the top-level pad frame's responsibility). The code returns
   `N/A`, never a silent PASS, on 0 signal pads; pinned by `test_core_macro_is_na_not_pass` +
   `test_core_with_antenna_diode_is_na_not_padring`; independently shown to discriminate a real ring
   (Caravel `chip_io.def` 818-comp ring → ESD PRESENT/MANUAL) from a core macro
   (`community/PERC_REAL_CARAVEL_VALIDATION.md`).
3. **Cross-voltage-domain 2/14 `INCOMPLETE` → HONEST_DEGRADE backed by STALE_ARTIFACT.** Both
   sha256 routed DEFs have 0 SPECIALNETS, 0 `USE POWER/GROUND`, 0 VDD/VSS tokens across all stages
   (PDN never built). `_discover_power_domains` → resolved=False → `INCOMPLETE`. This is the v0.2.11
   contract ("resolved=False → INCOMPLETE, never silent N/A" — the explicit fix for the Caravel
   single-supply mis-count); claiming N/A would be a false single-supply over-claim. picorv32 /
   subservient resolve True via USE-keyword → genuine single-supply N/A, so the 12-N/A vs
   2-INCOMPLETE split is a real structural distinction. The 0-PG/0-tap sha256 pair are two facets of
   the same pre-PDN-flow staleness.

### Honest residual
- **No commercial PERC** ran; the chain is structural/open-source-equivalent and defers ESD physics,
  latch-up tap-spacing + device-physics (Vhold>Vdd, SCR β-product, guard-ring efficacy), and
  cross-voltage-domain confirmation to MANUAL. The well-tap PASS is NECESSARY-BUT-NOT-SUFFICIENT.
- **The 14 corpus DEFs are stale** (pre-tapcell-fix) and should be regenerated through the current
  runner before any of their PERC numbers are cited as a current-quality signal. The corpus arm
  proves check behavior at scale; it does not measure today's runner output — control B does.
- **7 of 21 ICs had no routed DEF** and were excluded — an honest absence, not a pass.

### Reproduce
- Control: `grep -c -i 'tapvpwrvgnd\|__tap'
  /home/reyerchu/AI_IC_design/spm_benchmark_v0211/phase3/stage3/pnr/routed.def` → 67; `verdict:
  PERC_EQUIV_PASS` in `.../reports/phase3/perc_equivalent.json`.
- Corpus staleness: `grep -c -i 'tapvpwrvgnd\|__tap'` over `benchmark_ic/*/phase3/stage3/pnr/*.def`
  → 0 across the 14 DEF-bearing ICs.
- Sweep driver: `/home/reyerchu/AI_IC_design/_perc_driver.py <ic_dir>` (runs the shipped pure
  functions); runner mechanism: `phase3_one_shot_runner.py` `_build_tapcell_tcl:529`, welltap
  `:5789`, xdomain `:4846`; pytest `tests/test_phase3_signoff_chain_organic.py`.

### Follow-up
A 2nd fresh control (subservient, 4th__ generation) is being run to confirm the 67-tap /
PERC_EQUIV_PASS result generalizes beyond spm; result to be appended.

---

## v0.2.36 REGEN — corpus DEFs regenerated through the current tapcell+PDN runner (2026-06-04)

The corpus-staleness residual (ORGANIC-20260601 suggested_fix #1/#2) is now CLOSED: all 14
DEF-bearing ICs were re-PnR'd through `phase3_one_shot_runner.py` (v0.2.36) inside the iic-eda
mount (`/foss/designs`; the main-checkout `benchmark_ic/` is NOT container-mounted, so regen
runs under `/home/reyerchu/AI_IC_design/vibe_ic_staged/`). Every regenerated `routed.def` now
carries real FIXED `sky130_fd_sc_hd__tapvpwrvgnd_1` well-tap placement records (was 0 across the
board — the stale pre-v0.1.46 artifacts). Tap counts (grep-verified on the actual routed.def,
not fabricated; DEFs stay gitignored):

| IC | welltap (was 0) | note |
|---|---|---|
| 2nd/4th cv32e40p | 11121 | PnR+tapcell complete; runner rc=124 only because post-route signoff exceeded the 1 h subprocess timeout (DEF is tap-bearing) |
| 2nd/4th darkriscv | 3900 | |
| 2nd/4th VexRiscv | 4751 | |
| 4th picorv32 | 5497 | 2nd picorv32 ≡ same IC |
| 4th sha256_v2 / v2variant | 6125 | |
| 4th subservient | 384 | first force-re-PnR proof (0→384) |
| 4th serv | 8379 | real top = `serv_chip_top` (not `chip_top`); re-ran with `--top-name serv_chip_top` |
| 4th ibex | 5952 | real top = `ibex_chip_top`; DRC 0 / antenna 0 after repair |
| 4th neorv32 | 32144 | real top = `neorv32_chip_top` (VHDL→GHDL→yosys netlist); 0 detailed-route violations |

The 3 ICs that first failed (serv/ibex/neorv32) did so only because the corpus runner defaulted
`--top-name chip_top` while their real synthesizable top differs — a wrong-default, NOT a
missing-RTL gap; correct `--top-name` regenerated them cleanly. The neorv32 SoC-class run also
surfaced + fixed a general plugin bug (`_docker_exec` bytes-on-TimeoutExpired → `TypeError` crash;
fixed by bytes→str normalization, +4 pytest, plugin 0.2.35→0.2.36).

Conclusion: the v0.1.46/0.1.49 tapcell+PDN fix is proven on EVERY corpus IC (0 → 384–32144 taps).
Future PERC sweeps over freshly-regenerated DEFs will read WELLTAP_PRESENT, not the stale 0-tap
signal. (The regenerated DEFs are runtime artefacts and remain gitignored; this table is the
committed record.)
