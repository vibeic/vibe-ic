# SOURCE_MANIFEST — run_v1333_knowledge_converge

## Attribution

| Artifact | Origin | GENERATED vs REUSED |
|---|---|---|
| `records/<pid>.json` | CVDP HF v1.1.0 `nonagentic_code_generation_no_commercial` split (302-record dataset), per-record extract | REUSED-DATASET (verbatim record incl. harness) |
| `prompts/<pid>/prompt.txt`, `prompts/<pid>/context/**` | `input.prompt` + `input.context` of each record | REUSED-DATASET (verbatim, the blind-author inputs) |
| `drafts/base/<pid>/rtl/*.sv` | blind AI author, current plugin, reads prompt(+context) ONLY | GENERATED (this run) |
| `drafts/enh/<pid>/rtl/*.sv` | blind AI author + general self-verification discipline, prompt(+context) ONLY | GENERATED (this run) |
| `drafts/ctx/<pid>/rtl/*.sv` | unmodified `input.context` RTL, staged for the scrambler_0018 FLOOR-evidence replay | REUSED-DATASET (verbatim context, diagnostic only) |
| `drafts/sanity/…hamming_0001` | scorer-validation draft authored directly from the fully-specified prompt | GENERATED (this run) |
| `score.py`, `manifest.py` | this run's harness (stages record harness + draft into `cvdp-sim-pinned:latest`, runs official `pytest test_runner.py`) | GENERATED (this run) |
| `direct/<arm>_<pid>/` | per-run staged tree + `pytest.log` from the official harness | GENERATED (this run, scorer output) |
| `scores/{base,enh,ctx}_verdicts.txt` | aggregated PASS/FAIL verdicts | GENERATED (this run) |

## Oracle usage (honesty)

- **Authoring (§4.05):** every `base`/`enh` draft read ONLY `input.prompt` (+
  `input.context` for cid002/004/007/016 transform tasks). No draft read the
  record JSON, `src/` harness, `test_*.py`, or any other problem's files.
- **Diagnosis (§3.9 oracle-for-RCA):** the test harness (`test_*.py`) was read by
  the ORCHESTRATOR (not the authors) only to characterize the residual fails for
  triage. No harness literal was fed back into any author.
- **Golden:** stripped from the open slice (empty `output`) — not available for
  authoring or FLOOR-proof.

## Chip-agnostic / no-cheat

No plugin/MCP source was modified in this run. No version-less PR was filed (0/3
demonstrated lift; the residual fails are dataset floors, not plugin gaps). Nothing
outside `benchmark-data/` is touched.
