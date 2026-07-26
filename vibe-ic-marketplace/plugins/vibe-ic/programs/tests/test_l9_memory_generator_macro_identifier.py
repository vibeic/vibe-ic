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

The fix is a SECOND, NARROWER clause; `_MEMORY_NAME_TOKEN_RE` is untouched,
because its strict left boundary is what keeps PROGRAM / DIAGRAM / HISTOGRAM /
diagram_ctrl out of `memories[]` (pinned by
`test_v1_0_5_issue612_memory_walker_nonmemory_tokens.py`). The new clause
promotes a name-only row when the name carries a memory morpheme ANYWHERE AND
also carries an explicit `<digits>x<digits>` organisation token. NEITHER HALF
ALONE IS SAFE: the morpheme alone re-admits DIAGRAM, the organisation token
alone admits any floorplan array dimension.

The promoted row keeps `depth`/`width` as None. Generator conventions disagree
on ORDER — fakeram45_2048x39's own `.v` declares `WORD_DEPTH = 2048` /
`BITS = 39` (depth x width) while sky130 sram macro names are width x depth —
so assigning them from the name would FABRICATE NUMBERS.

chip-AGNOSTIC: open memory-compiler naming convention only.
"""
import os
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

U = P._v1_6_441_is_useful_memory_entry


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


# ---------------------------------------------------------------- real doc


def test_real_edge_llm_accel_docs_promote_the_sram_macro():
    """END-TO-END over the REAL on-disk benchmark documents.

    This is the load-bearing test: it drives `_v1_6_426_emit_memories` with the
    actual `benchmark-data/ic/edge_llm_accel/input/docs/*.md` bodies — no
    synthetic document — and asserts the chip's only SRAM hard macro reaches
    `memories[]`."""
    docs = _real_docs_dir()
    if docs is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
    extracted = {}
    for fn in sorted(os.listdir(docs)):
        p = docs / fn
        if p.is_file():
            extracted[fn] = p.read_text(encoding="utf-8", errors="replace")
    assert extracted, "no input docs read"

    l9 = {"top_module": "edge_llm_accel"}
    P._v1_6_426_emit_memories(l9, extracted)

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
    docs = _real_docs_dir()
    if docs is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
    extracted = {}
    for fn in sorted(os.listdir(docs)):
        p = docs / fn
        if p.is_file():
            extracted[fn] = p.read_text(encoding="utf-8", errors="replace")
    l9 = {"top_module": "edge_llm_accel"}
    P._v1_6_426_emit_memories(l9, extracted)
    rows = [e for e in (l9.get("memories") or [])
            if e.get("name") == "fakeram45_2048x39"]
    assert rows, "macro not promoted — see the end-to-end test"
    for r in rows:
        assert r.get("depth") is None, (
            "depth must not be inferred from the macro name: fakeram45 names "
            "are depth x width but sky130 sram names are width x depth")
        assert r.get("width") is None
        assert r.get("low_confidence") is True


def test_real_doc_non_macro_neighbour_stays_a_candidate():
    """Precision guard on the SAME real document: the PDK standard-cell
    library name latched off the same prose (`NangateOpenCellLibrary`) carries
    no memory morpheme and no organisation token, so it must stay in
    `memory_candidates[]`."""
    docs = _real_docs_dir()
    if docs is None:
        pytest.skip("benchmark-data/ic/edge_llm_accel/input/docs not on disk")
    extracted = {}
    for fn in sorted(os.listdir(docs)):
        p = docs / fn
        if p.is_file():
            extracted[fn] = p.read_text(encoding="utf-8", errors="replace")
    l9 = {"top_module": "edge_llm_accel"}
    P._v1_6_426_emit_memories(l9, extracted)
    promoted = {e.get("name") for e in (l9.get("memories") or [])}
    candidates = {e.get("name") for e in (l9.get("memory_candidates") or [])}
    assert "NangateOpenCellLibrary" not in promoted
    assert "NangateOpenCellLibrary" in candidates


# -------------------------------------------------------------- unit level


def test_generator_style_macro_name_is_useful():
    # the exact on-disk macro, plus two other generator families
    assert U({"name": "fakeram45_2048x39"}) is True
    assert U({"name": "fakeram45_1024x32"}) is True
    assert U({"name": "sky130_sram_1kbyte_1rw1r_32x256_8"}) is True


def test_boundary_visible_token_still_promotes_without_dimensions():
    """The original #612 clause is untouched: a left-boundary token alone is
    still sufficient, no organisation token required."""
    assert U({"name": "sram45_2048x39"}) is True
    assert U({"name": "data_ram"}) is True


def test_both_halves_are_required():
    """The conjunction is the whole point — neither half alone promotes."""
    # morpheme, no organisation token
    for nm in ("DIAGRAM", "HISTOGRAM", "PROGRAM", "diagram_ctrl",
               "parameterised", "fakeram45"):
        assert U({"name": nm}) is False, (
            "%s has a memory morpheme but no <digits>x<digits> organisation "
            "token — must NOT promote" % nm)
    # organisation token, no morpheme
    for nm in ("die_area_400x400", "PL_TARGET_DENSITY_2x2", "core_16x16",
               "NangateOpenCellLibrary"):
        assert U({"name": nm}) is False, (
            "%s has no memory morpheme — must NOT promote" % nm)


def test_issue612_negatives_stay_rejected():
    """Every name pinned as a NEGATIVE by
    test_v1_0_5_issue612_memory_walker_nonmemory_tokens.py stays rejected."""
    for nm in ("i_rst", "RESET_PC", "WITH_CSR", "FP_CORE_UTIL",
               "PL_TARGET_DENSITY", "FP_PDN_HOFFSET", "GF180MCU",
               "Cyclone10LP", "sky130_fd_sc_hd", "i_gpio", "o_gpio",
               "PROGRAM", "DIAGRAM", "HISTOGRAM", "diagram_ctrl"):
        assert U({"name": nm}) is False, "#612 negative %s regressed" % nm


def test_issue612_positives_stay_promoted():
    for nm in ("u_sram", "data_ram", "inst_fifo", "l1_cache", "sram0",
               "boot_rom", "regfile_bank", "scratch_mem"):
        assert U({"name": nm}) is True, "#612 positive %s regressed" % nm


def test_non_dict_and_empty_unchanged():
    assert U(None) is False
    assert U({}) is False
    assert U({"name": None}) is False
