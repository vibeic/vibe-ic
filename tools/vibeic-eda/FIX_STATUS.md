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

## Tools 3–5 — fork agents still running (klayout · magic+netgen[resumed] · iverilog+Verilator)
_updated as each lands + proof re-verified._
