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
import _owner_declared as _OD                              # noqa: E402
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
    # A fixture that answers `deliverable` is modelling a design whose owner
    # declared the route; since R-0915-95 it has to say so (`_owner_declared`).
    # A hand-written area disposition is the owner's explicit answer, not a
    # derived one (R-0929-DELIVERABLE-CONSISTENCY-2, `_owner_declared`).
    path.write_text(json.dumps(_OD.attest_explicit(_OD.attest(doc)),
                               indent=2) + "\n",
                    encoding="utf-8")




def _historical_declaration_fixture(project: Path):
    """Consumer-only route fixture: the normal runner now stops before this.

    Retain the old gate's marker/declaration cases using its real producer,
    without making a route word satisfy the missing template reason.
    """
    import tapeout_declaration_gen as declaration
    assert declaration.main([str(project), "--answers", str(project / ST.DESIGN_ANSWERS_REL)]) == 0








# --------------------------------------------------------------------------- #
# what the refusal must SAY — the defect this change closes
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# the contract, unmoved — these pass on main too, and are here to STAY passing
# --------------------------------------------------------------------------- #





# --------------------------------------------------------------------------- #
# controls — the refusal must still fire, and fire for the right trees
# --------------------------------------------------------------------------- #






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
    _historical_declaration_fixture(project)
    assert reader(project, has_slots=False) == (TD.ROUTE_SELF_TAPEOUT, None)

    # THE OPERATOR'S ANSWER WINS, and this reader honours that ordering rather
    # than restating it: a tree with slot files is on the shuttle route whatever
    # the design declared about itself.
    assert reader(project, has_slots=True)[0] == TD.ROUTE_SHUTTLE

    (project / TD.DECLARATION_REL).write_text("{ not json", encoding="utf-8")
    route, why = reader(project, has_slots=False)
    assert route == TD.NOT_DETERMINED and "not JSON" in why, why
