# Step 2 — Lint (OUR RTL vs REF RTL)

**Verdict: BOTH-CLEAN** (OURS 0/0/0; REF 0 err, 1 benign WARN)

## What ran
1. `eda_lint` (Verilator 5.044, MCP container, strictness=error_only) on OURS and REF.
2. yosys `read_verilog; hierarchy; proc; opt; check -assert` on both.
3. `rtl_hygiene_lint.py` (plugin P0 hygiene checker) on both.

## Result
| Tool | OURS | REF |
|------|------|-----|
| Verilator | success, 0 errors, 0 warnings | success, 0 errors, 0 warnings |
| yosys `check -assert` | rc=0 (no latch/multi-driver/loop) | rc=0 |
| yosys warnings | 0 | 1 INFO (memory `w`→register list — REF uses `reg w[0:15]` array) |
| rtl_hygiene_lint | 0 errors, 0 warnings, 0 info | 0 errors, **1 WARN** unread-reg `mode_r` @ sha256_core.v:92 |

## Finding
Both lint clean. OURS is marginally cleaner: it has **0 warnings** of any kind,
whereas REF carries one harmless `unread-reg` warning (`mode_r` written but
never read) — this exactly matches REF's own stored
`reports/phase2/lint/rtl_hygiene.json`. OURS avoided the memory-inference info
by declaring the message window as 16 explicitly-named regs (`w0..w15`) rather
than a `reg [31:0] w [0:15]` array.
