"""A producer may not report a field unreported while it is holding the field.

THE DEFECT, MEASURED on a real run's `sta_mcorner_ocv.rpt` before the repair::

    banner: === SETUP corner: process=SS liberty=..__ss_100C_1v60.lib, SPEF=<top>.max.spef ===
       rc_corner=None   spef='<top>.max.spef'

`_ppa/backends/opensta` captures the `SPEF=` token off the SAME banner line it
takes `process=` and `liberty=` from (`_BANNER_SPEF_RE`). `_ppa/timing.py` then
read `sec.rc_corner` only, never `sec.spef`, and wrote the gap reason

    "this report names no RC corner for the section; the RC axis is reported
     by the multi-corner SPEF report, not this one"

which is FALSE for that report: the section names its RC condition, as a
parasitics file, on its own banner. That sentence reached published records --
`ppa-crosslayer/records/h2h_A.json` carries `rc_corner: null` and the gate
`ppa_head_to_head_check` refuses it `SCOPE_SENTINEL` -- and it told every reader
to go look somewhere else for a datum the artefact already stated.

WHAT THIS TEST DOES *NOT* DEMAND, and the distinction is the point. It does not
demand that `rc_corner` be FILLED. The token is a FILE NAME, and reading `max`
out of `x.max.spef` is precisely the filename inference `_ppa/timing._stage_for`
refuses by design ("inferring `post_route_extracted` from the filename would let
a pre-layout estimate be compared against sign-off evidence"). A gap is the
correct outcome. What is demanded is that the REASON be true and name what the
producer is holding, so the next reader starts at the artefact rather than at a
denial.

Chip-, PDK- and vendor-AGNOSTIC: the fixture names no foundry, node or SKU.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

from _ppa import timing as _timing            # noqa: E402
from _ppa.backends import opensta as _opensta  # noqa: E402

TOP = "core_top"

#: Dialect B -- the shape `sta_mcorner_ocv.rpt` is written in. The banner names
#: a process and a SPEF FILE, and no `(max-RC corner)` label.
DIALECT_B = """\
=== SETUP corner: process=SS liberty=/pdk/openpdk/libs.ref/stdcells/lib/\
stdcells__ss_100C_1v60.lib, SPEF={top}.max.spef ===
STA_BASIS: POST_ROUTE_SPEF
worst slack max -0.250
=== HOLD corner: process=FF liberty=/pdk/openpdk/libs.ref/stdcells/lib/\
stdcells__ff_n40C_1v95.lib, SPEF={top}.min.spef ===
STA_BASIS: POST_ROUTE_SPEF
worst slack min 0.120
""".format(top=TOP)

#: The same shape with the SPEF token removed. Here the old sentence is TRUE and
#: must survive -- a repair that blanket-replaces it would be a different lie.
DIALECT_B_NO_SPEF = DIALECT_B.replace(", SPEF={}.max.spef".format(TOP), "") \
                             .replace(", SPEF={}.min.spef".format(TOP), "")


def _gaps(text: str):
    """Every `rc_corner` gap reason the producer emits for one report."""
    report = _opensta.parse_report(text, path="phase3/stage3/sta/sta_x.rpt")
    rows = _timing.rows_from_report(
        Path("/nonexistent-project"), Path("phase3/stage3/sta/sta_x.rpt"),
        report, mode=None, mode_gap="fixture declares no pvt matrix")
    return [r["scope_gaps"]["rc_corner"] for r in rows
            if "rc_corner" in (r.get("scope_gaps") or {})]


def test_the_backend_really_does_hold_the_spef_while_rc_corner_is_none():
    """The premise, proven rather than assumed: the datum IS in hand."""
    report = _opensta.parse_report(DIALECT_B)
    banners = [s for s in report.sections if s.banner is not None]
    assert banners, "fixture produced no bannered section"
    for sec in banners:
        assert sec.rc_corner is None, (
            "fixture is not dialect B any more: it now carries a normalised "
            "RC-corner label, so it cannot demonstrate the defect")
        assert sec.spef, "the backend dropped the SPEF token the banner names"


def test_the_reason_names_the_parasitics_the_producer_is_holding():
    reasons = _gaps(DIALECT_B)
    assert reasons, "no rc_corner gap was emitted for a section that lacks one"
    for why in reasons:
        assert ".spef" in why, (
            "the rc_corner gap reason does not name the parasitics file the "
            "producer parsed off the same banner line. A producer that holds "
            "the identity of a field and reports the field unreported is the "
            "denial this test exists to refuse. reason was: %r" % (why,))


def test_the_reason_does_not_claim_the_report_named_no_rc_corner():
    for why in _gaps(DIALECT_B):
        assert "names no RC corner" not in why, (
            "the producer still tells the reader this report names no RC "
            "corner, while its own parse holds the SPEF the banner states. "
            "reason was: %r" % (why,))


def test_the_corner_is_still_NOT_invented_from_the_file_name():
    """The other half. A gap is correct here; a filled key would be a guess."""
    report = _opensta.parse_report(DIALECT_B)
    rows = _timing.rows_from_report(
        Path("/nonexistent-project"), Path("phase3/stage3/sta/sta_x.rpt"),
        report, mode=None, mode_gap="fixture declares no pvt matrix")
    for r in rows:
        assert r["scope"].get("rc_corner") is None, (
            "`rc_corner` was FILLED from a file name. Deriving a corner from "
            "`%s.max.spef` is the filename inference `_stage_for` refuses by "
            "design; the honest outcome is a stated gap, not a guess." % TOP)


def test_a_report_that_truly_names_nothing_keeps_the_original_sentence():
    """The negative side: the old reason is right when it is right."""
    reasons = _gaps(DIALECT_B_NO_SPEF)
    assert reasons, "no rc_corner gap emitted for a report that names nothing"
    for why in reasons:
        assert "names no RC corner" in why, (
            "a report that genuinely names no RC condition must still say so; "
            "the repair must not blanket-replace a true sentence. reason "
            "was: %r" % (why,))
        assert ".spef" not in why, (
            "a parasitics file was named for a report that declares none: %r"
            % (why,))
