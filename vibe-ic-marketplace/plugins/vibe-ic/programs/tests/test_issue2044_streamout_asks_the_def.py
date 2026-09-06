"""#2044 F4 + F7 — the DEF→GDS streamout asks the DEF, and the DESIGN line is
found by grammar rather than by a byte offset.

Two defects, one file, one cause: the streamout took SOME of its facts from the
DEF and the rest from somewhere else, and neither shortcut could report itself.

F7 — `_def_design_name` READ 65536 BYTES AND SEARCHED THOSE. DEF puts `DESIGN`
in the header but sets no ceiling on the header: `#` comments are legal
anywhere, so a tool that stamps a provenance banner ahead of `DESIGN` pushes it
past any fixed offset. Past it, the function returned None — and None is not
inert. `_streamout_top` reads None as "the DEF agrees with the runner's top"
and streams the file-naming top, which is exactly the failure `_def_design_name`
was written to stop: MEASURED at plugin 1.17.4, `load <a cell this database does
not have>` creates an EMPTY cell of that name and `gds write` writes it —
`spm.gds`, 106 bytes, one empty structure, on which sign-off DRC then reported
`violations=0`. The byte bound was silently reintroducing the bug the function
fixes.

F4 — THE STREAMOUT NEVER ASKED THE DEF WHICH MASTERS IT INSTANTIATES. It took
the physical top FROM the DEF and its LEF/GDS view list from `pdk.macro_lefs` /
`pdk.macro_gds` alone, while `_def_reopen_extra_lefs_c` — on the same file —
derives exactly that for every fresh OpenROAD session. So the two could disagree
about which masters exist, and the streamout was the half that could not tell.

MEASURED IN THE FROZEN IMAGE (ghcr.io/vibeic/vibeic-eda sha256:06537f7e,
label 0.3.46; magic 8.3, sky130A), a DEF instantiating one master no LEF or GDS
defines::

    Cell totally_absent_master_zz couldn't be read
    DEF read, Line 9 (Error): Cell totally_absent_master_zz is not defined.
      Maybe you have not read the corresponding LEF file?
    DEF Read: encountered 1 error total.
       Generating output for cell probetop
    MAGIC_GDS_WRITTEN

Magic wrote a 3794-byte GDS and exited 0. Every guard in `_magic_def_to_gds`
passed it: the file is non-empty, `_detect_vacuous_magic` returns
`geometry_loaded=True`, no unknown layer, no empty bbox. Sign-off DRC, LVS and
the hand-off package therefore received a GDS with a cell missing from it, and
nothing anywhere said so.

WHAT IS TRUE NOW. `_magic_def_to_gds` resolves the DEF once (`#2044`'s
`_def_reopen_resolution`), ADDS the views the DEF's own masters need that the
PDK list does not already offer, and — after the stream — REFUSES BY NAME any
master the DEF instantiates that Magic's own transcript says it could not
resolve.

WHY THE TRANSCRIPT AND NOT THE VIEW LIST. Magic resolves cells from its own PDK
search path too — measured, and recorded in `_def_design_name`: with no IO views
passed at all Magic still read `gf180mcu_fd_io__in_c` from `$PDKPATH`. So
"absent from `pdk.macro_lefs`" does NOT mean "missing from the GDS", and a
refusal built on the view list alone would reject runs that are fine. Magic's
transcript is the one witness that cannot be wrong about what Magic resolved.

Chip/PDK-AGNOSTIC: every fixture below names a generic master; the one real cell
name that appears does so inside a quoted MEASURED transcript, as evidence.
"""
import ast
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ── F7 fixtures ──────────────────────────────────────────────────────────
_HEADER_TAIL = """UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100 100 ) ;
COMPONENTS 1 ;
    - u_a MASTER_A + PLACED ( 0 0 ) N ;
END COMPONENTS
END DESIGN
"""


def _def_with_banner(banner_bytes: int, design: str = "chip_top") -> str:
    """A DEF that is legal in every respect except that `banner_bytes` of
    legal `#` comment stand between the first line and its DESIGN line."""
    line = "# provenance: this run was produced by the flow under test\n"
    n = max(1, banner_bytes // len(line) + 1)
    return ("VERSION 5.8 ;\n"
            + line * n
            + f"DESIGN {design} ;\n"
            + _HEADER_TAIL)


def test_f7_design_line_found_past_the_old_64kib_bound(tmp_path):
    """RED ON BASE: the byte-bounded read returned None here.

    The banner is deliberately > 65536 bytes, the size of the read the
    pre-fix implementation performed."""
    text = _def_with_banner(80 * 1024)
    assert len(text.split("DESIGN chip_top")[0]) > 65536, (
        "fixture must push DESIGN past the bound it is testing")
    p = tmp_path / "big_header.def"
    p.write_text(text)
    assert R._def_design_name(p) == "chip_top"


def test_f7_streamout_top_substitutes_past_the_old_bound(tmp_path):
    """The consequence, not just the parser: with the DESIGN line unreadable
    the streamout streamed the runner's file-naming top. It no longer can."""
    p = tmp_path / "big_header.def"
    p.write_text(_def_with_banner(80 * 1024, design="chip_top"))
    cell, disclosure = R._streamout_top(p, "core")
    assert cell == "chip_top"
    assert "chip_top" in disclosure and disclosure, (
        "a substitution must be NAMED in the step's own detail")


def test_f7_control_ordinary_def_is_unchanged(tmp_path):
    """The byte-identical control: a DEF whose header is well inside the old
    bound answers exactly as before, and a headerless one still answers None."""
    p = tmp_path / "plain.def"
    p.write_text("VERSION 5.8 ;\nDESIGN chip_top ;\n" + _HEADER_TAIL)
    assert R._def_design_name(p) == "chip_top"
    assert R._streamout_top(p, "chip_top") == ("chip_top", "")

    q = tmp_path / "no_design.def"
    q.write_text("VERSION 5.8 ;\nUNITS DISTANCE MICRONS 1000 ;\n"
                 "COMPONENTS 1 ;\n    - u_a MASTER_A ;\nEND COMPONENTS\n")
    assert R._def_design_name(q) is None

    assert R._def_design_name(tmp_path / "absent.def") is None


def test_f7_body_is_never_read_when_design_is_absent(tmp_path):
    """Grammar-bounded, not unbounded: the replacement must still stop at the
    header. A DESIGN-less DEF with a large body answers None without the body
    ever being consumed."""
    body = "".join(f"    - u_{i} MASTER_A + PLACED ( {i} 0 ) N ;\n"
                   for i in range(60000))
    p = tmp_path / "headerless_big.def"
    p.write_text("VERSION 5.8 ;\nCOMPONENTS 60000 ;\n" + body
                 + "END COMPONENTS\nEND DESIGN\n")
    assert p.stat().st_size > 2 * 1024 * 1024
    assert R._def_design_name(p) is None
    # The stop is stated in the grammar, so it is assertable as such.
    assert R._DEF_BODY_SECTION_RE.match("COMPONENTS 60000 ;")
    assert R._DEF_BODY_SECTION_RE.match("  PINS 4 ;")
    assert not R._DEF_BODY_SECTION_RE.match("# a comment")
    assert not R._DEF_BODY_SECTION_RE.match("PROPERTYDEFINITIONS")


# ── F4: the refusal, on the MEASURED transcript ──────────────────────────
# Verbatim from the frozen image. Kept whole: a paraphrase of a tool's output
# is not evidence about that tool.
_MEASURED_MISSING_MASTER = """Reading DEF data from file /work/t.def.
This action cannot be undone.
Cell totally_absent_master_zz couldn't be read
DEF read, Line 9 (Error): Cell totally_absent_master_zz is not defined.  \
Maybe you have not read the corresponding LEF file?
  Processed 2 subcell instances total.
DEF read: Processed 11 lines.
DEF Read: encountered 1 error total.
   Copying output for cell sky130_fd_sc_hd__inv_1 from $PDKPATH/libs.ref/\
sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds
   Generating output for cell probetop
MAGIC_GDS_WRITTEN
"""

# The 106-byte-GDS transcript, quoted in `_def_design_name`. Magic says the
# same words about a TOP cell it does not have. That is NOT a missing master.
_MEASURED_MISSING_TOP = """Cell spm couldn't be read
No such file or directory
Cannot rename; cell "spm" already exists!
"""


def test_f4_refuses_by_name_the_master_the_def_asked_for():
    """RED ON BASE: nothing consulted the transcript for this at all."""
    masters = {"sky130_fd_sc_hd__inv_1", "totally_absent_master_zz"}
    assert R._magic_unresolved_masters(_MEASURED_MISSING_MASTER, masters) == [
        "totally_absent_master_zz"]


def test_f4_a_resolved_master_is_not_named():
    """The other direction of the same check: a master Magic DID resolve must
    never be reported. Without this, the refusal is one that cannot pass."""
    assert R._magic_unresolved_masters(
        _MEASURED_MISSING_MASTER, {"sky130_fd_sc_hd__inv_1"}) == []


def test_f4_top_cell_message_is_not_a_missing_master():
    """The intersection with the DEF's own masters is load-bearing: Magic
    prints `Cell <x> couldn't be read` for an absent TOP too, and that case
    belongs to `_streamout_top`, not here. Refusing on it would turn the
    106-byte-GDS run into a DIFFERENT wrong answer."""
    assert R._magic_unresolved_masters(_MEASURED_MISSING_TOP,
                                       {"MASTER_A", "MASTER_B"}) == []


def test_f4_clean_transcript_and_empty_inputs_refuse_nothing():
    """The control. A stream in which everything resolved must be inert here —
    this is the case every passing run takes."""
    clean = ("Reading DEF data from file /work/t.def.\n"
             "  Processed 2 subcell instances total.\n"
             "   Generating output for cell chip_top\n"
             "MAGIC_GDS_WRITTEN\n")
    assert R._magic_unresolved_masters(clean, {"MASTER_A", "MASTER_B"}) == []
    assert R._magic_unresolved_masters(_MEASURED_MISSING_MASTER, set()) == []
    assert R._magic_unresolved_masters("", {"MASTER_A"}) == []
    assert R._magic_unresolved_masters(None, {"MASTER_A"}) == []


def test_f4_every_named_master_is_reported_sorted():
    """More than one missing master is a list, not a first-hit."""
    t = ("Cell m_zeta couldn't be read\n"
         "Cell m_alpha is not defined.\n"
         "Cell m_alpha couldn't be read\n")
    assert R._magic_unresolved_masters(t, {"m_alpha", "m_zeta", "m_ok"}) == [
        "m_alpha", "m_zeta"]


# ── F4: the wiring, by AST ───────────────────────────────────────────────
# Grep cannot tell a call from a mention in a comment, and both halves of this
# fix live inside one function. These read the tree.
def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse((PROGRAMS / "phase3_one_shot_runner.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _calls(fn: ast.FunctionDef) -> set:
    return {n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def test_f4_streamout_consumes_the_resolver_and_the_refusal():
    """The non-vacuity guard, and the re-reddening mutation's target: make the
    streamout stop asking the DEF, or stop reading the transcript, and this
    fails."""
    calls = _calls(_fn("_magic_def_to_gds"))
    assert "_def_reopen_resolution" in calls, (
        "the streamout must resolve the DEF's facts, not re-derive them")
    assert "_def_reopen_extra_lefs_c" in calls, (
        "the view list must be extended from the DEF's own masters")
    assert "_magic_unresolved_masters" in calls, (
        "the stream must be refused when a master went unresolved")
    assert "_streamout_top" in calls, (
        "_streamout_top remains THE design-name authority here")


def test_f7_design_name_reads_no_fixed_byte_count():
    """The F7 mutation target: restoring any `fh.read(<n>)` here re-reddens."""
    fn = _fn("_def_design_name")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "read"
                and node.args):
            raise AssertionError(
                "the DESIGN line is bounded by DEF grammar, not by a byte "
                "count; a sized read here is the F7 defect returning")
    assert "_DEF_BODY_SECTION_RE" in {
        n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
