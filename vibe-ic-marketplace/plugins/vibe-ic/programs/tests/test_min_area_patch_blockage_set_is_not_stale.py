"""The post-route min-area patcher tested each candidate patch against a
blockage snapshot taken BEFORE any patch existed, and never registered the
patches it created — so patch N+1 was blind to patch N.

MEASURED (spm x ihp-sg13g2, sign-off KLayout deck `ihp-sg13g2.drc`, rule
"M2.b: Min. Metal2 space or notch: 0.21 um"): the routed design carried 3
M2.b violations. Attributing every violating edge back to the DEF showed
ALL THREE were collisions between `MIN_AREA_PATCH` RECT rectangles on
DIFFERENT nets — gaps of 0.154 / 0.176 / 0.125 um against a 0.21 um rule:

    net=__uuf__._057_ PATCH (66.328,96.875)-(66.825,97.165)
      vs net=__uuf__._158_ PATCH (66.135,96.035)-(66.345,96.721)
    net=__uuf__._146_ PATCH (123.928,100.235)-(124.425,100.525)
      vs net=net119    PATCH (123.255,100.235)-(123.752,100.525)
    net=__uuf__._050_ PATCH (123.735,99.395)-(124.232,99.685)
      vs net=__uuf__._146_ (124.220,99.810)-(124.420,100.380)

Causation was proved by DELETION, not by narrative: stripping the Metal2
RECT patches out of the routed DEF and re-running the same sign-off deck
took the count 3 -> 0 on this route AND 6 -> 0 on an independently-routed
one. The router was never at fault; the flow's own patcher was.

With the fix: 3 -> 1, reproduced on three independent runs (two at
thread_count 1, one at 32 — all three produced a byte-identical
routed.def). `MIN_AREA_PATCH_DONE` still reports patched=463 unpatchable=5,
i.e. the fix does NOT trade a spacing violation for an unpatched min-area
violation — it advances to the next candidate growth direction and patches
at a legal position instead.

THE RESIDUAL 1 IS KNOWINGLY OPEN and is a DIFFERENT defect: that collision
is ours-vs-TritonRoute's-own RECT patch, and `dbWirePathItr` cannot see RECT
shapes at all (probed: it returned exactly one Metal2 shape for nets whose
DEF carries a segment plus several RECT patches). These tests therefore pin
the ours-vs-ours fix ONLY, and pin the limitation as DISCLOSED so it cannot
be silently forgotten.

§4.05 — direction of safety: the dangerous direction is a patch landing too
close, because that is a real sign-off violation shipped into the GDS. A
patch REFUSED merely raises `unpatchable`, which is already a loud,
disclosed outcome. So the blockage set must only ever GROW.
"""
import re
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parents[1] / "phase3_one_shot_runner.py")
SRC = PROG.read_text()


def _tcl_template() -> str:
    m = re.search(r'_MIN_AREA_PATCH_TCL = r"""(.*?)"""', SRC, re.S)
    assert m, "could not locate _MIN_AREA_PATCH_TCL in phase3_one_shot_runner.py"
    return m.group(1)


def _tcl_code_only() -> str:
    """The TCL template minus its full-line comments.

    The comments are DISCLOSURE — this codebase deliberately records the
    design/PDK a defect was measured on ("MEASURED (spm x sky130A)"), and
    that evidence is what makes a fix auditable. The chip-AGNOSTIC rule
    binds the EXECUTABLE tcl: no literal may reach a decision.
    """
    return "\n".join(
        ln for ln in _tcl_template().splitlines()
        if not ln.lstrip().startswith("#")
    )


def _block_after(text: str, anchor: str, lines: int = 20) -> str:
    i = text.index(anchor)
    return text[max(0, i - 1400):i + 200]


def test_min_area_patch_registers_each_patch_into_the_blockage_set():
    """The applied patch must be added to `all` before the loop breaks."""
    tcl = _tcl_template()
    seg = _block_after(tcl, "incr patched; set ok 1")
    assert "dict lappend all $ln" in seg, (
        "min_area_patch applies a RECT patch without registering it in the "
        "`all` blockage set — patch N+1 is blind to patch N and the two can "
        "land inside the layer's own min SPACING (measured: 3x M2.b, all "
        "patch-vs-patch)."
    )


def test_via_enclosure_patcher_registers_each_patch_into_the_blockage_set():
    """Same defect, same fix, in the via-enclosure patcher's `allnet` set."""
    tcl = _tcl_template()
    seg = _block_after(tcl, "incr patched; set done 1")
    assert "dict lappend allnet $ln" in seg, (
        "the via-enclosure patcher applies a patch without registering it in "
        "`allnet`, so later candidates are spacing-tested against a snapshot "
        "that predates every patch."
    )


def test_registration_is_net_blind_because_the_drc_rule_is():
    """The sign-off rule is a geometric `space()` check — it does not care
    whose net a polygon belongs to. Registering the patch under a same-net
    exemption would reintroduce exactly the collisions this fix removes, so
    the min-area registration must carry no net tag."""
    tcl = _tcl_template()
    m = re.search(r"dict lappend all \$ln \[list ([^\]]*)\]", tcl)
    assert m, "min-area patch registration not found"
    operands = m.group(1).split()
    assert operands == ["$px1", "$py1", "$px2", "$py2"], (
        "the min-area blockage set is UNTAGGED (plain {x1 y1 x2 y2}); "
        f"registering {operands!r} changes its shape and will silently break "
        "the `ma_touch $bl $o` comparison in the clash test."
    )


def test_patch_registration_only_grows_the_blockage_set():
    """§4.05 — nothing may ever REMOVE from the blockage set: shrinking it
    re-opens the shipped-violation direction."""
    tcl = _tcl_template()
    for bad in ("dict unset all", "dict unset allnet",
                "set all [dict create]\n    ", "dict remove $all"):
        assert bad not in tcl, f"blockage set is narrowed via {bad!r}"
    # `all` is seeded exactly once, in the 1st pass.
    assert tcl.count("set all [dict create]") == 1


def test_rect_invisibility_stays_disclosed():
    """The residual ours-vs-TritonRoute collision is only defensible while it
    is DISCLOSED. If someone deletes the limitation note, this test fails
    rather than letting the gap go quiet."""
    header = SRC[SRC.index("_MIN_AREA_PATCH_TCL"):][:4000]
    assert "KNOWN LIMITATION" in header
    assert "dbWirePathItr" in header, (
        "the limitation note must name the API that cannot see RECT shapes"
    )
    for claim in ("RECT", "UNDER-count"):
        assert claim in header, f"limitation note no longer states {claim!r}"


@pytest.mark.parametrize("literal", [
    "66.328", "123.928", "124.232", "__uuf__", "net119",
    "ihp-sg13g2", "sg13g2", "Metal2", "spm",
])
def test_fix_carries_no_design_or_pdk_literal(literal):
    """chip-AGNOSTIC: the fix must not hardcode the coordinates, nets, layer
    or PDK it was found on. Only EXECUTABLE tcl is judged — the template's
    comments (and this file's docstring) deliberately quote the measured
    evidence, which is disclosure, not a decision input."""
    tcl = _tcl_code_only()
    assert literal not in tcl, (
        f"{literal!r} leaked into the min-area patch TCL; the patcher must "
        "read every value from the active tech LEF."
    )
