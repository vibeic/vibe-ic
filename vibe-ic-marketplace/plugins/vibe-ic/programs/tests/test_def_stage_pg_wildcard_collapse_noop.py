"""def_stage_progression_check Check-2 (`size-non-monotone`) false-FAILed a
legitimate PG SPECIALNETS connectivity-notation collapse.

ORGANIC #571's `_build_pg_reconnect_tcl` re-applies `global_connect` after
routing so physical-only cells created after the PDN's one-shot connect
(repair/CTS buffers, antenna diodes, decap/fill) get their PG pins attached.
On a design with many such cells, `global_connect` rewrites a SPECIALNETS
pin-connectivity list from thousands of explicit `( inst pin )` entries down
to the standard DEF wildcard `( * pin )` token — correct, and if anything
MORE complete (it also covers instances added later) — but it can shave
hundreds of KB off a DEF that never lost a single wire.

MEASURED (caravel_user_project x sky130A, v1.5.60): post_hold.def
(39,005,262 B) -> routed.def (38,580,931 B), a 424,331 B / 1.1% shrink,
while the routing/PDN geometry segment count (NEW/+ROUTED/+SHAPE lines)
went 479,307 -> 485,009 (grew) and COMPONENTS went 10,030 -> 10,139 (grew).
Step 21 Routing FAILed on an otherwise fully-converged, DRC-clean, LVS-clean
design.

Fix: exempt a shrink on ANY stage pair when the LATER stage shows POSITIVE
routing-geometry evidence (segment count > 0) that is itself non-decreasing
from the earlier stage, AND the component count is non-decreasing — i.e.
the shrink is attributable to connectivity-notation only, never a real
geometry or instance loss.

NEGATIVE no-leak — each of these must STILL FAIL:
  - a shrink where routing-geometry segments actually DECREASE (a real
    dropped-net truncation);
  - a shrink where components DECREASE (a real dropped-instance
    truncation), even if geometry segments look preserved;
  - a shrink with NO routing-geometry evidence at all (vacuous 0-vs-0),
    which proves nothing and must not be waved through on component count
    alone.

chip/PDK-AGNOSTIC: keyed on the DEF's own geometry/instance counts, no
design or PDK literal.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import def_stage_progression_check as D  # noqa: E402
import _path_layout as _pl  # noqa: E402


def _def_with_specialnets(n_components: int, pg_lines: list[str],
                          n_new_signal_segs: int = 0) -> str:
    """A syntactically plausible DEF with a tunable SPECIALNETS pin list and
    a tunable number of `NEW ...` signal-routing continuation segments."""
    body = ["COMPONENTS %d ;" % n_components]
    body += ["  - U_%d AND2X1 + PLACED ( %d %d ) N ;" % (i, i * 100, i * 100)
             for i in range(n_components)]
    body.append("END COMPONENTS")
    body.append("SPECIALNETS 2 ;")
    body.append("- VGND " + " ".join(pg_lines) + " + USE GROUND")
    body.append("  + ROUTED met5 1600 + SHAPE STRIPE ( 0 0 ) ( 100 0 )")
    for k in range(n_new_signal_segs):
        body.append("  NEW met3 170 ( %d 0 ) ( %d 10 )" % (k, k))
    body.append("- VPWR ( * VPWR )")
    body.append("  + ROUTED met5 1600 + SHAPE STRIPE ( 0 10 ) ( 100 10 )")
    body.append("END SPECIALNETS")
    return "\n".join(body) + "\n"


def _mk(tmp_path, *, prev_components, prev_pg_lines, prev_new_segs,
        next_components, next_pg_lines, next_new_segs):
    """Write a minimal 2-stage pair (post_hold -> routed) under `pnr/`, plus
    a floorplan/placed/post_cts filler so `inspect()` finds all 5 canonical
    stages. Only the post_hold/routed pair is under test; the earlier three
    are held identical+tiny+monotone so they never contribute a finding."""
    pnr = _pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    filler = "COMPONENTS 1 ;\n  - U_0 AND2X1 + PLACED ( 0 0 ) N ;\nEND COMPONENTS\n"
    (pnr / "floorplan.def").write_text(filler)
    (pnr / "placed.def").write_text(filler + "# pad\n")
    (pnr / "post_cts.def").write_text(filler + "# pad more\n")
    (pnr / "post_hold.def").write_text(
        _def_with_specialnets(prev_components, prev_pg_lines, prev_new_segs))
    (pnr / "routed.def").write_text(
        _def_with_specialnets(next_components, next_pg_lines, next_new_segs))
    return tmp_path


def _nonmonotone(tmp_path):
    _infos, finds = D.inspect(tmp_path)
    return [f for f in finds if f.rule == "size-non-monotone"]


def _explicit_pg_list(n):
    return ["( _%d_ VNB )" % i for i in range(n)]


# --------------------------------------------------------------- POSITIVE ---

def test_wildcard_collapse_shrink_is_not_a_finding(tmp_path):
    """The measured case: post_hold has a huge explicit PG pin list (big
    bytes, but this DEF fixture's routing/component counts are otherwise
    representative); routed collapses it to a wildcard token AND ALSO adds
    real signal routing + more components. Net byte size shrinks; geometry
    and instances both grow. Must NOT be flagged."""
    _mk(tmp_path,
        prev_components=50, prev_pg_lines=_explicit_pg_list(400),
        prev_new_segs=0,
        next_components=55, next_pg_lines=["( * VNB )"],
        next_new_segs=50)

    prev_size = (Path(_pl.pnr_dir(tmp_path)) / "post_hold.def").stat().st_size
    next_size = (Path(_pl.pnr_dir(tmp_path)) / "routed.def").stat().st_size
    assert next_size < prev_size, "fixture must actually shrink in bytes"

    assert _nonmonotone(tmp_path) == []


# ------------------------------------------------------------- NO-LEAK -----

def test_shrink_with_real_geometry_loss_still_fails(tmp_path):
    """Same wildcard collapse, but routing segments DECREASE too — a real
    truncation must not hide behind the exemption."""
    _mk(tmp_path,
        prev_components=50, prev_pg_lines=_explicit_pg_list(400),
        prev_new_segs=200,
        next_components=55, next_pg_lines=["( * VNB )"],
        next_new_segs=0)   # geometry LOST, not preserved

    finds = _nonmonotone(tmp_path)
    assert finds != []
    assert finds[0].rule == "size-non-monotone"


def test_shrink_with_instance_loss_still_fails(tmp_path):
    """Geometry looks preserved/grown, but COMPONENTS decreased — still a
    real regression, must not be waved through."""
    _mk(tmp_path,
        prev_components=50, prev_pg_lines=_explicit_pg_list(400),
        prev_new_segs=0,
        next_components=10, next_pg_lines=["( * VNB )"],  # fewer instances
        next_new_segs=50)

    assert _nonmonotone(tmp_path) != []


def test_vacuous_shrink_with_no_routing_evidence_at_all_still_fails(tmp_path):
    """No routing-geometry evidence at either stage (no SPECIALNETS/NETS
    wire statements at all, matching a pre-route DEF pair) — a true 0-vs-0
    comparison proves nothing and must not be exempted just because
    component count happens to be preserved. (The narrower case where a
    fixture DOES carry static PDN stripe lines unchanged in both stages is
    legitimately benign — covered by the positive case above; this test is
    the true vacuum, no routing marker present anywhere.)"""
    pnr = _pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    filler = "COMPONENTS 1 ;\n  - U_0 AND2X1 + PLACED ( 0 0 ) N ;\nEND COMPONENTS\n"
    (pnr / "floorplan.def").write_text(filler)
    (pnr / "placed.def").write_text(filler + "# pad\n")
    (pnr / "post_cts.def").write_text(filler + "# pad more\n")

    def _no_routing_def(n_components, pad):
        body = ["COMPONENTS %d ;" % n_components]
        body += ["  - U_%d AND2X1 + PLACED ( %d %d ) N ;" % (i, i * 100, i * 100)
                 for i in range(n_components)]
        body.append("END COMPONENTS")
        return "\n".join(body) + "\n# pad " + ("x" * pad) + "\n"

    (pnr / "post_hold.def").write_text(_no_routing_def(50, 4000))
    (pnr / "routed.def").write_text(_no_routing_def(50, 0))  # same count, shrinks

    assert _nonmonotone(tmp_path) != []


# ---------------------------------------------- harvest(#338 via #349) -----
# The exemption's own boundary: every control above pairs the byte shrink with
# GROWTH (more components, more segments). The measured wildcard-collapse case
# does not have to grow — a routed.def can collapse an explicit PG pin list to
# a wildcard token while doing exactly the same amount of work. Behaviour on
# main is already correct (verified before writing this: equal counts + shrink
# yields no finding); it was simply UNPINNED, so tightening the exemption to
# require STRICT growth would silently start failing real runs and no test
# would notice.

def test_equal_work_shrink_is_still_exempt(tmp_path):
    """Byte size shrinks, component count and routing-segment count are both
    UNCHANGED. Nothing was lost, so this is a re-encoding, not a truncation —
    the exemption must not require growth."""
    _mk(tmp_path,
        prev_components=50, prev_pg_lines=_explicit_pg_list(400),
        prev_new_segs=50,
        next_components=50, next_pg_lines=["( * VNB )"],
        next_new_segs=50)

    prev_size = (Path(_pl.pnr_dir(tmp_path)) / "post_hold.def").stat().st_size
    next_size = (Path(_pl.pnr_dir(tmp_path)) / "routed.def").stat().st_size
    assert next_size < prev_size, "fixture must actually shrink in bytes"

    assert _nonmonotone(tmp_path) == []


def test_equal_work_shrink_exemption_is_not_a_blanket_pass(tmp_path):
    """NO-LEAK for the test above: hold the shrink and the component count
    equal but LOSE routing segments. Equal-work is not a licence — the loss
    must still be caught, so the test above cannot be satisfied by an
    exemption that simply stopped looking."""
    _mk(tmp_path,
        prev_components=50, prev_pg_lines=_explicit_pg_list(400),
        prev_new_segs=50,
        next_components=50, next_pg_lines=["( * VNB )"],
        next_new_segs=10)

    assert _nonmonotone(tmp_path) != []
