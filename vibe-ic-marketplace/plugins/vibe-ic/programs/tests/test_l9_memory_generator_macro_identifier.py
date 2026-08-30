"""The L9 memory walker threw away a REAL SRAM hard macro.

`benchmark-data/ic/edge_llm_accel` stages `fakeram45_2048x39` — LEF, Liberty
and behavioural model — under `input/pdk_local/fakeram45/`, and the macro did
not reach `L9.memories[]`.

The walker RAN and FOUND the macro; the promotion gate
`_v1_6_441_is_useful_memory_entry` threw it away, because the macro cell name
fails BOTH of the gate's clauses:

  (a) structural — depth/width were never extracted. `_V1_6_426_RE_MEMORY_PROSE`
      captures `<depth>x<width>` only AFTER the type keyword, and here the
      dimensions live INSIDE the identifier, to the LEFT of the keyword.
  (b) name token — `_MEMORY_NAME_TOKEN_RE` requires a LEFT WORD BOUNDARY, and in
      `fakeram45` the `ram` is preceded by `e`. `sram45_2048x39` promotes,
      `fakeram45_2048x39` does not.

WHAT SEPARATES THE MACRO FROM THE JUNK — AND WHAT DOES NOT
----------------------------------------------------------
`_MEMORY_NAME_TOKEN_RE` is untouched: its strict left boundary is what keeps
PROGRAM / DIAGRAM / HISTOGRAM / diagram_ctrl out of `memories[]` (pinned by
`test_v1_0_5_issue612_memory_walker_nonmemory_tokens.py`).

The first attempt at a second clause paired the morpheme with a
`<digits>x<digits>` "organisation token" in the same name, tightened it, and
was abandoned. That clause is gone;
`test_the_tightest_lexical_rule_is_still_wrong_in_both_directions` spells the
tightest form out as a regex and scores it, and
`test_organisation_token_alone_never_promotes` keeps the token off the
promotion path.

The evidence that does separate them comes from OUTSIDE the string: the design
under analysis staged `fakeram45_2048x39.lef`, `.lib` and `.v` under its own
`input/pdk_local/fakeram45/`, and that LEF declares `MACRO fakeram45_2048x39`.
`test_real_doc_without_the_staged_artifact_stays_a_candidate` shows the
artefact — not the name — is the lever, and
`test_staged_artifact_is_the_only_lever` states what the surviving morpheme
conjunct still lets through.

The promoted row keeps `depth`/`width` as None: assigning them from the name
would FABRICATE NUMBERS, because the name does not say which number is which.

THE SCAN THAT READS THE ARTEFACT HAD TO BE FIXED TOO
----------------------------------------------------
Two ways the scan missed the artefact:

  * it skipped EVERY symlink, file symlinks included — so staging the macro by
    symlinking a PDK / IP tree into place produced an empty staged set and
    `memories == []`, the original defect through a different door. Symlinks
    are now followed; the broken link, the loop and the out-of-project target
    are each decided explicitly and each pinned below.
  * its caps truncated in silence, and a plain breadth-first walk drained the
    first directory completely — so a large sibling directory could spend the
    entire budget and the promotion vanished with nothing said. Order is now
    fair-share across directories, and what the caps DO cut is reported on
    stderr, in `L9.staged_macro_scan_truncated`, and on the very
    `memory_candidates[]` row that would have been promoted.

chip-AGNOSTIC: open LEF / Liberty / GDS file-and-keyword conventions, read out
of whatever the design under analysis staged. No chip-class string literal
participates in the rule.
"""
import inspect
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _published_corpus import corpus_root, skip_reason  # noqa: E402

U = P._v1_6_441_is_useful_memory_entry
_MEMORY_NAME_TOKEN_PATTERN = P._MEMORY_NAME_TOKEN_RE.pattern

# The corroborated clause needs the design's staged-macro set, so production
# passes the design root into the emitter. A MUTANT built from the parent
# commit has the two-argument emitter; detect that by SIGNATURE rather than by
# catching TypeError, so this shim can never swallow a real TypeError raised
# inside the emitter — and so the real-document tests below fail on a mutant
# with their own assertion, not with a call-shape error.
_ACCEPTS_PROJECT = "project" in inspect.signature(
    P._v1_6_426_emit_memories).parameters


def _emit(l9, extracted, project):
    if _ACCEPTS_PROJECT:
        P._v1_6_426_emit_memories(l9, extracted, project)
    else:
        P._v1_6_426_emit_memories(l9, extracted)


#: The design input this module reads, relative to whichever tree holds the
#: corpus. The `benchmark-data/` prefix belongs to the IN-REPO layout only.
_DOCS_REL = Path("ic") / "edge_llm_accel" / "input" / "docs"


def _real_docs_dir():
    """Locate the on-disk edge_llm_accel input docs, POINTER FIRST.

    THE WALK BELOW COULD NOT SUCCEED ON ANY HOST. It searched `PLUGIN` and every
    parent for `benchmark-data/ic/edge_llm_accel/input/docs`, and that tree left
    this repository at `c5d7f2d00`: `git ls-tree -r HEAD -- benchmark-data`
    matches nothing. So the skip below was not a capability probe — no
    provisioning could satisfy it, on any machine, ever — while reading in every
    report as an ordinary healthy skip. Silently-absent coverage is the shape
    that lets a regression land unnoticed, which is exactly what this module's
    load-bearing end-to-end test is here to prevent.

    `corpus_root()` is the repository's one answer to "where are the published
    trees", as `test_tool_diagnostic_id_gate.py:338` already uses it. The
    in-repo walk is KEPT and tried second, so a checkout that still carries the
    tree is read exactly as before.
    """
    root = corpus_root()
    if root is not None and (root / _DOCS_REL).is_dir():
        return root / _DOCS_REL
    rel = Path("benchmark-data") / _DOCS_REL
    for cand in [PLUGIN, *PLUGIN.parents]:
        d = cand / rel
        if d.is_dir():
            return d
    return None


def _real_docs():
    """(docs_dir, design_root, {filename: body}) or None when not on disk."""
    docs = _real_docs_dir()
    if docs is None:
        return None
    extracted = {}
    for fn in sorted(os.listdir(docs)):
        p = docs / fn
        if p.is_file():
            extracted[fn] = p.read_text(encoding="utf-8", errors="replace")
    return docs, docs.parent.parent, extracted


# ---------------------------------------------------------------- real doc


def test_real_edge_llm_accel_docs_promote_the_sram_macro():
    """END-TO-END over the REAL on-disk benchmark documents and the REAL
    on-disk staged macro.

    This is the load-bearing test: it drives `_v1_6_426_emit_memories` with the
    actual `benchmark-data/ic/edge_llm_accel/input/docs/*.md` bodies and the
    actual design root — no synthetic document, no synthetic artefact — and
    asserts the chip's only SRAM hard macro reaches `memories[]`."""
    real = _real_docs()
    if real is None:
        pytest.skip(f"ic/edge_llm_accel/input/docs: {skip_reason()}")
    _docs, design, extracted = real
    assert extracted, "no input docs read"

    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, extracted, design)

    names = [e.get("name") for e in (l9.get("memories") or [])]
    assert "fakeram45_2048x39" in names, (
        "the chip instantiates 20 fakeram45_2048x39 hard macros (LEF/Liberty/"
        ".v on disk under input/pdk_local/fakeram45/); it must reach "
        "L9.memories[], got memories=%r candidates=%r"
        % (l9.get("memories"), l9.get("memory_candidates")))
    assert l9.get("no_memories_in_input") is False


def test_real_doc_promoted_row_does_not_fabricate_depth_width():
    """The promoted row must NOT carry invented dimensions: the name does not
    say which number is depth and which is width, so depth/width stay None and
    the pre-existing `low_confidence` marker stays on the row."""
    real = _real_docs()
    if real is None:
        pytest.skip(f"ic/edge_llm_accel/input/docs: {skip_reason()}")
    _docs, design, extracted = real
    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, extracted, design)
    rows = [e for e in (l9.get("memories") or [])
            if e.get("name") == "fakeram45_2048x39"]
    assert rows, "macro not promoted — see the end-to-end test"
    for r in rows:
        assert r.get("depth") is None, (
            "depth must not be inferred from the macro name: fakeram45 names "
            "are depth x width but sky130 sram names are width x depth")
        assert r.get("width") is None
        assert r.get("low_confidence") is True


def test_real_doc_without_the_staged_artifact_stays_a_candidate():
    """THE ARTEFACT IS THE LEVER, NOT THE NAME.

    Same real documents, same real macro name, but no design root — so no
    staged-macro evidence. The row must stay in `memory_candidates[]`. If this
    starts passing on name shape alone, the clause has grown a lexical rule
    back."""
    real = _real_docs()
    if real is None:
        pytest.skip(f"ic/edge_llm_accel/input/docs: {skip_reason()}")
    if not _ACCEPTS_PROJECT:
        pytest.skip("emitter predates the staged-artefact clause")
    l9 = {"top_module": "edge_llm_accel"}
    P._v1_6_426_emit_memories(l9, real[2], None)
    promoted = {e.get("name") for e in (l9.get("memories") or [])}
    candidates = {e.get("name") for e in (l9.get("memory_candidates") or [])}
    assert "fakeram45_2048x39" not in promoted
    assert "fakeram45_2048x39" in candidates


def test_real_doc_promoted_row_cites_the_staged_artifact():
    """Provenance: the row records WHY it was promoted, and the artefact it
    points at is really on disk."""
    real = _real_docs()
    if real is None:
        pytest.skip(f"ic/edge_llm_accel/input/docs: {skip_reason()}")
    if not _ACCEPTS_PROJECT:
        pytest.skip("emitter predates the staged-artefact clause")
    _docs, design, extracted = real
    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, extracted, design)
    rows = [e for e in (l9.get("memories") or [])
            if e.get("name") == "fakeram45_2048x39"]
    assert rows
    assert rows[0].get("promotion_evidence") == (
        "staged_macro_artifact:input/pdk_local")
    staged = design / "input" / "pdk_local" / "fakeram45"
    for suffix in (".lef", ".lib", ".v"):
        assert (staged / ("fakeram45_2048x39" + suffix)).is_file(), (
            "the promotion cites a staged artefact that is not on disk")
    assert "MACRO fakeram45_2048x39" in (
        staged / "fakeram45_2048x39.lef").read_text(
            encoding="utf-8", errors="replace")


def test_real_doc_non_macro_neighbour_stays_a_candidate():
    """Precision guard on the SAME real document: the PDK standard-cell
    library name latched off the same prose (`NangateOpenCellLibrary`) is not
    staged as a macro and carries no memory morpheme, so it must stay in
    `memory_candidates[]`."""
    real = _real_docs()
    if real is None:
        pytest.skip(f"ic/edge_llm_accel/input/docs: {skip_reason()}")
    _docs, design, extracted = real
    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, extracted, design)
    promoted = {e.get("name") for e in (l9.get("memories") or [])}
    candidates = {e.get("name") for e in (l9.get("memory_candidates") or [])}
    assert "NangateOpenCellLibrary" not in promoted
    assert "NangateOpenCellLibrary" in candidates


# ------------------------------------------------- end-to-end junk fragments


# L1-L9 document prose in the Markdown / pipe-table / backtick shapes the
# v1.6.468 back-walker was built for. Each fragment makes the walker latch a
# NON-memory identifier that carries both a memory morpheme and a
# `<digits>x<digits>` (or hex) group. None of these designs stages a macro, so
# every row must stay in `memory_candidates[]`.
_JUNK_FRAGMENTS = {
    "A_systolic_L8.md":
        "## 8.2 PE array\n| module | note |\n|---|---|\n"
        "| `systolic_array_16x16_param` | weights fed from on-chip SRAM |\n",
    "B_hci_errcode_L4.md":
        "## 4.3 error codes\n| code | constant | note |\n|---|---|---|\n"
        "| 0x12 | `CMD_PARAM_ERR_0x1F` | illegal host FIFO command "
        "parameter |\n",
    "C_video_L2.md":
        "The `chroma_intra_4x4` transform unit reads the line cache.\n",
    "D_diagram_L2.md":
        "See `block_diagram_16x9`; the register file sits in the middle.\n",
    "E_filename_window_L7.md":
        "The behavioural model uses `param_matrix_4x4.v` next to the RAM "
        "model.\n",
    "F_dsp_L2.md":
        "The `histogram_256x8` statistics unit writes back to the FIFO.\n",
    "G_pkg_L9.md":
        "| package | `pin_grid_array_20x20_diagram` | keep clear of the SRAM "
        "macro area |\n",
    "I_bus_L3.md":
        "Interface `member_bus_2x32` hangs directly off the cache.\n",
    "J_xbar_L2.md":
        "`crossbar_8x8_parametric` connects the four SRAM banks.\n",
}


@pytest.mark.parametrize("fname", sorted(_JUNK_FRAGMENTS))
def test_junk_fragment_stays_a_candidate(fname):
    """Nine end-to-end fragments. None of these designs stages a macro, so
    nothing here may reach `memories[]`."""
    l9 = {"top_module": "dut_top"}
    _emit(l9, {fname: _JUNK_FRAGMENTS[fname]}, None)
    promoted = [e.get("name") for e in (l9.get("memories") or [])]
    assert promoted == [], (
        "%s promoted %r into L9.memories[] — none of these is a memory"
        % (fname, promoted))
    assert [e.get("name") for e in (l9.get("memory_candidates") or [])], (
        "%s should still leave a candidate row for provenance" % fname)


# -------------------------------------------------- staged-artefact lookup


def _stage(tmp_path, rel, body=""):
    p = Path(tmp_path) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_staged_lookup_reads_file_stems_and_lef_macro_headers(tmp_path):
    _stage(tmp_path, "input/pdk_local/fakeram45/fakeram45_1024x32.lib")
    _stage(tmp_path, "input/pdk_local/fakeram45/fakeram45_1024x32.v")
    _stage(tmp_path, "input/pdk_local/bundle/many.lef",
           "VERSION 5.8 ;\nMACRO dffram_1024x32\n  CLASS BLOCK ;\n"
           "END dffram_1024x32\nMACRO sky130_sram_2kbyte_1rw1r_32x512_8\n"
           "END sky130_sram_2kbyte_1rw1r_32x512_8\n")
    staged = P._staged_macro_cell_names(tmp_path)
    assert "fakeram45_1024x32" in staged        # from the file stem
    assert "many" in staged                     # the bundle file itself
    assert "dffram_1024x32" in staged           # from a MACRO header
    assert "sky130_sram_2kbyte_1rw1r_32x512_8" in staged


def test_staged_lookup_is_fail_safe(tmp_path):
    """No project, no `input/pdk_local/`, or a nonsense argument => empty set,
    never an exception. An empty set makes the clause inert, which is exactly
    how every design that stages nothing keeps its pre-existing behaviour."""
    assert P._staged_macro_cell_names(None) == frozenset()
    assert P._staged_macro_cell_names(tmp_path) == frozenset()
    assert P._staged_macro_cell_names(12345) == frozenset()
    assert P._staged_macro_cell_names(Path(tmp_path) / "nope") == frozenset()


def test_staged_macro_promotes_only_with_the_morpheme(tmp_path):
    """The staged set is necessary but the memory morpheme is still required,
    so a staged ANALOG hardmacro (`ldo`, `delta_sigma`) latched off nearby
    memory prose does not become a memory row."""
    _stage(tmp_path, "input/pdk_local/analog/ldo.lef", "MACRO ldo\nEND ldo\n")
    _stage(tmp_path, "input/pdk_local/analog/delta_sigma.lef", "")
    staged = P._staged_macro_cell_names(tmp_path)
    assert "ldo" in staged and "delta_sigma" in staged
    assert U({"name": "ldo"}, staged) is False
    assert U({"name": "delta_sigma"}, staged) is False


def test_generator_style_macro_name_is_useful_when_staged():
    """The exact on-disk macro plus two other generator families — each one
    promoted only once the design has staged it."""
    for nm in ("fakeram45_2048x39", "fakeram45_1024x32", "dffram_1024x32"):
        assert U({"name": nm}) is False, (
            "%s must NOT promote on name shape alone" % nm)
        assert U({"name": nm}, frozenset({nm.lower()})) is True, (
            "%s is staged as a physical macro — it must promote" % nm)


# ------------------------------------------- the abandoned lexical clause


def test_organisation_token_alone_never_promotes():
    """The `<digits>x<digits>` organisation token is GONE from the promotion
    path — including for the macro this whole change exists to recover.
    Nothing below may promote on name shape."""
    for nm in ("fakeram45_2048x39", "DIAGRAM_16x9", "HISTOGRAM_256x8",
               "diagram_ctrl_4x4", "block_diagram_16x9", "histogram_256x8",
               "chroma_intra_4x4", "member_bus_2x32", "param_matrix_4x4",
               "systolic_array_16x16_param", "crossbar_8x8_parametric",
               "pin_grid_array_20x20_diagram", "diagram2_16x9",
               "histogram8_256x8", "program0_4x4", "telegram 4 x 8",
               "v1x2_diagram"):
        assert U({"name": nm}) is False, (
            "%s promoted with no staged artefact — a <digits>x<digits> group "
            "is evidence of two numbers, not of a memory" % nm)


def test_hex_literal_never_reaches_the_promotion_path():
    """`0x12` / `0X7F` / `0x0` all matched the abandoned organisation regex,
    and `0x` is common in the L4 command-protocol and L5 register-map
    documents this walker consumes. None of these names may promote."""
    for nm in ("CMD_PARAM_ERR_0x1F", "PROGRAM_0x40",
               "FP_PDN_HOFFSET_PARAM_0x10", "WITH_CSR_PARAM_0x1",
               "invalid_hci_command_parameters_0x12",
               "memory_capacity_exceeded_0x07",
               "qos_unacceptable_parameter_0x2c",
               "unsupported_feature_or_parameter_value_0x11_370"):
        assert U({"name": nm}) is False, "%s is a hex error code" % nm


def test_staged_artifact_is_the_only_lever():
    """THE RESIDUAL, asserted as the code's ACTUAL behaviour.

    The surviving conjunct is the memory morpheme, and `DIAGRAM` contains
    `ram`. So a design that stages `DIAGRAM_16x9.lef` under its own
    `input/pdk_local/` WILL promote `DIAGRAM_16x9` — it shipped a physical
    macro under that cell name. This test pins that behaviour; if the rule is
    tightened further, change this test with it."""
    assert U({"name": "DIAGRAM_16x9"}) is False
    assert U({"name": "DIAGRAM_16x9"}, frozenset({"diagram_16x9"})) is True
    # ...and the artefact must name THAT cell, not a neighbour of it.
    assert U({"name": "DIAGRAM_16x9"},
             frozenset({"fakeram45_2048x39"})) is False


# -------------------------------------------------------------- unit level


def test_boundary_visible_token_still_promotes_without_dimensions():
    """The original #612 clause is untouched: a left-boundary token alone is
    still sufficient — no staged artefact and no organisation token needed."""
    assert U({"name": "sram45_2048x39"}) is True
    assert U({"name": "data_ram"}) is True
    assert U({"name": "sky130_sram_1kbyte_1rw1r_32x256_8"}) is True


def test_issue612_token_regex_is_byte_untouched():
    """`_MEMORY_NAME_TOKEN_RE`'s strict LEFT WORD BOUNDARY is the whole of the
    #612 protection. Pin its bytes."""
    assert _MEMORY_NAME_TOKEN_PATTERN == (
        r"(?:^|[^A-Za-z])(ram|rom|sram|dram|cache|regfile|fifo|mem)"
        r"(?:[^A-Za-z]|[0-9]|$)")


def test_issue612_negatives_stay_rejected_bare_and_suffixed():
    """MANDATORY IN BOTH FORMS.
    `test_v1_0_5_issue612_memory_walker_nonmemory_tokens.py` pins only the
    BARE names. Pin the suffixed forms here too, so appending a dimension or
    hex suffix cannot silently re-admit one."""
    bare = ("i_rst", "RESET_PC", "WITH_CSR", "FP_CORE_UTIL",
            "PL_TARGET_DENSITY", "FP_PDN_HOFFSET", "GF180MCU",
            "Cyclone10LP", "sky130_fd_sc_hd", "i_gpio", "o_gpio",
            "PROGRAM", "DIAGRAM", "HISTOGRAM", "diagram_ctrl")
    for nm in bare:
        assert U({"name": nm}) is False, "#612 negative %s regressed" % nm
    for nm in bare:
        for suffix in ("_0x40", "_16x9", "_256x8", "_4x4", "_2x2", "_0x1",
                       "_PARAM_0x10", " 1 x 8", "_1024x32", "2_16x9"):
            sfx = nm + suffix
            assert U({"name": sfx}) is False, (
                "#612 negative %s regressed once suffixed: %s" % (nm, sfx))


def test_issue612_positives_stay_promoted():
    for nm in ("u_sram", "data_ram", "inst_fifo", "l1_cache", "sram0",
               "boot_rom", "regfile_bank", "scratch_mem"):
        assert U({"name": nm}) is True, "#612 positive %s regressed" % nm


def test_non_dict_and_empty_unchanged():
    assert U(None) is False
    assert U({}) is False
    assert U({"name": None}) is False
    assert U({"name": None}, frozenset({"fakeram45_2048x39"})) is False
    assert U({"name": "fakeram45_2048x39"}, frozenset()) is False


# =====================================================================
# STAGING BY SYMLINK
#
# The lever is the design's own staged artefact, so the scan that looks
# for the artefact must see it however the design put it there. The scan
# used to skip EVERY symlink — file symlinks included, which cannot create
# a traversal loop and were not what the guard was for.
#
# Each shape below is pinned separately because each is a distinct decision:
# follow / do not follow, and what "follow" means for a target outside the
# project, for a dangling link, and for a link that closes a loop.
# =====================================================================


def _real_staged_macro_dir():
    """The REAL `input/pdk_local/fakeram45/` of the benchmark design, or
    None. These tests stage the actual LEF / Liberty / behavioural model, not
    a synthetic stand-in."""
    real = _real_docs()
    if real is None:
        return None
    d = real[1] / "input" / "pdk_local" / "fakeram45"
    return d if d.is_dir() else None


def _stage_shape(tmp_path, shape):
    """Build `<tmp>/proj` whose `input/pdk_local/` stages the REAL macro files
    in `shape`, and return the project root.

    Every symlink TARGET is placed at `<tmp>/extern/`, i.e. OUTSIDE the
    project — that is what staging a shared PDK actually looks like, and it
    makes "does the scan follow a link that leaves the project?" part of every
    symlink shape below rather than a separate hypothetical."""
    src = _real_staged_macro_dir()
    assert src is not None
    base = Path(tmp_path)
    proj = base / "proj"
    stage = proj / "input" / "pdk_local"
    extern = base / "extern" / "fakeram45"
    shutil.copytree(src, extern)
    assert extern.resolve() not in proj.resolve().parents
    assert not str(extern.resolve()).startswith(str(proj.resolve()))

    if shape == "copied":
        stage.mkdir(parents=True)
        shutil.copytree(src, stage / "fakeram45")
    elif shape == "file-symlink":
        (stage / "fakeram45").mkdir(parents=True)
        for f in sorted(extern.iterdir()):
            os.symlink(f, stage / "fakeram45" / f.name)
    elif shape == "dir-symlink":
        stage.mkdir(parents=True)
        os.symlink(extern, stage / "fakeram45")
    elif shape == "nested-dir-symlink":
        (stage / "vendor").mkdir(parents=True)
        os.symlink(extern, stage / "vendor" / "fakeram45")
    elif shape == "root-symlink":
        stage.parent.mkdir(parents=True)
        os.symlink(extern.parent, stage)
    else:  # pragma: no cover - guard against a typo in a parametrisation
        raise AssertionError("unknown staging shape %r" % shape)
    return proj


@pytest.mark.parametrize("shape", ["copied", "file-symlink", "dir-symlink",
                                   "nested-dir-symlink", "root-symlink"])
def test_symlinked_staging_reaches_memories_end_to_end(tmp_path, shape):
    """THE LOAD-BEARING SYMLINK TEST. Real documents, real macro files, five
    staging shapes — the promotion must not depend on which one the operator
    chose."""
    if _real_staged_macro_dir() is None:
        pytest.skip(f"ic/edge_llm_accel: {skip_reason()}")
    proj = _stage_shape(tmp_path, shape)
    staged = P._staged_macro_cell_names(proj)
    assert "fakeram45_2048x39" in staged, (
        "staged as %s: the design's own LEF/Liberty/.v are reachable under "
        "input/pdk_local/, so the cell name must be in the staged set; got %r"
        % (shape, sorted(staged)))

    _docs, _design, extracted = _real_docs()
    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, extracted, proj)
    names = [e.get("name") for e in (l9.get("memories") or [])]
    assert "fakeram45_2048x39" in names, (
        "staged as %s: macro must reach L9.memories[], got memories=%r"
        % (shape, l9.get("memories")))


def test_symlinked_staging_agrees_with_the_other_readers_of_this_directory(
        tmp_path):
    """THREE PROGRAMS, ONE DIRECTORY, ONE ANSWER.

    `phase3_one_shot_runner._discover_local_macros` and
    `hardmacro_supply_intent` also read `<project>/input/pdk_local/`. This test
    asserts what all three see on the FILE-symlink shape, on one fixture.
    `test_this_walker_is_a_superset_of_its_two_siblings` measures the other
    shapes, including the ones where the two siblings disagree with each
    other."""
    if _real_staged_macro_dir() is None:
        pytest.skip(f"ic/edge_llm_accel: {skip_reason()}")
    p3 = pytest.importorskip("phase3_one_shot_runner")
    proj = _stage_shape(tmp_path, "file-symlink")

    libs, lefs, _gds, vs = p3._discover_local_macros(proj)
    hsi_lefs = sorted((proj / "input" / "pdk_local").rglob("*.lef"))
    staged = P._staged_macro_cell_names(proj)

    assert libs and lefs and vs, (
        "fixture is wrong: phase3 must see the symlinked macro files")
    assert hsi_lefs, "fixture is wrong: rglob must see the symlinked LEF"
    assert "fakeram45_2048x39" in staged, (
        "phase3 sees libs=%d lefs=%d v=%d and rglob sees %d LEF(s) through "
        "these file symlinks; this walker must not answer 'nothing staged' "
        "about the same directory" % (len(libs), len(lefs), len(vs),
                                      len(hsi_lefs)))


def test_broken_symlink_is_not_evidence_of_staging(tmp_path):
    """A DANGLING link names a cell that is not there. `is_dir()` and
    `is_file()` are both False for it, so it is skipped — no exception, and no
    promotion off a stem with nothing behind it. The real sibling file in the
    same directory is still found, so this is a skip, not an abort."""
    _stage(tmp_path, "input/pdk_local/vendor/real_ram_1024x32.lef",
           "MACRO real_ram_1024x32\nEND real_ram_1024x32\n")
    os.symlink(Path(tmp_path) / "nowhere" / "ghostram_512x8.lef",
               Path(tmp_path) / "input" / "pdk_local" / "vendor"
               / "ghostram_512x8.lef")
    staged = P._staged_macro_cell_names(tmp_path)
    assert "ghostram_512x8" not in staged, (
        "a dangling symlink is not a staged artefact")
    assert "real_ram_1024x32" in staged, (
        "the dangling link must not abort the scan of its own directory")
    assert U({"name": "ghostram_512x8"}, staged) is False


def test_directory_symlink_loop_terminates_and_still_finds_the_macro(
        tmp_path):
    """FOLLOWING DIRECTORY SYMLINKS MEANS OWNING THE LOOP.

    Three loop shapes at once: a link onto the scan root, a link onto the
    directory that contains it, and a link onto its own parent. Every
    directory is keyed on the `(st_dev, st_ino)` of its FOLLOWED target, so
    each is walked at most once. The assertion is simply that this call
    returns — and returns the right answer."""
    _stage(tmp_path, "input/pdk_local/fakeram45/fakeram45_2048x39.lef",
           "MACRO fakeram45_2048x39\nEND fakeram45_2048x39\n")
    root = Path(tmp_path) / "input" / "pdk_local"
    os.symlink(root, root / "fakeram45" / "back_to_root")
    os.symlink(root / "fakeram45", root / "fakeram45" / "self")
    os.symlink(root / "fakeram45" / "..", root / "up")
    staged = P._staged_macro_cell_names(tmp_path)
    assert "fakeram45_2048x39" in staged
    assert U({"name": "fakeram45_2048x39"}, staged) is True


# =====================================================================
# TRUNCATION IS OBSERVABLE
#
# The scan's caps are fail-SAFE in direction — they can only lose a
# promotion, never invent one — but a lost promotion nobody can see is the
# same defect with a cap on it. Two things are pinned here: that a large
# sibling directory can no longer starve the real macro out of the budget,
# and that whatever the caps DO cut is reported where somebody reads it.
# =====================================================================


def _scan(project):
    """`(names, truncation_events)`. Fails with a readable assertion rather
    than an AttributeError when the scan cannot report truncation at all."""
    fn = getattr(P, "_staged_macro_scan", None)
    assert fn is not None, (
        "the staged-macro scan has no truncation channel: its caps can drop a "
        "real macro and nothing in the output says so")
    return fn(project)


def _big_sibling(tmp_path, n_entries):
    """A sibling directory that sorts BEFORE the macro's directory and holds
    more entries than the whole scan budget."""
    d = Path(tmp_path) / "input" / "pdk_local" / "aaa_stdcells"
    d.mkdir(parents=True)
    for i in range(n_entries):
        (d / ("cell_%05d.lef" % i)).write_text("", encoding="utf-8")
    _stage(tmp_path, "input/pdk_local/fakeram45/fakeram45_2048x39.lef",
           "MACRO fakeram45_2048x39\nEND fakeram45_2048x39\n")


def test_large_sibling_directory_cannot_starve_the_real_macro(tmp_path):
    """WHICH DIRECTORY GETS SCANNED MUST NOT BE DECIDED BY ITS NAME.

    A plain breadth-first walk drains the first directory completely, so
    `aaa_stdcells/` with more entries than the budget spends all of it before
    `fakeram45/` is ever listed, and the promotion disappears — silently, and
    only for designs whose standard-cell directory happens to sort first.
    Each directory now yields a bounded slice before the scan moves on."""
    _big_sibling(tmp_path, P._MEMORY_MACRO_MAX_FILES + 100)
    # Read through the plain name lookup, which exists both before and after
    # this change, so a regression fails on the STARVATION and not on a
    # missing helper.
    names = P._staged_macro_cell_names(tmp_path)
    assert "fakeram45_2048x39" in names, (
        "a sibling directory that sorts first spent the whole scan budget and "
        "pushed the real macro out; got %d name(s), none of them the macro"
        % len(names))
    assert U({"name": "fakeram45_2048x39"}, names) is True
    reasons = {e.get("reason") for e in _scan(tmp_path)[1]}
    assert "entry_budget_exhausted" in reasons, reasons
    assert "directory_listing_capped" in reasons, reasons


def test_exhausted_budget_is_reported_in_l9_and_on_the_affected_rows(
        tmp_path, capsys):
    """WHERE THE TRUNCATION IS READ — ON A FIXTURE THAT REALLY LOSES THE
    MACRO.

    Fair sharing rescues one big sibling, not an unbounded number of them.
    Here the design stages `_MEMORY_MACRO_DIR_SLICE + 1` vendor directories of
    `_MEMORY_MACRO_DIR_SLICE` entries each — together more than the whole
    budget — plus its real macro under a directory that sorts LAST. The budget
    is gone before that directory is ever queued, so the macro genuinely does
    not reach `memories[]`.

    That is the case that must not look like "this design has no memory
    macro". Three readers say otherwise, all of them places somebody already
    looks: a `[WARN]` on stderr while the run happens,
    `L9.staged_macro_scan_truncated` in the document this emitter owns, and a
    note on the very `memory_candidates[]` row that would have been
    promoted."""
    real = _real_docs()
    if real is None:
        pytest.skip(f"ic/edge_llm_accel/input/docs: {skip_reason()}")
    if not _ACCEPTS_PROJECT:
        pytest.skip("emitter predates the staged-artefact clause")
    stage = Path(tmp_path) / "input" / "pdk_local"
    slice_n = P._MEMORY_MACRO_DIR_SLICE
    for v in range(slice_n + 1):
        d = stage / ("vendor_%03d" % v)
        d.mkdir(parents=True)
        for i in range(slice_n):
            (d / ("cell_%05d.lef" % i)).write_text("", encoding="utf-8")
    _stage(tmp_path, "input/pdk_local/zzz_macros/fakeram45_2048x39.lef",
           "MACRO fakeram45_2048x39\nEND fakeram45_2048x39\n")
    assert (slice_n + 1) * slice_n > P._MEMORY_MACRO_MAX_FILES, (
        "fixture must exceed the scan budget")

    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, real[2], tmp_path)

    promoted = {e.get("name") for e in (l9.get("memories") or [])}
    assert "fakeram45_2048x39" not in promoted, (
        "fixture is wrong: the budget must run out before zzz_macros/ is "
        "reached, otherwise this test is not about a lost promotion")

    report = l9.get("staged_macro_scan_truncated")
    assert isinstance(report, dict), (
        "the scan hit its cap and L9 says nothing about it: an empty "
        "memories[] then reads as a fact about the design")
    assert report.get("root") == "input/pdk_local"
    reasons = {e.get("reason") for e in report.get("events") or []}
    assert "entry_budget_exhausted" in reasons, reasons

    rows = [e for e in (l9.get("memory_candidates") or [])
            if e.get("name") == "fakeram45_2048x39"]
    assert rows, "the row must still be preserved as a candidate"
    assert rows[0].get("staged_macro_scan") == "truncated:input/pdk_local", (
        "the row that failed ONLY the staged-set test must say the staged-set "
        "scan did not finish")
    assert report.get("candidate_rows_affected") >= 1

    err = capsys.readouterr().err
    assert "staged-macro scan under input/pdk_local was truncated" in err, err


def test_oversized_lef_body_is_reported_and_the_stem_still_counts(tmp_path):
    """The per-LEF byte cap does NOT drop the file, only the extra cells its
    `MACRO` headers would have named. Both halves are pinned: the stem is
    still staged evidence, and the unread body is reported."""
    d = Path(tmp_path) / "input" / "pdk_local" / "vendor"
    d.mkdir(parents=True)
    big = d / "hugeram_1024x32.lef"
    with open(big, "wb") as fh:                     # sparse: no 8 MB written
        fh.truncate(P._MEMORY_MACRO_MAX_LEF_BYTES + 1)
    assert big.stat().st_size > P._MEMORY_MACRO_MAX_LEF_BYTES
    names, cut = _scan(tmp_path)
    assert "hugeram_1024x32" in names, (
        "the file stem is evidence on its own; only the MACRO headers are lost")
    assert {e.get("reason") for e in cut} == {"lef_macro_headers_not_read"}
    assert cut[0].get("bytes") > P._MEMORY_MACRO_MAX_LEF_BYTES


def test_the_truncation_report_says_when_it_is_itself_truncated(tmp_path):
    """The report is bounded too — a pathological tree must not turn the
    anomaly channel INTO the anomaly. When the bound bites it says so, with
    the real total, instead of quietly dropping the tail."""
    d = Path(tmp_path) / "input" / "pdk_local" / "vendor"
    d.mkdir(parents=True)
    n = P._MEMORY_MACRO_MAX_TRUNCATION_EVENTS + 3
    for i in range(n):
        with open(d / ("bigram_%02d.lef" % i), "wb") as fh:
            fh.truncate(P._MEMORY_MACRO_MAX_LEF_BYTES + 1)
    _names, cut = _scan(tmp_path)
    assert len(cut) == P._MEMORY_MACRO_MAX_TRUNCATION_EVENTS + 1, len(cut)
    tail = cut[-1]
    assert tail.get("reason") == "truncation_report_capped"
    assert tail.get("events_total") == n, tail


def test_an_unreadable_directory_is_reported_like_a_cap(tmp_path):
    """Not a cap, same consequence: evidence the scan was supposed to read and
    did not. It must not look like a complete scan that found nothing."""
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not deny reads")
    d = Path(tmp_path) / "input" / "pdk_local" / "locked"
    d.mkdir(parents=True)
    (d / "secretram_8x8.lef").write_text("", encoding="utf-8")
    _stage(tmp_path, "input/pdk_local/open/openram_16x16.lef", "")
    os.chmod(d, 0o000)
    try:
        names, cut = _scan(tmp_path)
    finally:
        os.chmod(d, 0o755)
    assert "openram_16x16" in names, "the readable sibling must still be read"
    assert "secretram_8x8" not in names
    assert {e.get("reason") for e in cut} == {"directory_unreadable"}, cut


def test_a_complete_scan_reports_nothing_and_changes_no_l9_key(tmp_path):
    """The report exists only when there is something to report: a scan that
    read everything it reached adds no `staged_macro_scan_truncated` key and
    stamps no row, so the truncation channel does not become noise on a design
    that lost nothing."""
    if _real_staged_macro_dir() is None:
        pytest.skip(f"ic/edge_llm_accel: {skip_reason()}")
    _docs, design, extracted = _real_docs()
    assert _scan(design)[1] == [], (
        "the real design scans completely; nothing to report")
    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, extracted, design)
    assert "staged_macro_scan_truncated" not in l9
    for e in (l9.get("memory_candidates") or []) + (l9.get("memories") or []):
        assert "staged_macro_scan" not in e

    proj = _stage_shape(tmp_path, "copied")
    assert _scan(proj)[1] == []
    assert _scan(None) == (frozenset(), [])
    assert _scan(Path(tmp_path) / "nope") == (frozenset(), [])


# =====================================================================
# THE SHAPE THAT WAS DROPPED IN SILENCE
#
# "Symlink a shared PDK into place out of a directory this process may not
# search": `Path.is_dir()` stats the TARGET and RAISES on EACCES rather than
# returning False, and the entry loop's catch-all dropped the entry with no
# event, no L9 key and no stderr WARN — indistinguishable from a design that
# stages nothing. Fail-safe in direction (a promotion is lost, not invented),
# but silent.
#
# Each test below drives one reason code from the enumeration inside
# `_staged_macro_scan`, and one of them checks that enumeration against the
# source so a handler that NAMES OSError cannot be added without a reason
# code. Its scope is stated in its own docstring — it is a guard, not a proof.
# =====================================================================


def _unsearchable_vault(tmp_path, name="vault"):
    """A directory holding staged artefacts whose PARENT denies search — the
    design symlinks one macro family out of a vendor tree this process may not
    traverse. What is asserted about it here is only what these tests
    construct; no claim is made about how any particular site sets its
    permissions."""
    vault = Path(tmp_path) / name
    vault.mkdir(parents=True, exist_ok=True)
    return vault


@pytest.mark.parametrize("link", ["dir", "file"])
def test_symlink_into_an_unsearchable_directory_is_reported(tmp_path, link):
    """THE SILENT SHAPE, both link forms.

    `input/pdk_local/fakeram45 -> <vault>/fakeram45` (and the per-file
    variant) where `<vault>` is mode 0000. `is_dir()` raises EACCES on the
    followed target, and that must produce an `entry_unreadable` event rather
    than an empty set with an empty event list. The readable sibling in the
    same directory must still be scanned: this is a skip that is REPORTED, not
    an abort."""
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not deny reads")
    stage = Path(tmp_path) / "input" / "pdk_local"
    stage.mkdir(parents=True)
    (stage / "sibling_ram_8x8.lef").write_text(
        "MACRO sibling_ram_8x8\nEND sibling_ram_8x8\n", encoding="utf-8")
    vault = _unsearchable_vault(tmp_path)
    if link == "dir":
        (vault / "fakeram45").mkdir()
        (vault / "fakeram45" / "fakeram45_2048x39.lef").write_text(
            "MACRO fakeram45_2048x39\nEND fakeram45_2048x39\n",
            encoding="utf-8")
        os.symlink(vault / "fakeram45", stage / "fakeram45")
    else:
        (vault / "fakeram45_2048x39.lef").write_text(
            "MACRO fakeram45_2048x39\nEND fakeram45_2048x39\n",
            encoding="utf-8")
        os.symlink(vault / "fakeram45_2048x39.lef",
                   stage / "fakeram45_2048x39.lef")
    os.chmod(vault, 0o000)
    try:
        names, cut = _scan(tmp_path)
    finally:
        os.chmod(vault, 0o755)

    assert "fakeram45_2048x39" not in names, (
        "fixture is wrong: the vault must really deny the read")
    assert "sibling_ram_8x8" in names, (
        "the unreadable entry must be a skip, not an abort of its directory")
    assert {e.get("reason") for e in cut} == {"entry_unreadable"}, (
        "a staged macro the scan could not even classify was dropped in "
        "SILENCE — an empty memories[] then reads as a fact about the "
        "design; got %r" % (cut,))
    assert cut[0].get("error") == "PermissionError", cut
    assert cut[0].get("path") in ("fakeram45", "fakeram45_2048x39.lef"), cut


def test_on_the_unsearchable_shape_the_siblings_do_not_report_either(
        tmp_path):
    """WHAT THE OTHER TWO READERS DO ON THE SAME SHAPE, measured rather than
    assumed.

    They do not agree with each other: `_discover_local_macros` RAISES
    PermissionError out of its own `is_dir()`, and `rglob("*.lef")` returns
    empty. Neither reports a shortfall, which is the point of the event this
    walker emits."""
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not deny reads")
    p3 = pytest.importorskip("phase3_one_shot_runner")
    proj = Path(tmp_path) / "proj"
    stage = proj / "input" / "pdk_local"
    stage.mkdir(parents=True)
    vault = _unsearchable_vault(tmp_path)
    (vault / "fakeram45").mkdir()
    (vault / "fakeram45" / "fakeram45_2048x39.lef").write_text(
        "MACRO fakeram45_2048x39\nEND fakeram45_2048x39\n", encoding="utf-8")
    os.symlink(vault / "fakeram45", stage / "fakeram45")
    os.chmod(vault, 0o000)
    try:
        with pytest.raises(PermissionError):
            p3._discover_local_macros(proj)
        assert sorted(stage.rglob("*.lef")) == []
        names, cut = _scan(proj)
    finally:
        os.chmod(vault, 0o755)
    assert names == frozenset()
    assert {e.get("reason") for e in cut} == {"entry_unreadable"}, (
        "this walker is the only one of the three that says anything here; "
        "that is the whole point of the event")


def test_symlink_into_an_unsearchable_directory_reaches_l9_and_stderr(
        tmp_path, capsys):
    """END-TO-END on the REAL documents: the same shape must get the same
    three readers the unreadable-DIRECTORY case gets — the L9 key, the stderr
    WARN, and the note on the very candidate row that would have been
    promoted."""
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not deny reads")
    if _real_staged_macro_dir() is None:
        pytest.skip(f"ic/edge_llm_accel: {skip_reason()}")
    if not _ACCEPTS_PROJECT:
        pytest.skip("emitter predates the staged-artefact clause")
    _docs, _design, extracted = _real_docs()
    proj = Path(tmp_path) / "proj"
    stage = proj / "input" / "pdk_local"
    stage.mkdir(parents=True)
    vault = _unsearchable_vault(tmp_path)
    shutil.copytree(_real_staged_macro_dir(), vault / "fakeram45")
    os.symlink(vault / "fakeram45", stage / "fakeram45")
    os.chmod(vault, 0o000)
    try:
        l9 = {"top_module": "edge_llm_accel"}
        _emit(l9, extracted, proj)
    finally:
        os.chmod(vault, 0o755)

    assert "fakeram45_2048x39" not in {
        e.get("name") for e in (l9.get("memories") or [])}, (
        "fixture is wrong: the macro must be unreachable here")
    report = l9.get("staged_macro_scan_truncated")
    assert isinstance(report, dict), (
        "the scan could not read the staged macro and L9 says nothing: the "
        "empty memories[] reads as 'this design has no SRAM macro'")
    assert "entry_unreadable" in {
        e.get("reason") for e in report.get("events") or []}, report
    rows = [e for e in (l9.get("memory_candidates") or [])
            if e.get("name") == "fakeram45_2048x39"]
    assert rows and rows[0].get("staged_macro_scan") == (
        "truncated:input/pdk_local"), rows
    assert report.get("candidate_rows_affected") >= 1
    assert "staged-macro scan under input/pdk_local was truncated" in (
        capsys.readouterr().err)


def test_many_unreadable_entries_cannot_turn_the_report_into_the_anomaly(
        tmp_path):
    """The `entry_unreadable` event fires PER ENTRY, so a directory full of
    links into a locked vault could make the anomaly channel the anomaly —
    the failure `_MEMORY_MACRO_MAX_TRUNCATION_EVENTS` exists to prevent,
    reached through this code path. Bounded at the cap plus the marker."""
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not deny reads")
    stage = Path(tmp_path) / "input" / "pdk_local"
    stage.mkdir(parents=True)
    vault = _unsearchable_vault(tmp_path)
    (vault / "t").mkdir()
    n = P._MEMORY_MACRO_MAX_TRUNCATION_EVENTS * 8
    for i in range(n):
        os.symlink(vault / "t", stage / ("m_%05d" % i))
    os.chmod(vault, 0o000)
    try:
        names, cut = _scan(tmp_path)
    finally:
        os.chmod(vault, 0o755)
    assert names == frozenset()
    assert len(cut) == P._MEMORY_MACRO_MAX_TRUNCATION_EVENTS + 1, len(cut)
    assert {e.get("reason") for e in cut[:-1]} == {"entry_unreadable"}, cut[0]
    assert cut[-1].get("reason") == "truncation_report_capped"
    assert cut[-1].get("events_total") == n, cut[-1]
    # ...and no reported path names the vault outside the project.
    for e in cut:
        p = str(e.get("path", ""))
        assert not p.startswith("/") and ".." not in p, e


def test_staged_root_symlinked_into_an_unsearchable_directory_is_reported(
        tmp_path):
    """The same EACCES, one level up: `input/pdk_local` ITSELF is the symlink.

    `root.is_dir()` raises before the walk starts. Returning
    `(frozenset(), [])` there — which is what the code did — makes "the PDK
    directory is locked" identical to "this design stages nothing", and the
    latter is the fail-safe default the whole clause rests on."""
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not deny reads")
    proj = Path(tmp_path) / "proj"
    (proj / "input").mkdir(parents=True)
    vault = _unsearchable_vault(tmp_path)
    (vault / "pdk_local").mkdir()
    (vault / "pdk_local" / "fakeram45_2048x39.lef").write_text(
        "MACRO fakeram45_2048x39\nEND fakeram45_2048x39\n", encoding="utf-8")
    os.symlink(vault / "pdk_local", proj / "input" / "pdk_local")
    os.chmod(vault, 0o000)
    try:
        names, cut = _scan(proj)
    finally:
        os.chmod(vault, 0o755)
    assert names == frozenset()
    assert {e.get("reason") for e in cut} == {"staged_root_unreadable"}, cut
    assert cut[0].get("path") == "input/pdk_local", cut

    # ...and the two shapes that legitimately mean "nothing staged" must NOT
    # grow an event, or the channel becomes noise on every design.
    assert _scan(Path(tmp_path) / "no_such_project") == (frozenset(), [])
    empty = Path(tmp_path) / "empty_project"
    empty.mkdir()
    assert _scan(empty) == (frozenset(), [])


def test_an_unreadable_lef_body_loses_the_cells_it_abstracts_and_says_so(
        tmp_path):
    """A bundle LEF whose own mode denies read.

    It stats fine, so `is_file()` is True and the STEM is staged evidence —
    but every OTHER cell the bundle abstracts is lost, which is the same loss
    the byte cap reports as `lef_macro_headers_not_read`. It was silent."""
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not deny reads")
    d = Path(tmp_path) / "input" / "pdk_local" / "vendor"
    d.mkdir(parents=True)
    bundle = d / "bundle.lef"
    bundle.write_text("MACRO hiddenram_1024x32\nEND hiddenram_1024x32\n",
                      encoding="utf-8")
    os.chmod(bundle, 0o000)
    try:
        names, cut = _scan(tmp_path)
    finally:
        os.chmod(bundle, 0o644)
    assert "bundle" in names, "the stem is still evidence"
    assert "hiddenram_1024x32" not in names, (
        "fixture is wrong: the body must really be unreadable")
    assert {e.get("reason") for e in cut} == {"lef_body_unreadable"}, cut
    assert cut[0].get("error") == "PermissionError", cut


def test_every_oserror_handler_in_the_scan_reports_or_is_listed_here():
    """THE GUARD ON THE ENUMERATION.

    A prose promise that "every loss is reported" cannot hold itself up; check
    it against the source instead.

    Every handler inside `_staged_macro_scan` (its nested `_rel` / `_note` /
    `_enqueue` included) that names `OSError` must either call `_note(...)` or
    return a value carrying a `"reason"`. Adding a bare
    `except OSError: continue` fails HERE, at the handler, instead of being
    found later by someone building the input.

    SCOPE, stated so nobody reads more into a green result: this checks
    handlers that NAME OSError, in this one function. A handler spelled
    `except Exception:` would not be seen, and `_capped_dir_listing` is a
    module-level helper outside this source (it has no handler — it
    propagates, which is why the caller has one)."""
    import ast
    import textwrap
    src = textwrap.dedent(inspect.getsource(P._staged_macro_scan))
    tree = ast.parse(src)

    def _names(node):
        if node is None:
            return set()
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, ast.Tuple):
            out = set()
            for e in node.elts:
                out |= _names(e)
            return out
        return set()

    handlers = [h for h in ast.walk(tree)
                if isinstance(h, ast.ExceptHandler)
                and "OSError" in _names(h.type)]
    assert len(handlers) >= 6, (
        "expected the scan's OSError handlers to still be here; found %d"
        % len(handlers))
    unreported = []
    for h in handlers:
        body = ast.dump(ast.Module(body=h.body, type_ignores=[]))
        if "'_note'" in body or '"reason"' in body or "'reason'" in body:
            continue
        unreported.append(h.lineno)
    assert not unreported, (
        "OSError handler(s) at line offset(s) %r inside _staged_macro_scan "
        "abandon an entry without emitting a reason code — that is exactly "
        "the shape of the EACCES hole this round closed" % (unreported,))


def test_artefact_suffixes_are_ordered_so_no_suffix_masks_a_longer_one():
    """WHETHER FIRST-MATCH ORDER DECIDES ANY STEM, RE-DERIVED FROM THE TUPLE.

    `".sv".endswith(".v")` is False — the leading dot breaks it — and no pair
    in the tuple currently overlaps, so reversing it changes no stem here.

    That is a property of the CONTENTS, not a law: adding `.gz` or `.lib.gz`
    would make order load-bearing, and the failure mode is a silently
    truncated stem, which corroborates nothing and reads as "the design did
    not stage that cell"."""
    sfx = P._MEMORY_MACRO_ARTEFACT_SUFFIXES
    assert ".sv".endswith(".v") is False, (
        "the premise of the old comment; if this ever becomes True, Python "
        "changed under us")
    overlaps = {(a, b) for a in sfx for b in sfx
                if a != b and b.endswith(a)}
    assert overlaps == set(), (
        "%r now overlap, so first-match ORDER decides their stems: put the "
        "longer suffix first and pin it here" % (sorted(overlaps),))

    def _stem(fname, order):
        low = fname.lower()
        for s in order:
            if low.endswith(s) and len(low) > len(s):
                return fname[: len(fname) - len(s)]
        return ""

    probes = ["cell.sv", "cell.v", "chip.gds.gz", "chip.gdsii", "chip.gds",
              "m.lef", "m.lib", "m.db", "cell.s.v", "x.SV", "x.GDS.GZ"]
    for p in probes:
        assert _stem(p, sfx) == _stem(p, tuple(reversed(sfx))), (
            "%s's stem depends on the tuple order" % p)
    # `.gz` is not a member, so `.gds.gz` earns its entry by coverage rather
    # than by ordering.
    assert _stem("chip.gds.gz", sfx) == "chip"
    assert _stem("chip.gds.gz",
                 tuple(s for s in sfx if s != ".gds.gz")) == "", (
        "drop the .gds.gz entry and a gzipped GDS names no cell at all")


# =====================================================================
# THIS WALKER AGAINST ITS SIBLINGS, PER STAGING SHAPE
#
# `_SIBLING_MATRIX` is the measurement, re-checked on every run: what the
# two other readers of `input/pdk_local/` see for each staging shape, and
# what this walker sees. The source comments point here rather than
# restating it.
# =====================================================================


_SIBLING_MATRIX = {
    # shape             -> (phase3 sees it, hardmacro rglob sees it)
    "copied":              (True,  True),
    "file-symlink":        (True,  True),
    "dir-symlink":         (True,  False),
    "nested-dir-symlink":  (False, False),
    "root-symlink":        (True,  True),
}


@pytest.mark.parametrize("shape", sorted(_SIBLING_MATRIX))
def test_this_walker_is_a_superset_of_its_two_siblings(tmp_path, shape):
    """MEASURED, per staging shape, against both pre-existing readers of
    `input/pdk_local/`.

    The two siblings DISAGREE with each other on `dir-symlink` (phase3's
    top-level `iterdir()` + `is_dir()` follows one; `rglob` does not descend
    into one), so "match the siblings" is not a well-defined target. On
    `nested-dir-symlink` both are blind and this walker still finds the cell.
    The assertion below is that this walker sees no less than a sibling, on
    each shape in the table."""
    if _real_staged_macro_dir() is None:
        pytest.skip(f"ic/edge_llm_accel: {skip_reason()}")
    p3 = pytest.importorskip("phase3_one_shot_runner")
    proj = _stage_shape(tmp_path, shape)
    pl = proj / "input" / "pdk_local"

    libs, lefs, _gds, vs = p3._discover_local_macros(proj)
    p3_sees = bool(libs and lefs and vs)
    rglob_sees = bool(sorted(pl.rglob("*.lef")) if pl.is_dir() else [])
    ours = "fakeram45_2048x39" in P._staged_macro_cell_names(proj)

    expected_p3, expected_rglob = _SIBLING_MATRIX[shape]
    assert (p3_sees, rglob_sees) == (expected_p3, expected_rglob), (
        "the sibling behaviour this walker is compared against MOVED for "
        "shape %s: phase3=%s rglob=%s, table says %s/%s — re-measure the "
        "table in the block comment on _staged_macro_scan before touching "
        "anything else" % (shape, p3_sees, rglob_sees, expected_p3,
                           expected_rglob))
    assert ours, (
        "shape %s: this walker must never see LESS than a sibling" % shape)
    if not (expected_p3 and expected_rglob):
        assert ours, "superset claim"


# =====================================================================
# CLAIMS THE COMMENTS MAKE ABOUT THEMSELVES
#
# These tests exist so the remaining prose is CHECKED rather than
# remembered: each one re-derives a statement the source makes about its own
# behaviour, and fails when the statement stops being true.
# =====================================================================


# The 27 names the abandoned lexical clause was scored against: 3 real
# generator macro families that MUST promote, and 24 negatives that must not.
# Every one of them is independently pinned elsewhere in this file, by
# `test_organisation_token_alone_never_promotes` and
# `test_hex_literal_never_reaches_the_promotion_path`.
_LEXICAL_POSITIVES = ["fakeram45_2048x39", "fakeram45_1024x32",
                      "dffram_1024x32"]
_LEXICAL_NEGATIVES = [
    "DIAGRAM_16x9", "HISTOGRAM_256x8", "diagram_ctrl_4x4",
    "block_diagram_16x9", "histogram_256x8", "chroma_intra_4x4",
    "member_bus_2x32", "param_matrix_4x4", "systolic_array_16x16_param",
    "crossbar_8x8_parametric", "pin_grid_array_20x20_diagram",
    "diagram2_16x9", "histogram8_256x8", "program0_4x4", "telegram 4 x 8",
    "v1x2_diagram",
    "CMD_PARAM_ERR_0x1F", "PROGRAM_0x40", "FP_PDN_HOFFSET_PARAM_0x10",
    "WITH_CSR_PARAM_0x1", "invalid_hci_command_parameters_0x12",
    "memory_capacity_exceeded_0x07", "qos_unacceptable_parameter_0x2c",
    "unsupported_feature_or_parameter_value_0x11_370",
]


def test_the_tightest_lexical_rule_is_still_wrong_in_both_directions():
    """WHY THE LEXICAL CLAUSE WAS ABANDONED, RE-DERIVED.

    The block comment above `_MEMORY_NAME_TOKEN_ANYWHERE_RE` says an
    organisation-token rule was tried and abandoned. Spell the tightest form
    of that rule out as a regex and score it against 27 names here, so the
    reason is a measurement and not a memory.

    If some future rule scores 0/0 on this corpus, this test fails — and the
    right response is to re-open the design question, not to edit the
    numbers."""
    import re as _re
    corpus = _LEXICAL_POSITIVES + _LEXICAL_NEGATIVES
    assert len(corpus) == 27, len(corpus)
    assert len(set(corpus)) == 27, "corpus has duplicates"
    # None of these is promoted by the pre-existing #612 clause, so all 27
    # really do fall through to the second clause under test.
    assert not [n for n in corpus if P._MEMORY_NAME_TOKEN_RE.search(n)]

    org = _re.compile(r"(?:^|_)(?!0)\d+[xX]\d+")

    def promotes(name):
        """morpheme anywhere + <digits>x<digits>, no whitespace, no
        leading-zero (hex) operand, anchored at `_`/start, morpheme
        immediately followed by a digit."""
        if not P._MEMORY_NAME_TOKEN_ANYWHERE_RE.search(name):
            return False
        if not org.search(name):
            return False
        return any(name[m.end():m.end() + 1].isdigit()
                   for m in P._MEMORY_NAME_TOKEN_ANYWHERE_RE.finditer(name))

    false_accepts = sorted(n for n in _LEXICAL_NEGATIVES if promotes(n))
    false_rejects = sorted(n for n in _LEXICAL_POSITIVES if not promotes(n))
    assert false_accepts == ["diagram2_16x9", "histogram8_256x8",
                             "program0_4x4"], false_accepts
    assert false_rejects == ["dffram_1024x32"], false_rejects

    # ...and the shipped code promotes none of them on name shape alone.
    for n in corpus:
        assert U({"name": n}) is False, n
    # ...while the staged artefact promotes every real macro family.
    for n in _LEXICAL_POSITIVES:
        assert U({"name": n}, frozenset({n.lower()})) is True, n


def test_capped_listing_is_linear_in_the_directory_not_constant(tmp_path):
    """WHAT THE GENERATOR IN `_capped_dir_listing` DOES AND DOES NOT BUY.

    Measured here, not asserted in prose: peak memory tracks the DIRECTORY
    size rather than the cap, so the cap is not a memory bound. What the
    generator buys is that only `cap` Path objects are retained — measurably
    cheaper than `sorted(directory.iterdir())`, and no cheaper than
    `os.listdir` itself at a small cap."""
    import gc
    import tracemalloc

    def peak(fn):
        gc.collect()
        tracemalloc.start()
        keep = fn()
        _cur, pk = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del keep
        return pk

    d = Path(tmp_path) / "many"
    d.mkdir()
    small, big = 2000, 16000
    for i in range(big):
        (d / ("f_%07d" % i)).touch()

    p_sorted = peak(lambda: sorted(d.iterdir()))
    p_cap = peak(lambda: P._capped_dir_listing(d, 64))
    p_listdir = peak(lambda: os.listdir(d))
    assert p_cap < p_sorted / 2, (
        "the cap-sized heap must be materially cheaper than materialising a "
        "Path per entry: cap=%d sorted=%d" % (p_cap, p_sorted))
    assert p_cap < p_listdir * 2, (
        "at cap=64 the cost IS os.listdir plus a little: cap=%d listdir=%d"
        % (p_cap, p_listdir))

    # NOT constant: shrink the directory and the peak must drop with it.
    for i in range(small, big):
        (d / ("f_%07d" % i)).unlink()
    p_cap_small = peak(lambda: P._capped_dir_listing(d, 64))
    assert p_cap_small < p_cap / 2, (
        "peak tracks the DIRECTORY size, not the cap — if this ever stops "
        "being true the O(cap) claim could be restored: %d entries=%d, "
        "%d entries=%d" % (small, p_cap_small, big, p_cap))


def test_the_borrowed_precedent_for_reporting_a_drop_really_exists():
    """The truncation-report comment justifies its shape by citing an existing
    one in this module. Check the citation, not the story: the cited name must
    resolve, and must really do both halves it is cited for."""
    src = Path(inspect.getfile(P)).read_text(encoding="utf-8")
    cited = re.findall(r"\(`([A-Za-z_][A-Za-z0-9_]*)`, v1\.6\.93", src)
    assert cited, "the precedent citation vanished; re-check this test"
    for fn in cited:
        assert hasattr(P, fn), (
            "the truncation report cites %r as its precedent and no such "
            "function exists in this module" % fn)
    # ...and the cited precedent really does both halves it is cited for.
    body = inspect.getsource(getattr(P, cited[0]))
    assert "[WARN]" in body, "cited for a stderr WARN it does not emit"
    assert '"reason"' in body, "cited for a reason-coded record it lacks"


def test_the_enumeration_of_abandonment_points_names_tests_that_exist():
    """The block comment inside `_staged_macro_scan` lists each reason code
    against the test that drives it. Check that every test it names exists in
    this file."""
    src = inspect.getsource(P._staged_macro_scan)
    # The enumeration wraps long test names across comment lines, always
    # breaking AFTER an underscore. Rejoin only those, so a wrapped name is
    # not welded to the next row's reason code.
    flat = re.sub(r"_\n\s*#\s+", "_", src)
    named = set(re.findall(r"\btest_[a-z0-9_]+", flat))
    assert len(named) >= 6, (
        "the enumeration should still name a test per abandonment point; "
        "found %r" % (sorted(named),))
    here = set(globals())
    missing = sorted(n for n in named if n not in here)
    assert not missing, (
        "_staged_macro_scan's enumeration points at test(s) that do not "
        "exist in this file: %r" % (missing,))
