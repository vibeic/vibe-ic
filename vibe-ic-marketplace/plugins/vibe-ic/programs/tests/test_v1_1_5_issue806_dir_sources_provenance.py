"""ORGANIC #806 (#770) — iface_conformance_v2 PORT-DIRECTION provenance was keyed
on the NAME-sources union (`sources`), so a markdown table with NO Direction
column (which supplies only the NAME, direction='') conferred STRUCTURAL
provenance on a direction actually scraped only from descriptive PROSE ("Data
output from FIFO") → is_block_eligible(STRUCTURAL, CONTRADICTED)=True → a correct
RTL declaration was hard-blocked.

FIX: a `dir_sources` set populated by `add()` ONLY when a source establishes /
agrees the stored non-empty direction; PORT-DIRECTION provenance is computed from
`dir_sources`. A directionless-table name no longer confers STRUCTURAL on a
prose-only direction → a CONTRADICTED RTL declaration downgrades to advisory.

§4.05: a real Direction-column row / a direction-declaring given-code header /
an agreeing structural+prose source all still populate dir_sources STRUCTURALLY
→ still block. chip-AGNOSTIC.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as I  # noqa: E402
import _provenance as P            # noqa: E402

_STRUCT = sorted(I._STRUCTURAL_IFACE_SOURCES)[0]   # a real structural source tag


def test_806_directionless_name_then_prose_dir_is_prose_heuristic():
    pif = I.PromptIface()
    # a DIRECTION-LESS table names the port (no direction)…
    pif.add("foo", "", "table")
    # …then a free-PROSE scrape supplies the direction.
    pif.add("foo", "output", "prose_dir")
    assert pif.ports["foo"] == "output"
    assert "table" in pif.sources["foo"]
    # dir_sources owns ONLY the prose source → provenance stays PROSE_HEURISTIC.
    assert pif.dir_sources["foo"] == {"prose_dir"}
    assert I._iface_provenance(pif.dir_sources["foo"]) == P.PROSE_HEURISTIC


def test_806_noleak_structural_direction_source_blocks():
    pif = I.PromptIface()
    pif.add("dat", "output", _STRUCT)     # real Direction-column / given-code
    assert pif.dir_sources["dat"] == {_STRUCT}
    assert I._iface_provenance(pif.dir_sources["dat"]) == P.STRUCTURAL


def test_806_noleak_agreeing_structural_plus_prose_stays_structural():
    pif = I.PromptIface()
    pif.add("sig", "input", _STRUCT)      # establishes structurally
    pif.add("sig", "input", "prose_dir")  # prose AGREES → corroborates
    assert _STRUCT in pif.dir_sources["sig"]
    assert I._iface_provenance(pif.dir_sources["sig"]) == P.STRUCTURAL


def test_806_directionless_only_has_empty_dir_sources():
    pif = I.PromptIface()
    pif.add("bar", "", "table")           # named, no direction asserted
    assert pif.dir_sources.get("bar", set()) == set()


def test_806_prose_contradicted_by_rtl_is_advisory():
    # the end-state the fix targets: prose-only direction (PROSE_HEURISTIC) that
    # the RTL CONTRADICTS → advisory, not block-eligible.
    prov = P.PROSE_HEURISTIC
    corr = P.corroborate_direction("output", "input")   # CONTRADICTED
    assert P.is_block_eligible(prov, corr) is False
    # …but a STRUCTURAL direction contradicted by RTL still blocks.
    assert P.is_block_eligible(P.STRUCTURAL, corr) is True


# ── END-STATE: the real iface_conformance_v2 program (--strict). A directionless
#    table + prose direction contradicted by RTL → advisory (rc 0); a real
#    Direction-column reversal still hard-blocks (rc 1). ────────────────────────
import subprocess  # noqa: E402

_PROG = PROGRAMS / "iface_conformance_v2.py"


def test_806_endstate_directionless_table_prose_dir_is_advisory(tmp_path):
    (tmp_path / "spec.txt").write_text(
        "| Signal | Width |\n|---|---|\n| `dout` | 8 |\n\n"
        "The `dout` port is the data output from the FIFO.\n")
    (tmp_path / "rtl.sv").write_text("module foo(input [7:0] dout); endmodule")
    r = subprocess.run(
        [sys.executable, str(_PROG), "--prompt", str(tmp_path / "spec.txt"),
         "--rtl", str(tmp_path / "rtl.sv"), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)   # prose-only → advisory


def test_806_endstate_noleak_real_direction_column_still_blocks(tmp_path):
    (tmp_path / "spec.txt").write_text(
        "| Signal | Direction |\n|---|---|\n| `dout` | output |\n")
    (tmp_path / "rtl.sv").write_text("module foo(input [7:0] dout); endmodule")
    r = subprocess.run(
        [sys.executable, str(_PROG), "--prompt", str(tmp_path / "spec.txt"),
         "--rtl", str(tmp_path / "rtl.sv"), "--strict"],
        capture_output=True, text=True)
    assert r.returncode == 1, (r.stdout + r.stderr)   # structural → still blocks
    assert "PORT-DIRECTION" in r.stdout


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
