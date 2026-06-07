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


def test_extraction_env_sets_magic_ext_use_gds(monkeypatch, tmp_path):
    # the Magic-extraction subprocess must export MAGIC_EXT_USE_GDS=1.
    import inspect
    src = inspect.getsource(R._run_extraction_lvs)
    assert "MAGIC_EXT_USE_GDS=1" in src


def test_netgen_shell_exports_magic_ext_use_gds():
    # #508 ROUND-2 (dormant-feature, the #511 lesson): MAGIC_EXT_USE_GDS=1
    # was exported ONLY in the Magic-extraction shell, but the ignore-class
    # block lives in the NETGEN setup loaded by a SEPARATE _docker_exec
    # (env does not persist across calls) — so at netgen time the block was
    # OFF. The env MUST be wired into the netgen command's own shell. Pin
    # it structurally: the export must appear in the ~600 chars preceding
    # the `netgen -batch lvs` invocation (i.e. in the netgen shell, not
    # merely somewhere in the function).
    import inspect
    src = inspect.getsource(R._run_extraction_lvs)
    i = src.index("netgen -batch lvs")
    window = src[max(0, i - 600):i]
    assert "MAGIC_EXT_USE_GDS=1" in window, (
        "MAGIC_EXT_USE_GDS=1 not wired into the netgen shell — the "
        "ignore-class block would be OFF at netgen time (#508 r2)")


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
