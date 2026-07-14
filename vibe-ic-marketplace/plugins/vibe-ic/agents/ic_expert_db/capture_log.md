# IC Expert DB — capture log

Append-only chronological record of lessons filed into `ic_expert_db.json` via
`programs/ic_expert_db_capture.py` (the gated dialogue write-back). One line per
capture, newest at the bottom:

```
## [<ISO-8601>] capture | source=<dialogue|closed-loop> ic_class=<class> | VALIDATED(consistency+deny) | <lesson snippet>
```

Every logged capture passed `ic_expert_db_consistency_check` (blindness / oracle /
gate-override / structural) + a chip-deny-token scan BEFORE it was staged, and was
then reviewed as a git diff by the repo-gatekeeper. This file is the DB's provenance
trail (the Karpathy LLM-Wiki `log.md`) — it is never rewritten, only appended.

<!-- captures below -->
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=functional-modification-delivery | VALIDATED(consistency+deny) | When a modification task asks you to ADD a new module or feature to an EXISTING provided f
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=reset-interface-defaults | VALIDATED(consistency+deny) | When a spec mentions a reset without stating polarity or synchrony, take the convention fr
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=output-latency-defaults | VALIDATED(consistency+deny) | 'Registered output' means EXACTLY one clock of latency: the result of inputs sampled at ed
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=bit-ordering-endianness-defaults | VALIDATED(consistency+deny) | When a spec serializes a word or packs fields without stating bit order, resolve it in thi
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=handshake-valid-ready | VALIDATED(consistency+deny) | While valid is asserted and ready is low, HOLD the payload and valid stable: never advance
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=handshake-valid-ready | VALIDATED(consistency+deny) | When a spec calls a flag a 'pulse' or says it is 'asserted for one cycle' (done, error, ca
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=bus-interface-defaults | VALIDATED(consistency+deny) | Unless the spec says otherwise, every declared output must carry a DEFINED value at every 
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=arithmetic-signedness-defaults | VALIDATED(consistency+deny) | When a spec does not state signedness, operands are UNSIGNED by default; switch to signed 
## [2026-07-14] capture | source=issue-139 owner-directed distill (v1.4.14 clean-run) ic_class=bus-interface-defaults | VALIDATED(consistency+deny) | When a verbatim code header/skeleton (module declaration, port list, parameter list) CONFL
## [2026-07-14] governance-cleanup | source=issue-139 owner adjudication | ORACLE-SOURCE ban | REMOVED iterative-training-datapath "harness-toplevel-alias rule" (instructed reading the scorer-side .env TOPLEVEL/VERILOG_SOURCES — a forbidden oracle read, never honest experience)
## [2026-07-14] governance-cleanup | source=issue-139 owner adjudication | id-slug naming REJECTED | fsm-controller lesson rewritten craft-only (the "bind the top name to the design<problem-slug>/id" half is a dataset naming convention, not spec-alone design experience — under-specified names stay an accepted floor); two multi-file lessons re-keyed from VERILOG_SOURCES to the task/prompt file enumeration; bus-interface-defaults table-vs-skeleton tail aligned to header-wins. Structural guard added: ic_expert_db_consistency_check ORACLE-SOURCE regexes + test_issue139_expert_db_oracle_source_guard.py.
