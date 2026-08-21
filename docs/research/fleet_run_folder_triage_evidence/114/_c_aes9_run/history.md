
---
## 2026-08-01 16:35:42 - User Prompt

> OWN opentitan_aes round 9. Fix the coverage.yml vs coverage.json/atpg_coverage.rpt producer/consumer mismatch (measured 50.7% held but gate reports 'no coverage evidence'). Establish which side is wrong and fix THAT side. Then take a full flow_compliance_check --strict verdict, report failure NAME SET.

---
## 2026-08-01 17:01:02 - Summary

Round 9 (opentitan_aes): Fixed the coverage.yml-vs-coverage.json producer/consumer mismatch. Established PRODUCER is the wrong side (its docstring declares coverage.json/atpg_coverage.rpt as outputs, so the gate is faithful). run_fault() now emits a durable stuck-at snapshot the moment stuck-at is measured (before the transition pass, independent of CLI main). Before/after on the real coverage.yml: dft_signoff measured_pct None ('no coverage evidence') -> 50.7316 ('below 95% floor'). PR vibe-ic#610 (version-less, RED-on-main negative control, ~2400 tests 0 regressions). flow_compliance --strict verdict: Overall FAIL; NAME SET FAIL={P0,11 DFT,FS1 FMEDA} MISSING={7,8,10,DT1} VACUOUS={D1,14}. FS1 VACUOUS->FAIL confirms r8 PR2 landed as v1.9.27. Output completeness gate: COMPLETE/exit 0.
