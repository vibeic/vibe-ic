"""v0.3.9 — #508 + #509: signoff-LVS extraction recipe + GDS streamout
port labels. Both are EDA-recipe fixes whose end-to-end validation
(real spm/subservient GDS → magic extract → netgen, a multi-hour
container run) is the field agent's empirically-verified domain; these
tests pin the DETERMINISTIC recipe content the runner emits so the
field-proven fix can never silently regress.

#508 — the LVS extraction TCL ran a FLAT `extract all` on the top cell,
which on a real design (spm 201k insts / subservient 2470 top insts)
exploded to 69.39M / 1.99M Magic errors → over the #477 ceiling → empty
lvs.json → Step-31 LVS never got a real verdict. Fix = hierarchical
extraction (`extract no all; extract do local; extract all`, std cells
kept as transistor-level subckts) + `MAGIC_EXT_USE_GDS=1` (gates the
netgen fill/tap/decap ignore-class block; without it netgen mismatches
fill/tap device counts or SIGSEGVs). Field-verified: spm errors 69.39M
→ 6.59M (10.5x), subservient reaches netgen's terminal verdict.

#509 — the Magic DEF→GDS streamout wrote only the met PORT GEOMETRY, not
the pin TEXT on the label-purpose layer, so signoff LVS re-extraction saw
top I/O as internal nets → every top port a DISCONNECTED node → spurious
top-level 'do not match'. Fix = `port makeall` in the streamout TCL to
promote DEF pins to ports so the labels are written.

Chip-AGNOSTIC: pure Magic recipe, no chip-specific names.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ── #508 — hierarchical LVS extraction recipe ────────────────────────

def test_extraction_recipe_is_hierarchical():
    tcl = R._MAGIC_EXT2SPICE_TCL
    # the three-line hierarchical sequence, in order.
    assert "extract no all" in tcl
    assert "extract do local" in tcl
    # `extract all` still present (it's the final hierarchical extract),
    # but it must be PRECEDED by the black-boxing lines, not standalone.
    i_no = tcl.index("extract no all")
    i_local = tcl.index("extract do local")
    i_all = tcl.index("extract all")
    assert i_no < i_local < i_all, "hierarchical order violated"


def test_extraction_still_emits_ext2spice_lvs():
    tcl = R._MAGIC_EXT2SPICE_TCL
    assert "ext2spice lvs" in tcl
    assert "ext2spice -o $env(SPICE_OUT)" in tcl


def test_extraction_is_def_direct_not_gds():
    # #508/#509 round-2 FINAL: the field-validated LVS extraction reads the
    # routed DEF DIRECTLY (which builds the top pins as labels) and
    # `port makeall` promotes them to ports BEFORE extraction — the only
    # path that reached real top-port recognition. The GDS-based path
    # (gds read) is GONE from the LVS extraction.
    tcl = R._MAGIC_EXT2SPICE_TCL
    assert "def read $env(DEF)" in tcl
    assert "port makeall" in tcl
    assert "lef read $env(TLEF)" in tcl and "lef read $env(CLEF)" in tcl
    assert "gds read" not in tcl
    # port makeall must precede the extract pass.
    assert tcl.index("port makeall") < tcl.index("extract no all")


def test_lvs_path_does_not_force_magic_ext_use_gds():
    # field anti-lesson (#508/#509 r2): MAGIC_EXT_USE_GDS forces a leaf GDS
    # re-extract that floods 2900+ cell-internal disconnects on the
    # cell-level DEF-direct compare. Neither the extraction shell nor the
    # netgen shell may EXPORT it. Assert no CODE form sets it (the string
    # still appears in explanatory comments, which is fine).
    import inspect
    src = inspect.getsource(R._run_extraction_lvs)
    assert "export MAGIC_EXT_USE_GDS=1" not in src      # shell export
    assert 'f"MAGIC_EXT_USE_GDS=1 "' not in src         # f-string env prefix
    assert 'f"export MAGIC_EXT_USE_GDS' not in src      # f-string export


def _emitted_ignore_regexps(body):
    """The `ignore class` regexps the local netgen setup emits, as Python
    patterns (#211: the setup now matches the physical-cell FAMILY token as a
    name segment via TCL ERE, so we translate the POSIX classes and test the
    patterns BEHAVIOURALLY rather than by literal substring)."""
    import re as _re
    return [_re.compile(m.replace("[[:digit:]]", r"\d")
                        .replace("[[:alpha:]]", "[A-Za-z]"))
            for m in _re.findall(r"regexp \{([^}]*)\} \$_c", body)]


def test_local_netgen_setup_ignores_physical_cells(tmp_path):
    # the project-local netgen setup sources the PDK setup and
    # UNCONDITIONALLY ignores fill/tap/decap/fakediode on BOTH circuits.
    # #211 made the ignore patterns PDK-agnostic (family token on any library
    # prefix), so this asserts the emitted regexps actually IGNORE the
    # canonical sky130 physical cells while SPARING functional cells — a
    # behavioural check, stronger than the old literal-substring check.
    pdk = R._detect_pdk(Path("/nonexistent"), override="sky130A")
    host, cpath = R._emit_local_netgen_setup(tmp_path, pdk, "vibeic-eda")
    body = host.read_text()
    assert "sky130A_setup.tcl" in body          # sources PDK setup
    assert "$cells1" in body and "$cells2" in body  # both circuits
    pats = _emitted_ignore_regexps(body)
    assert pats, "no `ignore class` regexps emitted"
    for nm in ("sky130_fd_sc_hd__fill_8", "sky130_fd_sc_hd__tapvpwrvgnd_1",
               "sky130_fd_sc_hd__decap_4", "sky130_ef_sc_hd__fakediode_2"):
        assert any(p.search(nm) for p in pats), f"physical cell not ignored: {nm}"
    for nm in ("sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__inv_2",
               "sky130_fd_sc_hd__and2_1", "sky130_fd_sc_hd__dfxtp_1"):
        assert not any(p.search(nm) for p in pats), f"functional cell ignored: {nm}"
    # must NOT hardcode a design-specific functional class as ignored
    # (that could hide a real defect in another design).
    assert "dfrtp_1" not in body and "__inv_1" not in body


# ── #509 — streamout promotes DEF pins to ports ──────────────────────

def test_streamout_promotes_ports():
    tcl = R._MAGIC_STREAMOUT_TCL
    assert "port makeall" in tcl
    # promotion must happen BEFORE the gds write so the labels are
    # included in the stream.
    assert tcl.index("port makeall") < tcl.index("gds write")


def test_streamout_port_promotion_is_nonfatal():
    # a design with no DEF pins must not abort the streamout — the
    # promotion is wrapped in catch.
    tcl = R._MAGIC_STREAMOUT_TCL
    assert "catch {port makeall}" in tcl
    assert "PORT_MAKEALL_NONFATAL" in tcl


def test_streamout_still_writes_gds():
    tcl = R._MAGIC_STREAMOUT_TCL
    assert "gds write $env(GDS_OUT)" in tcl
    assert "MAGIC_GDS_WRITTEN" in tcl
