#!/usr/bin/env python3
"""FX_LL21_DECLARED_OUTPUTS — steps 15 and 21 carry their declared outputs
whether or not the pre-stream gate admits the layout, and an empty router DRC
report has ONE answer.

MEASURED (spm x gf180mcuD, DIE deliverable, image 0.3.83, CMP3R_spm_fullchip
_status, 2026-09-28): the pre-stream gate failed (sta_record, antenna), and
steps 15 and 21 then FAILED `missing_artefact` for `pdn.done`,
`routed.drc.rpt` and `reports/phase3/drc_router.rpt` -- although the grid was
built (LibreLane's PDN step: 0 power-grid violations) and the route converged
(final `DRT-0199 ... = 0`).

ROOT CAUSE (reproduced here, and NOT specific to the LibreLane chain): all
three are written only by the POST-stream canonicalize pass. The pre-stream
pass returns before them, and the post-stream pass is skipped when the gate
fails -- the core-only DIRECT-path run that failed the same gate (N4,
2026-09-28) lacks the same three files. On the LibreLane path the PDN verdict
was also unreadable: `pnr.tcl` runs no `pdngen`, so the transcript carries no
`PDN_*` marker, and the old text would have said "NOT CONNECTED".

And the audit of a scope holding only EMPTY router reports said `read as
ZERO` at INFO and `No DRC violation categories` at ERROR about the same files.

chip-, PDK- and vendor-AGNOSTIC: synthetic fixtures only.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(PROG / "tests"))

from _ppa import power as P  # noqa: E402
from _hostpaths import require_repo  # noqa: E402

# LibreLane's detailed-routing log, as `openroad.log` splices it in
_LL_ROUTE_LOG = (
    "# >>> LIBRELANE OpenROAD.DetailedRouting phase3/librelane/21-route/"
    "05-openroad-detailedrouting/openroad-detailedrouting.log\n"
    "[INFO DRT-0195] Start detail routing.\n"
    "[INFO DRT-0199]   Number of violations = 12.\n"
    "[INFO DRT-0199]   Number of violations = 0.\n"
    "[INFO DRT-0198] Complete detail routing.\n")








# ── the declared outputs exist after a PRE-stream pass ─────────────────────























def test_checked_in_supply_defs_have_distinct_subjects():
    owned = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                         "programs", "calibration", "pg_supply_owned_negative.def")
    unowned = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                           "programs", "calibration", "pg_supply_unowned_positive.def")
    a, b = P._def_supply_subject_sha256(owned), P._def_supply_subject_sha256(unowned)
    assert a and b and a != b


def test_the_prestream_return_is_preceded_by_both_emitters():
    """Both outputs are produced BEFORE the `if prestream:` return, so a later
    edit cannot move them behind it unnoticed."""
    import ast
    tree = ast.parse((PROG / "phase3_one_shot_runner.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "step_canonicalize_artefacts")
    ret = [n for n in ast.walk(fn) if isinstance(n, ast.If)
           and isinstance(n.test, ast.Name) and n.test.id == "prestream"
           and any(isinstance(s, ast.Return) for s in n.body)]
    assert len(ret) == 1
    ret_line = next(s for s in ret[0].body if isinstance(s, ast.Return)).lineno
    calls = [(getattr(c.func, "id", None) or getattr(c.func, "attr", None), c.lineno)
             for c in ast.walk(fn) if isinstance(c, ast.Call)]
    for name in ("pdn_done_text", "_emit_router_drc_report", "emit_clock_plan"):
        assert any(n == name and ln < ret_line for n, ln in calls), name


# ── one answer for an empty router report ──────────────────────────────────
