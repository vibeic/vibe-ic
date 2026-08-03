#!/usr/bin/env python3
"""Step 21 — the router-DRC gate whose verdict came from step 31's report.

THE DEFECT. `eda_report_audit._discover` is a project-wide `rglob` with no
relationship to the step whose gate is asking. Step 21 ("Routing") declares
`phase3/stage3/pnr/routed.drc.rpt`; step 31 ("Physical Verification") declares
`reports/phase3/drc_signoff.rpt`. Both run `--mode drc`, so both saw every DRC
report in the project.

MEASURED on the real completed run `campaign_pr427/spm/converge_ihp-sg13g2`
(pure-digital standard cell; the DRC artefacts here are digital):

    drc_report_check . --mode drc
        files_found = 5
        DRC_CATEGORY_PRESENT cites
        steps/31_physical_verification_drc_lvs_erc_density/drc_signoff.rpt

    drc_report_check . --mode drc --under phase3/stage3/pnr
        files_found = 1
        DRC_CATEGORY_PRESENT cites phase3/stage3/pnr/routed.drc.rpt
        rc still 0

`real_violation_total` was summed across all five, so the leak runs both ways:
step 31's report can CARRY step 21's gate when the router's own report is
absent, and step 31's violations can FAIL routing.

WHAT IT COSTS. Measured over the 26 phase-3 roots under `benchmark-data/ic`,
scoping moves 7 from rc 0 to rc 1. Six are `<root>/reports` pseudo-roots the
enumeration produced (a gate is invoked with the project root, not its reports/
subdir). The seventh, `benchmark-data/ic/sha256`, is a genuine root that holds
no router-DRC report of its own — its PASS was earned entirely by the DRC
reports of the nested `clean_run_*` snapshots beneath it. rc 1 there is the
correct verdict, and it is the rc=1 path having been seen to execute, which is
what justifies wiring the scoped form into a blocking slot.

`--under` is OPT-IN: omitted, discovery is project-wide exactly as before, so
step 31 and every other caller are untouched by this change.

A TYPO'D SCOPE IS NOT A MISSING REPORT. `--under does/not/exist` fails closed,
but the first version of this change gave it a finding byte-identical to a
genuinely absent report, so a broken declaration was indistinguishable from a
real miss. `scoped_under_missing` now discloses which scopes were absent, and a
`SCOPE_NOT_FOUND` WARNING fires when EVERY declared scope is absent — the case
where discovery was structurally impossible and the verdict is about the scope,
not the project. Deliberately not an ERROR and deliberately not fired on a
PARTLY absent scope: step 21 legitimately names a canonicalised copy
(`reports/phase3/drc_router.rpt`) that a given run may not have produced, so
promoting that to rc 1 would fail most real roots for a non-defect.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PROGRAMS))

_PAD = "# " + ("=" * 78 + "\n") * 40

_ROUTER_DRC = (
    "[INFO DRT-0012] OpenROAD detailed_route DRC summary\n"
    "Layer M2 via enclosure error at (3.0, 4.5)\n"
    "Layer M3 antenna ratio check\n"
    "Total: 0 violations\n" + _PAD
)
_SIGNOFF_DRC = (
    "KLayout DRC runset — sign-off deck\n"
    "spacing check: 0\nwidth check: 0\nenclosure: 0\nantenna: 0\nvia: 0\n"
    "Total: 0 violations\nDRC clean\n" + _PAD
)


def _run(*args):
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "drc_report_check.py"), *args],
        capture_output=True, text=True, timeout=60)
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:
        return r.returncode, {"summary": {}, "findings": []}


def _project(tmp: Path, *, router=True, signoff=True) -> Path:
    proj = tmp / "proj"
    if router:
        pnr = proj / "phase3" / "stage3" / "pnr"
        pnr.mkdir(parents=True)
        (pnr / "routed.drc.rpt").write_text(_ROUTER_DRC)
    if signoff:
        st31 = proj / "steps" / "31_physical_verification_drc_lvs_erc_density"
        st31.mkdir(parents=True)
        (st31 / "drc_signoff.rpt").write_text(_SIGNOFF_DRC)
    proj.mkdir(parents=True, exist_ok=True)
    return proj


def _cited(doc):
    return sorted({f.get("file", "") for f in doc["findings"] if f.get("file")})


# ===========================================================================
# The scoped gate measures this step's own artefact
# ===========================================================================
def test_scoped_discovery_sees_only_the_scoped_subtree(tmp_path):
    proj = _project(tmp_path)
    rc, doc = _run(str(proj), "--mode", "drc", "--under", "phase3/stage3/pnr")
    assert doc["summary"]["files_found"] == 1, doc["summary"]
    assert all("routed.drc.rpt" in f for f in _cited(doc)), _cited(doc)
    assert rc == 0


def test_another_steps_report_cannot_satisfy_a_scoped_gate(tmp_path):
    """The false-certify direction: with no router DRC of its own, step 21's
    gate used to pass on step 31's report."""
    proj = _project(tmp_path, router=False)
    rc_unscoped, doc_u = _run(str(proj), "--mode", "drc")
    assert rc_unscoped == 0 and doc_u["summary"]["files_found"] == 1, doc_u
    rc_scoped, doc_s = _run(str(proj), "--mode", "drc",
                            "--under", "phase3/stage3/pnr")
    assert rc_scoped == 1, (
        "a step with no report of its own is still being passed by another "
        "step's report")
    assert doc_s["summary"]["files_found"] == 0


def test_another_steps_violations_cannot_fail_a_scoped_gate(tmp_path):
    """The other direction, equally wrong: step 31's DRC failing routing."""
    proj = _project(tmp_path)
    st31 = proj / "steps" / "31_physical_verification_drc_lvs_erc_density"
    (st31 / "drc_signoff.rpt").write_text(
        _SIGNOFF_DRC.replace("Total: 0 violations", "Total: 47 violations"))
    rc_unscoped, _ = _run(str(proj), "--mode", "drc")
    rc_scoped, _ = _run(str(proj), "--mode", "drc",
                        "--under", "phase3/stage3/pnr")
    assert rc_unscoped == 1, "fixture does not reproduce the leak"
    assert rc_scoped == 0, "step 31's violations still reach step 21's gate"


def test_a_file_may_be_named_as_a_scope_root(tmp_path):
    """The canonicalised copy `reports/phase3/drc_router.rpt` lives in a
    directory it shares with step 31's `drc_signoff.rpt`, so the scope has to
    be expressible as a single FILE."""
    proj = _project(tmp_path, router=False)
    rp = proj / "reports" / "phase3"
    rp.mkdir(parents=True)
    (rp / "drc_router.rpt").write_text(_ROUTER_DRC)
    (rp / "drc_signoff.rpt").write_text(_SIGNOFF_DRC)
    rc, doc = _run(str(proj), "--mode", "drc",
                   "--under", "reports/phase3/drc_router.rpt")
    assert rc == 0
    assert doc["summary"]["files_found"] == 1
    assert all("drc_router.rpt" in f for f in _cited(doc)), _cited(doc)


def test_the_scope_travels_with_the_verdict(tmp_path):
    """A reader must be able to see WHICH artefacts a verdict was reached
    over; a scoped verdict that does not say so is worse than none."""
    proj = _project(tmp_path)
    _, doc = _run(str(proj), "--mode", "drc", "--under", "phase3/stage3/pnr")
    assert doc["summary"]["scoped_under"] == ["phase3/stage3/pnr"], doc["summary"]


# ===========================================================================
# A TYPO'D SCOPE MUST NOT LOOK LIKE A MISSING REPORT
# ===========================================================================
def test_a_scope_that_does_not_exist_is_named_as_such(tmp_path):
    """Without this, `--under does/not/exist` produces a byte-identical
    finding to a genuinely absent report ("No DRC report found"), so a broken
    declaration reads as a real miss. It fails closed either way — the point
    is that a reader can tell WHICH failure it is."""
    proj = _project(tmp_path)              # holds a real router DRC report
    rc, doc = _run(str(proj), "--mode", "drc", "--under", "does/not/exist")
    assert rc == 1
    rules = [f["rule"] for f in doc["findings"]]
    assert "SCOPE_NOT_FOUND" in rules, rules
    assert doc["summary"]["scoped_under_missing"] == ["does/not/exist"]


def test_a_real_miss_is_not_blamed_on_the_scope(tmp_path):
    """The two-sided control. A scope that EXISTS and simply holds no report
    must not claim the scope was the problem."""
    proj = _project(tmp_path, router=False, signoff=False)
    (proj / "phase3" / "stage3" / "pnr").mkdir(parents=True, exist_ok=True)
    rc, doc = _run(str(proj), "--mode", "drc", "--under", "phase3/stage3/pnr")
    assert rc == 1
    rules = [f["rule"] for f in doc["findings"]]
    assert "SCOPE_NOT_FOUND" not in rules, rules
    assert doc["summary"]["scoped_under_missing"] == []


def test_a_partly_absent_scope_is_disclosed_but_not_blamed(tmp_path):
    """Step 21 names `reports/phase3/drc_router.rpt`, a canonicalised copy a
    given run may legitimately not have produced. One absent scope out of two
    is DISCLOSURE, never a SCOPE_NOT_FOUND finding, and never rc-bearing."""
    proj = _project(tmp_path)
    rc, doc = _run(str(proj), "--mode", "drc",
                   "--under", "phase3/stage3/pnr",
                   "--under", "reports/phase3/drc_router.rpt")
    assert rc == 0
    assert [f["rule"] for f in doc["findings"]].count("SCOPE_NOT_FOUND") == 0
    assert doc["summary"]["scoped_under_missing"] == [
        "reports/phase3/drc_router.rpt"]


def test_step21_declares_the_scope_that_matches_its_own_outputs():
    """The declaration is the fix; a flag nothing passes changes nothing."""
    flow = _FLOW.read_text(errors="replace")
    cmds = re.findall(r'"(drc_report_check [^"]*)"', flow)
    step21 = [c for c in cmds if "drc_router.json" in c]
    assert step21, "step 21's drc gate is no longer declared"
    for cmd in step21:
        toks = cmd.split()
        unders = [toks[i + 1] for i, t in enumerate(toks) if t == "--under"]
        assert "phase3/stage3/pnr" in unders, cmd
        assert "reports/phase3/drc_router.rpt" in unders, cmd
        assert not any("drc_signoff" in u for u in unders), cmd


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
def test_d1_unscoped_discovery_is_unchanged(tmp_path):
    """`--under` is opt-in. Every existing caller — step 31 included — must
    keep seeing the whole project."""
    proj = _project(tmp_path)
    rc, doc = _run(str(proj), "--mode", "drc")
    assert rc == 0
    assert doc["summary"]["files_found"] == 2, doc["summary"]
    assert "scoped_under" not in doc["summary"]


def test_d1_step31_scopes_to_its_own_declared_artefact():
    """Step 31's DRC gate reads THE SIGN-OFF REPORT and nothing else.

    This assertion used to read `"--under" not in cmd` — "sign-off DRC is
    deliberately project-wide". vibe-ic#584 then scoped step 31 to
    `reports/phase3/drc_signoff.rpt` (see line ~223 of this same file, which
    already knows that) and this guard was left asserting the superseded
    premise, so it has been RED on origin/main ever since — measured on a
    pristine checkout of origin/main, not inferred. It is corrected here rather
    than left red because the line it guards is the line this change edits.

    What it pins now is the property that actually matters and that #584
    landed: the step-31 gate must not reach outside its own artefact — in
    particular it must never pick up step 21's router report.
    """
    flow = _FLOW.read_text(errors="replace")
    cmds = re.findall(r'"(drc_report_check [^"]*)"', flow)
    step31 = [c for c in cmds if "drc_signoff.json" in c]
    assert step31, "step 31's drc gate is no longer declared"
    for cmd in step31:
        unders = [t.split()[0] for t in cmd.split("--under ")[1:]]
        assert unders == ["reports/phase3/drc_signoff.rpt"], cmd
        assert not any("drc_router" in u for u in unders), cmd
        # and it must carry the sign-off policy step 21 must never carry
        assert "--signoff" in cmd.split(), cmd


def test_d1_an_empty_project_still_fails(tmp_path):
    rc, _ = _run(str(tmp_path), "--mode", "drc")
    assert rc == 1


def test_d1_a_real_violation_count_still_fails(tmp_path):
    proj = _project(tmp_path, signoff=False)
    (proj / "phase3" / "stage3" / "pnr" / "routed.drc.rpt").write_text(
        _ROUTER_DRC.replace("Total: 0 violations", "Total: 12 violations"))
    rc, _ = _run(str(proj), "--mode", "drc", "--under", "phase3/stage3/pnr")
    assert rc == 1


def test_d1_backup_directories_are_still_excluded(tmp_path):
    """#525 / v1.3.94 — a `_stale_bak/` or `_snapshot/` copy must stay out of
    unscoped discovery. Nothing about scoping may weaken that."""
    import eda_report_audit as A
    proj = _project(tmp_path, signoff=False)
    bak = proj / "phase3" / "stage3" / "pnr" / "_stale_bak"
    bak.mkdir(parents=True)
    (bak / "routed.drc.rpt").write_text(_ROUTER_DRC)
    found = A._discover(proj, ["*drc*.rpt"])
    assert [p.name for p in found] == ["routed.drc.rpt"], found
    assert all("_stale_bak" not in str(p) for p in found), found


def test_backup_directories_are_excluded_inside_a_scope_too(tmp_path):
    """The scope narrows discovery; it must not re-admit anything. (Not a
    direction-1 guard: `scoped_discovery` is introduced by this change.)"""
    import eda_report_audit as A
    proj = _project(tmp_path, signoff=False)
    bak = proj / "phase3" / "stage3" / "pnr" / "_stale_bak"
    bak.mkdir(parents=True)
    (bak / "routed.drc.rpt").write_text(_ROUTER_DRC)
    with A.scoped_discovery([proj / "phase3/stage3/pnr"]):
        found = A._discover(proj, ["*drc*.rpt"])
    assert [p.name for p in found] == ["routed.drc.rpt"], found
    assert all("_stale_bak" not in str(p) for p in found), found


def test_the_scope_is_reset_after_the_block(tmp_path):
    """In-process callers (`eda_report_audit.main(...)`) must not leak a scope
    into the next call. (Not a direction-1 guard: new API.)"""
    import eda_report_audit as A
    proj = _project(tmp_path)
    with A.scoped_discovery([proj / "phase3/stage3/pnr"]):
        pass
    found = A._discover(proj, ["*drc*.rpt"])
    assert len(found) == 2, found
