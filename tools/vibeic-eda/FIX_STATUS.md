# vibeic-eda — 48-fix program status

Live scoreboard for the OSS-EDA fork initiative (`OSS_EDA_FORK_ROADMAP.md`). Every
`DONE` row has a reproducible FAIL→PASS proof that the repo-gatekeeper re-ran and
verified before integrating into `vibeic-eda`. `ADOPTED` = closed by adopting the
current upstream tree (roadmap was against an older version); proven working, no
custom patch. `DEFERRED` = algorithm-hard research port, honestly not attempted/
partial. `EXTERNAL` = a fork genuinely cannot manufacture (foundry data).

Legend: ✅ DONE-proven · 🟢 ADOPTED-proven · 🔷 DEFERRED(algorithm-hard) · ⚪ EXTERNAL

## Tool 1 — OpenROAD  (fork: vibeic/OpenROAD, built native, in vibeic-eda:0.1.0)
| Fix | Class | Status | Proof (gatekeeper-verified) |
|---|---|---|---|
| post-detailed-route repair on real parasitics: Signal-11 crash-fix + `-detailed_routing` flag + kDetailedRouting→Steiner | algorithm-hard | ✅ | sha256 routed/ss/OpenRCX: stock segfaults; patched repair 8 resized+4 buf, max-slew **289→0**, exit 0 |
| repair_design pass-2 segfault (ECO re-run on buffered netlist) | bug-fix-easy | — | **non-reproducible** on current build (double repair_design → PASS2_DONE_NO_CRASH, exit 0); no fix needed on this version |
| in-flow reroute to realize inserted buffers | algorithm-hard | 🔷 | TritonRoute can't re-route an already-routed design (DRT-0626/1010, with+without repair); needs `src/drt` incremental-ECO. Capability ships for manual ECO; not wired into auto-flow |
| RSZ-0089 wire-rc abort, DPL-0033 check_placement abort, DRT-0305 constant-PG abort | easy/medium | 🔷 | lower-priority severity-reclassifications the plugin already `catch`-wraps; deferred behind higher-value work |

## Tool 2 — yosys + abc  (fork: vibeic/yosys @ vibeic/synth-fixes, commit c5c8f65d8)
| Fix | Class | Status | Proof (gatekeeper-verified) |
|---|---|---|---|
| tri-state fanin preservation (implicit `tribuf -logic` in `synth`) | feature-add-medium | ✅ | `assign io=oe?val:'z`: stock→`assign io=val` (oe dropped); patched→**4× `$_TBUF_ .E(oe)`**; 137/137+99/99 no-regress |
| slang duplicate-module source-located diagnostic + nonzero rc | bug-fix-easy | 🟢 | modern yosys bundles slang: two `module foo`→`error: duplicate definition of 'foo'` +note, RC=1 |
| `$readmemh` ROM init propagation | feature-add-medium | 🟢 | modern tree maps ROM init to correct logic (DE/AD/BE/EF), not always-X |
| unpacked-array ports auto-flatten | feature-add-medium | 🟢 | `read_slang` flattens `logic[7:0] foo[0:3]`→`output[31:0] foo` (legacy `read_verilog -sv` rejects) |
| cross-file `import pkg::*` / StateEnumT | feature-add-medium | 🟢 | `read_slang` builds FSM across files (even reverse order); legacy path syntax-errors |
| abc D-latch mapping · carry-chain/prefix-adder · equiv SEC closure | algorithm-hard | 🔷 | research ports, deferred |

## Tool 6 — ngspice  (fork: vibeic/ngspice @ vibeic/batch-honesty, commit c89de02)
| Fix | Class | Status | Proof (gatekeeper-verified) |
|---|---|---|---|
| `-b` batch honesty: nonzero rc + per-`.measure` PASS/FAIL marker | feature-add-medium | ✅ | failed `.meas`: stock→`failed!` **RC=0** (silent CI pass); patched→`;;MEAS vbogus FAIL` **RC=1** — re-run by gatekeeper on stock vs patched binary |
| `$&<measvar>` scalar → length-1 vector | bug-fix-easy | ✅ | `$&vpk`: stock `no such variable`/empty → patched `0.999952` |
| control-mode `.param` expansion (`tran`/`meas at=`) | feature-add-medium | ✅ | `tran … tend`: stock `TSTOP invalid` RC=1 → patched runs RC=0 |
| native Monte-Carlo (`mc N var:lo:hi`) | feature-add-medium | ✅◐ | stock `mc: no such command` → patched 20-run mean/σ/min/max/yield; **PARTIAL**: control-mode command not `.mc` dot-card, plain MC (no LHS/Sobol) — honestly flagged |
| DC homotopy for floating SC nodes · AMS co-sim bridge | algorithm-hard | 🔷 | research ports, deferred |
| PATH packaging | bug-fix-easy | ⚪→build | belongs in vibeic-eda Dockerfile, not ngspice source |
| Build: MAKE_EXIT=0, `make check` 57/58 (1 fail = env graphics, identical on stock → 0 regressions) |||| 

## Tool 4 — magic + netgen  (fork: vibeic/{magic,netgen} @ vibeic/lvs-fidelity)
netgen commits 29852b6+b7d4138 · magic commit 82d8fb33 · both pushed
| Fix | Tool | Class | Status | Proof (gatekeeper-verified) |
|---|---|---|---|---|
| `Final result:` reflects transistor-property errors | netgen | bug-fix-easy | ✅ | **re-run by gatekeeper**: R=1k vs 2k → stock `Circuits match uniquely` (silent LVS false-pass!) → patched `do NOT match uniquely (property errors present)` |
| portless top-cell guard (non-proxy port count) | netgen | bug-fix-easy | ✅ | portless `.subckt`: stock `match uniquely` → patched `do NOT match (no ports to anchor)` |
| `-auto-global` (derive globals from `.global`) | netgen | feature-add-medium | ✅ | `.global` one-side: stock `failed pin matching` → patched `match uniquely` |
| `-nopower="…"` PG-as-global | netgen | feature-add-medium | ✅ | caller-named PG nets: baseline mismatch → patched `match uniquely` |
| black-box leaf positional pin match (+`&&`→`&` typo) | netgen | feature-add-medium | ✅ | defined-vs-stub leaf: stock `failed pin matching` → patched `match`; 3-pin stub still fails (negative control) |
| `ext2spice` label→port promotion (`port makeall` default on) | magic | feature-add-medium | ✅ | scmos NMOS: stock `.subckt top` (empty) → patched `.subckt top DRN SRC Gnd GATE` — feeds netgen portless guard |
| `def/gds read` RECT-null crash | magic | bug-fix-easy | 🟢 | already fixed upstream in 8.3.671 (proven: RECT-before-LAYER reads RC=0, no segfault) |
| unknown-layer→retain · NDR-via `def read` · SPECIALNET power-name propagation | magic | easy/medium | 🔷 | honest DEFERRED — fix-sites located (`defRead.c ~478/530`, ext2spice substrate node); need heavy OpenROAD DEF+LEF repro, not shipped unproven |

## Tool 5 — iverilog + Verilator  (fork: vibeic/iverilog @ vibeic/sv-tb-coverage)
iverilog commits e1e12f6+110cadd · pushed · verilator forked, no commit (no honest fix — reported)
| Fix | Tool | Class | Status | Proof (gatekeeper-verified) |
|---|---|---|---|---|
| `->>` nonblocking-event: `-t null` elaborates but vvp codegen segfaults | iverilog | bug-fix-easy | ✅ | **re-run by gatekeeper**: event referenced only by `->>` → stock **SEGFAULT rc=139** → patched compiles rc=0 + `hits=2 PASS` (3 root bugs: nodangle nb-trig, stale `sorry`, schedule_propagate); full suite SV 902/908 + Verilog 1765/1768 **0 regressions** |
| comp-unit package-before-import ordering (driver hoists pkg-declaring files) | iverilog | feature-add-medium | ✅ | use-before-decl: stock `syntax error/Invalid module item` rc=2 → patched `WIDTH=16 PASS`; comment/string-skip negative control holds |
| full-array assignment-pattern `'{...}` | iverilog | feature-add-medium | 🟢 | already upstream in v14.0-devel (proven on stock: decl-init + procedural PASS) |
| `break;`/`continue;` in loops | iverilog | feature-add-medium | 🟢 | already upstream (proven: `sum=4 PASS`) |
| downgrade BLKLOOPINIT/WIDTH/LATCH/COMBDLY | Verilator | bug-fix-easy | ⚪ | **obsolete on v5.051** (honest): each already `-Wno`-suppressible; BLKLOOPINIT's only trigger is also rejected by iverilog → downgrading would emit silently-wrong sims. No honest fix → no patch |
| event-driven `--timing` scheduler · Verilator CDC/NBA region parity | both | algorithm-hard | 🔷 | research ports, deferred |

## Tool 3 — klayout  (fork: vibeic/klayout @ vibeic/streamout-fixes, commit b82b6e9)
| Fix | Class | Status | Proof (gatekeeper-verified) |
|---|---|---|---|
| foundry layer-map instead of compact 1..N fallback | feature-add-medium | ✅ | **re-run by gatekeeper**: stock `met1.PIN=1/2` (Magic-unreadable, breaks LVS) → patched+map `met1.PIN=68/16`, `via1=67/44`, `met1.NET=68/20` (real sky130 layer/datatypes) |
| honor tech-LEF `MANUFACTURINGGRID`, snap instance + via coords | bug-fix-easy | ✅ | **re-run by gatekeeper**: `OFFGRID_VERTICES 8 → 0` (vs 5nm grid); no-op on grid-legal geometry (default-ON, 90/90 tests pass) |
| merge-abutting streamout (union same-layer polys across instances) | feature-add-medium | ✅ | met1 abutting polys `2 → 1` (opt-in `KLAYOUT_LEFDEF_MERGE_ABUTTING=1`); deferred to `finish()` to avoid dangling-`db::Cell*` SIGSEGV |
| Regression: `dbLEFDEFImportTests` 90/90 pass, identical stock vs patched; each fix's OFF path reproduces stock exactly |||| 
