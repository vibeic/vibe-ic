"""The L9 memory walker threw away a REAL SRAM hard macro.

`benchmark-data/ic/edge_llm_accel` instantiates twenty `fakeram45_2048x39`
hard macros — the LEF / Liberty / behavioural model are all on disk under
`input/pdk_local/fakeram45/` — and shipped
`phase1/generated_docs/L9_INTEGRATION_SPEC.json` with `memories: []`.

The walker RAN and FOUND the macro; the promotion gate
`_v1_6_441_is_useful_memory_entry` threw it away, because a generator-emitted
macro cell name fails BOTH of the gate's clauses:

  (a) structural — depth/width were never extracted. `_V1_6_426_RE_MEMORY_PROSE`
      captures `<depth>x<width>` only AFTER the type keyword, and the source doc
      writes ``| SRAM 巨集 | `fakeram45_2048x39` × 20 |``: the dimensions live
      INSIDE the identifier, to the LEFT of the keyword.
  (b) name token — `_MEMORY_NAME_TOKEN_RE` requires a LEFT WORD BOUNDARY, and in
      `fakeram45` the `ram` is preceded by `e`. `sram45_2048x39` promotes,
      `fakeram45_2048x39` does not.

WHAT SEPARATES THE MACRO FROM THE JUNK — AND WHAT DOES NOT
----------------------------------------------------------
`_MEMORY_NAME_TOKEN_RE` is untouched: its strict left boundary is what keeps
PROGRAM / DIAGRAM / HISTOGRAM / diagram_ctrl out of `memories[]` (pinned by
`test_v1_0_5_issue612_memory_walker_nonmemory_tokens.py`).

The first attempt at a second clause paired the morpheme with a
`<digits>x<digits>` "organisation token" in the same name. MEASURED, that does
not work: `\\d+\\s*[xX]\\s*\\d+` matches the hex literals `0x12` / `0X7F`, and
`fakeram45_2048x39` and `DIAGRAM_16x9` are otherwise the same string shape.
Tightening the token (no whitespace, then no hex, then anchored at an `_`
boundary, then requiring the morpheme itself to be followed by a digit) never
got below three false accepts — `diagram2_16x9`, `histogram8_256x8`,
`program0_4x4` — and the tightest form falsely REJECTED `dffram_1024x32`, a
real OpenLane macro family. A `<digits>x<digits>` group is evidence of two
numbers, not of a memory. That clause is gone, and
`test_organisation_token_alone_never_promotes` keeps it gone.

The evidence that does separate them comes from OUTSIDE the string: the design
under analysis STAGED `fakeram45_2048x39.lef` (35140 B), `.lib` and `.v` under
its own `input/pdk_local/fakeram45/`, and that LEF declares
`MACRO fakeram45_2048x39`. An aspect ratio, a statistics unit and a hex error
code never have a LEF.
`test_real_doc_without_the_staged_artifact_stays_a_candidate` proves the
artefact — not the name — is the lever.

The promoted row keeps `depth`/`width` as None. Generator conventions disagree
on ORDER — fakeram45_2048x39's own `.v` declares `WORD_DEPTH = 2048` /
`BITS = 39` (depth x width) while sky130 sram macro names are width x depth —
so assigning them from the name would FABRICATE NUMBERS.

chip-AGNOSTIC: open LEF / Liberty / GDS file-and-keyword conventions, read out
of whatever the design under analysis staged. No chip-class string literal
participates in the rule.
"""
import inspect
import os
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

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


def _real_docs_dir():
    """Locate the on-disk edge_llm_accel input docs by STRUCTURE (the
    marketplace nesting means the repo root is several parents up), not by a
    hard-coded parent count."""
    rel = Path("benchmark-data") / "ic" / "edge_llm_accel" / "input" / "docs"
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
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
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
    """The promoted row must NOT carry invented dimensions. Generator naming
    order is not portable, so depth/width stay None and the pre-existing
    `low_confidence` marker stays on the row."""
    real = _real_docs()
    if real is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
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
    ever starts passing on name shape alone, the clause has silently grown a
    lexical rule back and every attack in this file is live again."""
    real = _real_docs()
    if real is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
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
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
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
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
    _docs, design, extracted = real
    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, extracted, design)
    promoted = {e.get("name") for e in (l9.get("memories") or [])}
    candidates = {e.get("name") for e in (l9.get("memory_candidates") or [])}
    assert "NangateOpenCellLibrary" not in promoted
    assert "NangateOpenCellLibrary" in candidates


# ------------------------------------------------- end-to-end junk fragments


# Realistic L1-L9 document prose in the exact Markdown / pipe-table / backtick
# shapes the v1.6.468 back-walker was built for. Each fragment makes the walker
# latch a NON-memory identifier that carries both a memory morpheme and a
# `<digits>x<digits>` (or hex) group — and every one of them was promoted into
# `memories[]` by the first version of this clause. None of these designs
# stages a macro; every row must stay in `memory_candidates[]`.
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
    """Nine end-to-end fragments in the real document shapes. An aspect ratio,
    a statistics unit and a hex error code are not memories."""
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
    so a staged ANALOG hardmacro (`ldo`, `delta_sigma` — both real artefacts
    elsewhere in benchmark-data) latched off nearby memory prose does not
    become a memory row."""
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
    and `0x` is the DEFINING SHAPE of the L4 command-protocol and L5
    register-map documents this walker consumes. The last four names below are
    verbatim identifiers harvested out of this repo's own Bluetooth-HCI error
    tables — real inputs, not invented ones."""
    for nm in ("CMD_PARAM_ERR_0x1F", "PROGRAM_0x40",
               "FP_PDN_HOFFSET_PARAM_0x10", "WITH_CSR_PARAM_0x1",
               "invalid_hci_command_parameters_0x12",
               "memory_capacity_exceeded_0x07",
               "qos_unacceptable_parameter_0x2c",
               "unsupported_feature_or_parameter_value_0x11_370"):
        assert U({"name": nm}) is False, "%s is a hex error code" % nm


def test_staged_artifact_is_the_only_lever():
    """THE HONEST RESIDUAL, asserted as the code's ACTUAL behaviour.

    The surviving conjunct is the memory morpheme, and `DIAGRAM` contains
    `ram`. So a design that really staged `DIAGRAM_16x9.lef` under its own
    `input/pdk_local/` WOULD promote `DIAGRAM_16x9`. That is no longer a
    lexical accident: it means the design shipped a physical macro under that
    cell name. This test pins the TRUE behaviour rather than a prettier one —
    if the rule is ever tightened further, change this test; never let the
    comment and the code drift apart again."""
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
    BARE names; the first version of this clause re-admitted every one of them
    the moment a dimension or hex suffix was appended, while its own comment
    claimed both halves were required. Pin the suffixed forms here so that can
    never silently become true again."""
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
# for the artefact must see it however the design put it there. Symlinking
# a PDK / IP tree into place is the normal staging idiom, and the scan used
# to skip EVERY symlink — file symlinks included, which cannot create a
# traversal loop and were never the thing the guard was for.
#
# Measured on the REAL edge_llm_accel design with the REAL documents, the
# per-file-symlink staging shape produced `memories == []`: the defect this
# whole branch exists to fix, back again, through a different door.
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
    chose. `file-symlink`, `dir-symlink` and `nested-dir-symlink` all returned
    an EMPTY staged set and `memories == []` before this change."""
    if _real_staged_macro_dir() is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel not on disk")
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
    `hardmacro_supply_intent` already read `<project>/input/pdk_local/` and
    already follow file symlinks (`is_file()` and `rglob("*.lef")` + open both
    do). This walker skipped them, so the three programs disagreed about what
    the design had staged — measured, on this exact fixture: phase3 saw
    libs=1 lefs=1 while this walker saw nothing.

    Pinned for FILE symlinks, which is the shape all three agree on. The two
    siblings disagree with EACH OTHER about directory symlinks (phase3's
    top-level `iterdir()`/`is_dir()` follows one, `rglob` does not descend into
    one), so there is no single sibling behaviour to match there; see the
    module comment on `_staged_macro_scan` for how that tie is broken."""
    if _real_staged_macro_dir() is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel not on disk")
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
    more entries than the whole scan budget — a staged standard-cell library,
    which is exactly what a design puts next to its macros."""
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
    assert _scan(tmp_path)[1], (
        "the budget WAS exhausted on this fixture; that must be reported")


def test_exhausted_budget_is_reported_in_l9_and_on_the_affected_rows(
        tmp_path, capsys):
    """WHERE THE TRUNCATION IS READ.

    Same starved fixture, but with the macro directory renamed so it sorts
    AFTER the budget is gone even with fair sharing — the macro is genuinely
    not found, which is the case that must not look like "this design has no
    memory macro".

    Three readers, all of them places somebody already looks: a `[WARN]` on
    stderr while the run happens, `L9.staged_macro_scan_truncated` in the
    document this emitter owns, and a note on the very
    `memory_candidates[]` row that would have been promoted."""
    real = _real_docs()
    if real is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
    if not _ACCEPTS_PROJECT:
        pytest.skip("emitter predates the staged-artefact clause")
    d = Path(tmp_path) / "input" / "pdk_local" / "aaa_stdcells"
    d.mkdir(parents=True)
    for i in range(P._MEMORY_MACRO_MAX_FILES + 100):
        (d / ("cell_%05d.lef" % i)).write_text("", encoding="utf-8")

    l9 = {"top_module": "edge_llm_accel"}
    _emit(l9, real[2], tmp_path)

    promoted = {e.get("name") for e in (l9.get("memories") or [])}
    assert "fakeram45_2048x39" not in promoted        # nothing was fabricated

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


def test_a_complete_scan_reports_nothing_and_changes_no_l9_key(tmp_path):
    """The report exists only when there is something to report. Every design
    in benchmark-data scans completely, so no L9 in the corpus grows a key,
    no typed-field count moves, and the truncation channel cannot become
    noise that readers learn to ignore."""
    if _real_staged_macro_dir() is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel not on disk")
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
