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
