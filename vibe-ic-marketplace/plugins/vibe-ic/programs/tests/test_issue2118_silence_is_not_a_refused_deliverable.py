"""vibe-ic#2118 — `_effective_deliverable`'s whole truth table.

RE-PINNED TO R-0915-95 (icrev1, 2026-09-21), NOT WEAKENED. This file was
written to restore the derivation for one case -- a declaration that EXISTS and
that NOBODY HAS ANSWERED YET -- on the ground that such a template is neither
unreadable nor unattested, so #2376 had "reached one case too far". The owner
ruling it collided with is the one that took `deliverable` off the derivable
list altogether, and the collision was not seen when this landed: this file's
own commit message dates the counterpart test file to f5a237d21 (2026-09-07),
"thirteen days before the landing that reddened it", while
`test_hardmacro_delivery_ships_no_die_seal_ring.py` had in fact been re-pinned
to the ruling seventeen hours earlier, in 58ca26548 (2026-09-20 23:11). Since
then the tree has failed its own rule: two landed tests asserted opposite
values for one call, and the census carries it as cause C11
(`assert 'HARDMACRO' is None`).

WHAT THE RE-MEASUREMENT SHOWED, on cbca058b3, 8HD-d, image 0.3.67:

  * THE GROUND DOES NOT HOLD. `derived` at the publisher's call site is
    `_declared_deliverable`, whose only surviving authority is
    `_ppa/delivery_path` -- a route read from WHICH ROUTER ARTEFACT IS ON DISK.
    Under a silent declaration the value handed back is therefore the old
    router marker itself, which is the one thing #2376 exists to refuse. Driven
    directly: silent declaration with no router artefact -> (None, "the
    delivery route is NOT_DETERMINED"); the same tree plus
    `input/submission_template/slots/*.yaml` -> DIE; plus
    `input/submission_template/NO_TEMPLATE.txt` -> HARDMACRO. The "fresh
    template" case and the "stale marker" case are the same case.

  * THE STATED CONSEQUENCE DOES NOT ARRIVE. This file's premise was that the
    publisher would then name the size rectangle "on every DIE and every
    HARDMACRO whose declaration had not been hand-answered -- which is the
    normal state of a fresh run". Driven WITH the change in place against a
    real fresh project and the REAL `_declared_deliverable` (the publisher
    case below monkeypatches that function), `published` came back
    `['top_cell']` with `die_area_um` and `macro_area_um` both in
    `not_determined` -- the very symptom the change was for.

WHAT IS KEPT, and it is most of the file: #2376's refusal of an unattested
answer, #2425's refusal of an answer with no provenance map at all, the
unreadable case, and the no-file case. Only the two SILENT-declaration
assertions move, and they move to the ruling.
"""
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _tapeout_declaration as td            # noqa: E402











# ── the five cases, and each one moves the answer ───────────────────────────












# ── and the consequence the publisher cares about ───────────────────────────
def test_a_silent_declaration_gets_NEITHER_name_even_with_a_route_stated(
        tmp_path, monkeypatch):
    """The consequence at the publisher, and it is the sibling file's own rule.

    That file's header already says an undeclared deliverable "publishes
    NEITHER -- choosing one name would be a guess wearing a derivation's
    clothes", and the publisher says the same thing in a comment at the call
    site. This pins it against the strongest available contrary input: the
    route is STATED through the `_declared_deliverable` mock and the
    declaration is still silent, so nothing but the declaration can settle it.

    The declared arms of that rule -- a HARDMACRO publishing `macro_*` and a
    DIE publishing `die_*` -- are in the sibling file and are unchanged; they
    now declare the deliverable in the fixture instead of relying on the mock.
    """
    from test_issue2118_a_hardmacro_has_no_die_to_declare import (
        _publisher_project, _publish)
    project = _publisher_project(tmp_path)          # silent, deliverable=None
    rec = _publish(project, monkeypatch, td.DELIVERABLE_HARDMACRO)
    for key in ("macro_area_um", "macro_origin_um",
                "die_area_um", "die_origin_um"):
        assert key not in rec["published"], rec["published"]
        assert "not known" in rec["not_determined"][key], rec["not_determined"]
