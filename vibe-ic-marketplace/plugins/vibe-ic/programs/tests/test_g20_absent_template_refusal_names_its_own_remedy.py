#!/usr/bin/env python3
"""G20 — step 0.5ic's absent-template refusal must name its own remedy.

WHAT WAS REPORTED, AND WHAT WAS ACTUALLY TRUE
=============================================
A report (G20) measured a die that answered `deliverable=DIE`, found step
0.5ic FAILing with NO_TEMPLATE_WITHOUT_REASON, saw 15.5ic and 26.5ic go
`blocked-by-upstream(step 0.5ic)` with their artefacts on disk, and concluded:
"no chip-path (`ic`) step can reach PASS on a self-tape-out".

THAT CONCLUSION IS FALSE, and this file pins the measurement that falsifies it.
On live main v1.16.32 (bcedcdf25d9c), with NO source change, the same tree
reaches `0.5ic PASS` and leaves ZERO rows `blocked-by-upstream(0.5ic)` as soon
as the design supplies `operator_template.absent_reason` in
`input/step_0_5ic_answers.json`. The chip path was reachable the whole time.
`test_a_stated_reason_reaches_not_applicable_and_leaves_no_row_blocked` is that
measurement, kept here as a standing guard.

WHAT WAS REAL
=============
The refusal did not say how. Its sentence was "the record states no usable
reason why that is" and it named the floor and nothing else — not the file the
design supplies the reason in, not the key, and not the fact that the gate had
ALREADY read the design's declaration. Sitting beside it on disk was
`SELF_TAPEOUT.txt`, written by this step's own generator, reading "This design
declares that it is a DIE and that it targets NO shuttle operator". A competent
reader concluded the gate had never consulted it.

The proposed remedy was to let the route word buy the absence. That would have
deleted two guards this repo pins on purpose —
`test_submission_template_check.py::test_a_reason_that_is_not_a_reason_still_fails`
and `::test_dispatching_the_producers_cannot_buy_a_pass_on_its_own` — and it is
wrong on the merits: `_tapeout_declaration.route_of` derives `SELF_TAPEOUT`
from `deliverable=DIE` AND no slot file having been ingested, so the route is
computed FROM the very absence whose reason is being asked for. A die can be on
a shuttle. The route word cannot pay for the absence that produced it.

SO THIS CHANGE MOVES NO VERDICT AT ALL, and that is deliberate. It makes the
refusal carry its own remedy and disclose what it read, and it makes the run
say — before the step refuses — that the design staged no answer. Every tree
this gate refused before, it refuses now.

chip-AGNOSTIC: no vendor, foundry, process node, SKU or design name appears.
"""
import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _submission_template as ST   # noqa: E402
import _tapeout_declaration as TD   # noqa: E402
import _progress_run as _pr         # noqa: E402


#: A reason the design states in its OWN words. Long enough to clear
#: `ST.MIN_REASON_CHARS`, which is READ from the runtime rather than typed here.
_REASON = (
    "This design targets no shuttle operator; it is a self tape-out. No "
    "operator project template exists to stage, so there is no slot geometry, "
    "no operator fixtures and no per-slot pad list for this step to ingest.")

_AREA = {"status": TD.AREA_BUDGET_LIMIT, "max_die_dimensions_um": [3000, 3000]}


@pytest.fixture()
def project():
    # mkdtemp, not tmp_path: a fixture root carrying a newline has broken tool
    # invocation in this tree before, and every path below reaches a subprocess.
    root = Path(tempfile.mkdtemp(prefix="g20_"))
    (root / "input").mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _answers(project: Path, doc):
    path = project / ST.DESIGN_ANSWERS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _drive(project: Path) -> "tuple[int, str]":
    """Run step 0.5ic through the SHIPPED runner entry, capturing what it said."""
    import phase1_one_shot_runner as R
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = R._run_step_0_5ic(project)
    return rc, buf.getvalue()


def _gate(project: Path):
    """The step's first gate clause, exactly as `flow/...yaml` spells it."""
    import submission_template_check as CHK
    rc = CHK.main([str(project), "--json", str(ST.REPORT_REL)])
    doc = json.loads((project / ST.REPORT_REL).read_text(encoding="utf-8"))
    return rc, doc["check"]


def _refusal(check, rule):
    hits = [r for r in check["refusals"] if r["rule"] == rule]
    assert len(hits) == 1, [r["rule"] for r in check["refusals"]]
    return hits[0]


def _audit_rows(project: Path):
    cp = _pr.run([sys.executable, str(PROGRAMS / "flow_compliance_check.py"),
                  str(project)], cwd=str(project), capture_output=True, text=True)
    path = project / "reports/audit/phase23_completion_audit.json"
    assert path.is_file(), cp.stdout[-2000:] + cp.stderr[-2000:]
    rows = {}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("id"), str) and "status" in o:
                rows.setdefault(o["id"], o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(path.read_text(encoding="utf-8")))
    return rows


# --------------------------------------------------------------------------- #
# what the refusal must SAY — the defect this change closes
# --------------------------------------------------------------------------- #
def test_the_refusal_names_where_the_reason_is_supplied(project):
    """A refusal that names a floor and not its channel sends readers wrong."""
    _answers(project, {"answers": {"deliverable": TD.DELIVERABLE_DIE},
                       TD.SYNTHESIS_AREA_BUDGET_KEY: _AREA})
    assert _drive(project)[0] == 0
    rc, check = _gate(project)

    assert rc == 1, "the verdict must NOT move: this change is disclosure only"
    r = _refusal(check, "NO_TEMPLATE_WITHOUT_REASON")

    # PROSE, for the human reading a flow report...
    assert ST.DESIGN_ANSWERS_REL in r["message"], r["message"]
    assert "operator_template.absent_reason" in r["message"], r["message"]
    assert str(ST.MIN_REASON_CHARS) in r["message"], r["message"]
    # ...and STRUCTURE, for anything that consumes the record instead.
    assert r.get("design_answers_path") == ST.DESIGN_ANSWERS_REL, r
    assert r.get("design_answers_key") == "operator_template.absent_reason", r


def test_the_refusal_names_the_route_it_read_and_why_it_bought_nothing(project):
    """"I did not read it" and "I read it and it is not a reason" differ.

    The whole G20 report turned on that pair. The gate HAD read the design's
    declaration; the sentence did not say so, so its silence read as absence.
    """
    _answers(project, {"answers": {"deliverable": TD.DELIVERABLE_DIE},
                       TD.SYNTHESIS_AREA_BUDGET_KEY: _AREA})
    assert _drive(project)[0] == 0
    assert (project / TD.SELF_TAPEOUT_REL).is_file()

    rc, check = _gate(project)
    assert rc == 1
    r = _refusal(check, "NO_TEMPLATE_WITHOUT_REASON")

    assert r.get("declared_route") == TD.ROUTE_SELF_TAPEOUT, r
    assert r.get("declared_absence_router") == TD.SELF_TAPEOUT_REL, r
    assert check["examined"].get("declared_route") == TD.ROUTE_SELF_TAPEOUT, \
        check["examined"]
    assert TD.DECLARATION_REL in r["message"], r["message"]
    assert TD.ROUTE_SELF_TAPEOUT in r["message"], r["message"]
    # and it must say WHY the route buys nothing, not merely that it does not
    assert "route_of" in r["message"], r["message"]


def test_the_run_discloses_the_missing_answer_before_the_step_refuses(project):
    """A decline that discloses nothing reads downstream as nothing-to-do."""
    rc, said = _drive(project)          # no answers file staged at all
    assert rc == 0, "the producers must still RUN for a design that said nothing"
    assert ST.DESIGN_ANSWERS_REL in said, said
    assert "operator_template.absent_reason" in said, said
    assert "NO_TEMPLATE_WITHOUT_REASON" in said, said

    # and the same disclosure when the file exists and answers the wrong half
    _answers(project, {"answers": {"deliverable": TD.DELIVERABLE_DIE}})
    rc, said = _drive(project)
    assert rc == 0
    assert ST.DESIGN_ANSWERS_REL in said, said
    assert "operator_template.absent_reason" in said, said


# --------------------------------------------------------------------------- #
# the contract, unmoved — these pass on main too, and are here to STAY passing
# --------------------------------------------------------------------------- #
def test_the_route_word_still_buys_nothing(project):
    """`deliverable=DIE` alone is not a reason, and must not become one.

    Kept beside the tests above because the disclosure they ask for is exactly
    what a later reader would be tempted to "fix" by relaxing this instead.
    """
    _answers(project, {"answers": {"deliverable": TD.DELIVERABLE_DIE},
                       TD.SYNTHESIS_AREA_BUDGET_KEY: _AREA})
    assert _drive(project)[0] == 0
    assert (project / TD.SELF_TAPEOUT_REL).is_file(), (
        "the route IS selected — which is why the refusal has to explain "
        "itself rather than look like a flow that lost the declaration")
    rc, check = _gate(project)
    assert (rc, check["verdict"]) == (1, ST.VERDICT_FAIL), check
    assert [r["rule"] for r in check["refusals"]] == ["NO_TEMPLATE_WITHOUT_REASON"]


def test_a_stated_reason_reaches_not_applicable_and_leaves_no_row_blocked(project):
    """THE MEASUREMENT THAT FALSIFIES "the chip path cannot be certified".

    The design states its own reason; step 0.5ic reaches NOT_APPLICABLE — never
    PASS — and every row that names 0.5ic as its `condition_owner` keeps its own
    verdict instead of being erased by `blocked-by-upstream(0.5ic)`.
    """
    _answers(project, {"operator_template": {"absent_reason": _REASON},
                       "answers": {"deliverable": TD.DELIVERABLE_DIE},
                       TD.SYNTHESIS_AREA_BUDGET_KEY: _AREA})
    assert _drive(project)[0] == 0
    rc, check = _gate(project)
    assert rc == 0, check
    assert check["verdict"] == ST.VERDICT_NOT_APPLICABLE, check
    assert check["not_applicable_reason"] == _REASON
    assert "passed" not in check, "NOT_APPLICABLE must never fold into a boolean"

    rows = _audit_rows(project)
    assert rows["0.5ic"]["status"] == "PASS", rows["0.5ic"]
    # THE DENOMINATOR IS STATED: a zero over rows nobody looked at is the empty
    # scan this tree has been bitten by. All four dependents must be present.
    for sid in ("15.5ic", "26.5ic", "37.5ic", "37.5ip"):
        assert sid in rows, sorted(rows)
    blocked = sorted(sid for sid, r in rows.items()
                     if "blocked-by-upstream(0.5ic)" in str(r.get("cascade_note") or ""))
    assert blocked == [], blocked


# --------------------------------------------------------------------------- #
# controls — the refusal must still fire, and fire for the right trees
# --------------------------------------------------------------------------- #
def test_control_a_design_that_said_nothing_still_fails(project):
    """The OPERATOR route with a genuinely absent template. Still a FAIL.

    This gate exists because a silently missing slot file is how a design gets
    taped out into the wrong geometry.
    """
    assert _drive(project)[0] == 0
    assert not (project / TD.SELF_TAPEOUT_REL).exists()
    rc, check = _gate(project)
    assert (rc, check["verdict"]) == (1, ST.VERDICT_FAIL), check
    r = _refusal(check, "NO_TEMPLATE_WITHOUT_REASON")
    assert r.get("declared_route", "<no such key>") == TD.NOT_DETERMINED, r
    assert r.get("declared_absence_router", "<no such key>") is None, r
    # and the sentence still carries the remedy on THIS arm too
    assert ST.DESIGN_ANSWERS_REL in r["message"], r["message"]


def test_control_a_marker_file_beside_no_declaration_is_not_a_declaration(project):
    """The FILE'S CONTENT declares the route, not the file's name."""
    _answers(project, {"answers": {"deliverable": TD.DELIVERABLE_DIE},
                       TD.SYNTHESIS_AREA_BUDGET_KEY: _AREA})
    assert _drive(project)[0] == 0
    marker = project / TD.SELF_TAPEOUT_REL
    assert marker.read_text(encoding="utf-8").splitlines()[0].strip() \
        == TD.SELF_TAPEOUT_MARKER

    # the declaration is replaced by one that answers nothing; the router file
    # the generator wrote is left exactly where it is
    (project / TD.DECLARATION_REL).write_text(
        json.dumps(TD.blank_declaration(), indent=2) + "\n", encoding="utf-8")

    rc, check = _gate(project)
    assert (rc, check["verdict"]) == (1, ST.VERDICT_FAIL), check
    r = _refusal(check, "NO_TEMPLATE_WITHOUT_REASON")
    assert r.get("declared_route", "<no such key>") == TD.NOT_DETERMINED, r
    assert "answers no `deliverable`" in r["message"], r["message"]


def test_control_the_hardmacro_route_is_untouched(project):
    """A HARDMACRO declaration writes no self-tape-out router, and still FAILs."""
    _answers(project, {"answers": {"deliverable": TD.DELIVERABLE_HARDMACRO},
                       TD.SYNTHESIS_AREA_BUDGET_KEY: _AREA})
    assert _drive(project)[0] == 0
    assert not (project / TD.SELF_TAPEOUT_REL).exists()
    rc, check = _gate(project)
    assert rc == 1
    r = _refusal(check, "NO_TEMPLATE_WITHOUT_REASON")
    assert r.get("declared_route") == TD.ROUTE_IP, r


def test_declared_route_on_disk_separates_unreadable_from_undeclared(project):
    """The reader the refusal quotes, held to the producer it mirrors.

    `getattr`, not a bare attribute: a control that dies with AttributeError
    against the pre-fix tree has OBSERVED NOTHING, and "the tests fail before
    the change" is true of every new file ever written. This way the old tree
    answers, and answers wrongly.
    """
    reader = getattr(TD, "declared_route_on_disk", None)
    assert callable(reader), reader

    route, why = reader(project, has_slots=False)
    assert route == TD.NOT_DETERMINED and TD.DECLARATION_REL in why, why

    _answers(project, {"answers": {"deliverable": TD.DELIVERABLE_DIE},
                       TD.SYNTHESIS_AREA_BUDGET_KEY: _AREA})
    assert _drive(project)[0] == 0
    assert reader(project, has_slots=False) == (TD.ROUTE_SELF_TAPEOUT, None)

    # THE OPERATOR'S ANSWER WINS, and this reader honours that ordering rather
    # than restating it: a tree with slot files is on the shuttle route whatever
    # the design declared about itself.
    assert reader(project, has_slots=True)[0] == TD.ROUTE_SHUTTLE

    (project / TD.DECLARATION_REL).write_text("{ not json", encoding="utf-8")
    route, why = reader(project, has_slots=False)
    assert route == TD.NOT_DETERMINED and "not JSON" in why, why
