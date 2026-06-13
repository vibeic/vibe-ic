# Step 2 — Lint (OUR spm.v)

## What we ran
- `verilator --lint-only -Wall --top-module spm spm.v` in container iic-eda
  (Verilator 5.044) on OUR RTL.
- Plugin `rtl_hygiene_lint.py` and `rtl_signal_name_semantic_check.py` on OUR RTL (host).
- Same verilator lint on REF RTL for comparison.

## OUR result
- **verilator -Wall: CLEAN.** Exit 0, zero warnings, zero errors:
  `Verilator: Built from 0.032 MB sources in 2 modules ... ` `OUR_EXIT=0`.
  (An earlier run showed a single `DECLFILENAME` warning — that was purely because the
  staged copy was renamed `spm_ours.v`; with the real filename `spm.v` it is clean.)
- **rtl_hygiene_lint.py**: `0 errors, 0 warnings, 0 info` → `[]`, exit 0.
- **rtl_signal_name_semantic_check.py**: `verdict: PASS`, 0 warns (no active-low
  name / active-high value polarity mismatches).

## REF result
- verilator -Wall on REF RTL: **CLEAN**, `REF_EXIT=0`, zero warnings.
- REF stored lint reports `reports/phase2/lint/rtl_hygiene.json` = `[]` and
  `rom_init_lint.json` = `[]` → REF lint clean.

## Verdict: MATCH (both clean)
OUR and REF RTL are both 100% lint-clean under Verilator -Wall and under the plugin
hygiene/name-semantic auditors. MATCH.
