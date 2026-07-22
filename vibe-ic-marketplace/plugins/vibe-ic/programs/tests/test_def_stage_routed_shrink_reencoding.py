"""def_stage_progression_check Check-2 (`size-non-monotone`) false-FAILed a
legitimate post_hold -> routed byte SHRINK.

Detailed routing REPLACES the prior stage's global/estimated routing with the
final per-net geometry, and that re-encoding can come back a few percent SMALLER
while carrying strictly MORE routing — the routed DEF is a compact SUPERSET, not
a truncation. A byte-monotone rule then reports fraud on a correctly-routed
design, cascading Steps 22/24/25/26/27/28/32-37.

OBSERVED (caravel_user_project x sky130A, 2026-07-22): routed.def 38,573,330 B
vs post_hold.def 38,998,185 B (-1.09%) while COMPONENTS grew 9,991 -> 10,078
and routed-wire segments grew 479,307 -> 484,980. DRC 0 / LVS match / STA met.

Fix: exempt a shrink on the post_hold -> routed transition ONLY with POSITIVE
proof that routing WORK did not shrink — instances non-decreasing AND routing
present AND route-segment count non-decreasing. A truncated routed DEF (which
loses segments) still FAILs, and Check 3 (instance count) / Check 4 (routing
presence) remain the truncation guards.

chip-AGNOSTIC: keyed on the DEF's own COMPONENTS / routed-segment counts and the
exact stage pair; no chip literal, no PDK literal.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import def_stage_progression_check as D  # noqa: E402
import _path_layout as _pl  # noqa: E402


def _comp_body(n_components: int) -> str:
    body = ["COMPONENTS %d ;" % n_components]
    body += ["  - U_%d AND2X1 + PLACED ( %d %d ) N ;" % (i, i * 100, i * 100)
             for i in range(n_components)]
    body.append("END COMPONENTS")
    return "\n".join(body)


def _routed_def(n_components: int, n_segments: int, pad: int) -> str:
    """A DEF with a tunable COMPONENTS count, routed-segment count and byte size.

    Each net contributes one `+ ROUTED` start plus `NEW` continuations, which is
    exactly what _count_route_segments tallies. `pad` rides in a trailing comment
    so byte size is independent of the two counts.
    """
    lines = [_comp_body(n_components), "NETS %d ;" % max(n_segments, 1)]
    for i in range(n_segments):
        lines.append("  - n%d + ROUTED met1 ( %d 0 ) ( %d 0 )" % (i, i, i + 1))
    lines.append("END NETS")
    return "\n".join(lines) + "\n# pad " + ("x" * pad) + "\n"


def _mk(tmp_path, *, routed_components, routed_segments, routed_pad,
        hold_components=100, hold_segments=100, hold_pad=200_000):
    """Write a 5-stage set where floorplan..post_hold are fixed and only the
    routed stage is under the caller's control. Byte size is dominated by the
    trailing `pad` (segment/component counts are kept small), so a caller can set
    routed BYTES independently of its segment/component counts — the whole point,
    since the real defect is "more segments, fewer bytes". post_hold carries a
    big pad so a pad-0 routed stage is reliably SMALLER regardless of its counts.
    Every stage has a distinct sha256 and a non-decreasing instance count
    floorplan->post_hold, so Checks 1 and 3 stay quiet and Check 2 is isolated on
    the post_hold->routed pair."""
    pnr = _pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "floorplan.def").write_text(_comp_body(2) + "\n# fp\n")
    (pnr / "placed.def").write_text(
        _routed_def(hold_components - 1, hold_segments, hold_pad - 2))
    # post_cts a touch SMALLER than post_hold (a growth, so Check 2 stays quiet
    # on that pair) yet a distinct sha256 (so Check 1 stays quiet): isolates the
    # post_hold -> routed pair as the only thing under test.
    (pnr / "post_cts.def").write_text(
        _routed_def(hold_components, hold_segments, hold_pad - 1))
    (pnr / "post_hold.def").write_text(
        _routed_def(hold_components, hold_segments, hold_pad))
    (pnr / "routed.def").write_text(
        _routed_def(routed_components, routed_segments, routed_pad))
    return tmp_path


def _nonmonotone(tmp_path):
    _infos, finds = D.inspect(tmp_path)
    return [f for f in finds if f.rule == "size-non-monotone"]


def _pnr_sizes(tmp_path):
    pnr = _pl.pnr_dir(tmp_path)
    return {s: (pnr / f"{s}.def").stat().st_size
            for s in ("post_hold", "routed")}


# --------------------------------------------------------------- POSITIVE ---

def test_routed_shrink_with_more_work_is_not_a_finding(tmp_path):
    """The measured case: routed is SMALLER in bytes but has MORE components and
    MORE routed segments — a compact re-encoding, not a truncation."""
    _mk(tmp_path, routed_components=110, routed_segments=105, routed_pad=0)
    sz = _pnr_sizes(tmp_path)
    assert sz["routed"] < sz["post_hold"], "fixture must actually shrink"
    assert _nonmonotone(tmp_path) == []


def test_routed_equal_work_shrink_ok(tmp_path):
    """Even with equal instance/segment counts a small re-encoding shrink is
    fine, provided routing is present and nothing was lost."""
    _mk(tmp_path, routed_components=100, routed_segments=100, routed_pad=0)
    sz = _pnr_sizes(tmp_path)
    assert sz["routed"] < sz["post_hold"]
    assert _nonmonotone(tmp_path) == []


# ------------------------------------------------- NEGATIVE / NO-LEAK -------

def test_routed_shrink_with_fewer_segments_still_fails(tmp_path):
    """A routed DEF that LOST routing segments is a truncation, not a
    re-encoding — it must still FAIL even though components grew."""
    _mk(tmp_path, routed_components=110, routed_segments=50, routed_pad=0)
    sz = _pnr_sizes(tmp_path)
    assert sz["routed"] < sz["post_hold"]
    assert _nonmonotone(tmp_path) != []


def test_routed_shrink_with_fewer_components_still_fails(tmp_path):
    """Instances went DOWN — no exemption (Check 3 also fires independently)."""
    _mk(tmp_path, routed_components=50, routed_segments=105, routed_pad=0)
    assert _nonmonotone(tmp_path) != []


def test_routed_shrink_without_routing_still_fails(tmp_path):
    """No routed geometry at all -> not the re-encoding case; must FAIL."""
    _mk(tmp_path, routed_components=110, routed_segments=0, routed_pad=0)
    assert _nonmonotone(tmp_path) != []
