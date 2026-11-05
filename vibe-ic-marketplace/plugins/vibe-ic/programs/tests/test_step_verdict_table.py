"""R-0915-86 (1) — the shared table reader and the direction rule.

`_step_verdict_table` is the ONE place `real_ic_gate` and `audit_replay` turn a
compliance artefact into a per-step table and decide which way a step moved.
Two properties have to hold or both programs lie in the same way:

  1. BOTH artefact shapes read as the SAME table. `flow_compliance_check` writes
     `verdict`/`step_counts`/`command_argv` into
     `reports/audit/phase23_completion_audit.json` and `overall`/`counts` into
     the path given to `--json`, with an element-for-element identical `steps[]`
     (MEASURED 2026-09-16 on the frozen subservient_r26 snapshot: 69 steps,
     identical 18-key records, identical counts). A reader that knew one shape
     would read the other as a table with no verdict — i.e. would rank it
     NON_GREEN and report a catastrophic regression that never happened.

  2. The direction rule adds NO vocabulary. It is `verdict`'
     classification, which adjudicates BY SUBTRACTION so a word invented
     tomorrow lands somewhere without anyone remembering to come here. The
     load-bearing test below plants a word registered NOWHERE and requires a
     direction for it.

CALIBRATION (R-0915-86 (3)) is the pair of tests at the end: the differ must
FIRE on a planted flip and stay SILENT on an identical table. An instrument that
has not been shown to do both may not judge.
"""
from __future__ import annotations

import importlib







# ── 1. the two artefact shapes are one table ─────────────────────────────────







# ── 2. the direction rule is derived, not enumerated ─────────────────────────







# ── comparability: the refusal that keeps 69-vs-9 off the page ───────────────















# ── CALIBRATION (R-0915-86 (3)): fires on a positive, silent on a negative ───

_ARGV = ["flow_compliance_check.py", "/p", "--strict"]




















# ── R-0915-88: the RUN SHAPE axis ───────────────────────────────────────────
#
# THE ESCAPE THIS CLOSES, MEASURED 2026-09-16 BY USING THE GATE. The flow is
# program-first + AI-BACKUP: several steps complete only when an AGENT answers a
# hand-off. A published cell produced by an agent-driven lane run and a table
# produced by a program-only landing gate therefore disagree on those steps at
# EVERY tree — measured at six, spanning a ten-landing range and current main,
# with the tree never moving either verdict. Diffing the two printed "the IC
# regressed" about a landing that had done nothing, in a report a human read.
#
# The discriminator is DERIVED, never a per-step exception list: the run's own
# `gate_execution_ledger` records each gate's `exit_code`, and the AWAITING code
# is `flow_compliance_check`'s own constant for "pass two is somebody else's
# move". A tier invented tomorrow inherits this for free.
















# ── the chip-AGNOSTIC declaration these three files make, ENFORCED ──────────
#
# `source_chip_agnostic_check` READS a `CHIP_AGNOSTIC:` declaration and
# DISCLOSES it — its own docstring says so in as many words: "It does NOT
# enforce it: the program's own test is the lane that can refuse, and
# duplicating the refusal here would be two lanes with one rule between them."
# All three files of this change declare `strict-logic`, so this is that lane.
# It covers all three together because they land as one change and the middle
# one is the module the other two import.

_THIS_CHANGE = ("_step_verdict_table.py", "real_ic_gate.py", "audit_replay.py")


def _module_logic(path):
    """The file with its MODULE docstring stripped and nothing else — the exact
    scope `strict-logic` names. Every nested docstring and comment STAYS, which
    is where a literal would really hide."""
    import ast
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    body = tree.body[1:] if (tree.body and isinstance(tree.body[0], ast.Expr)
                             and isinstance(tree.body[0].value, ast.Constant)
                             and isinstance(tree.body[0].value.value, str)
                             ) else tree.body
    return "\n".join(ast.get_source_segment(text, n) or "" for n in body)






def test_the_guard_above_can_actually_see_a_planted_literal():
    """CALIBRATION of the guard itself (R-0915-86 (3)): an instrument that
    cannot fire proves nothing about the files it passed. A literal planted in
    a LOGIC position must be found, and the same literal in the module
    docstring must NOT be — that difference IS `strict-logic`."""
    chk = importlib.import_module("source_chip_agnostic_check")
    token_re = chk._build_token_re(["spm"])
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp(prefix="agn_"))
    planted = d / "m.py"
    planted.write_text('"""doc mentioning spm."""\nX = "spm"\n', encoding="utf-8")
    assert token_re.search(_module_logic(planted)), \
        "the guard cannot see a literal in the logic — it proves nothing"
    docstring_only = d / "n.py"
    docstring_only.write_text('"""doc mentioning spm."""\nX = 1\n',
                              encoding="utf-8")
    assert not token_re.search(_module_logic(docstring_only)), \
        "strict-logic must permit the docstring to name what it measured on"
