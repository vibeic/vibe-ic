r"""ORGANIC #648 [P2] — phase1 L9 emitted `submodules: []` (and
`no_submodules_in_input: true`) even when the input docs DECLARED the module
hierarchy, dropping every declared child and creating stub-module risk.

Three input conventions were dropped:
  (a) a box-drawing tree under `## Hierarchy` — `_V1_6_534_ASCII_TREE_NODE_RE`'s
      connector class `[|`+\-]` EXCLUDED the Unicode box glyphs └─├│┌┐┘, and a
      connector-less root with a trailing `(...)` annotation broke the no-leading-
      connector branch;
  (b) prose `X instantiates [exactly] one|N `Y`` sentences — no parser existed;
  (c) submodule-heading vocab lacked Hierarchy / Instantiation tree /
      (Submodule) Integration / Port-mapping;
  (d) a wrapper→child markdown port-map table was never routed into the
      submodule port-maps.

Fix (v1.0.38):
  (a) box-drawing-aware `_V1_0_38_ASCII_TREE_NODE_RE` (+ box-glyph spacer
      tolerance in `_V1_0_38_CONNECTOR_ONLY_RE`); the walker is rewired to it and
      now also gates every node through `_is_real_submodule_name`;
  (b) `_v1_0_38_prose_instantiates_children` parses the right-hand child;
  (c) broadened `_RE_L9_BULLET_SUBMOD_HEADING_v1_6_313` vocab; the bullet walker
      now SKIPS an "X instantiates Y" bullet's subject so the parent does not
      leak (the prose parser owns those children);
  (d) `_v1_0_38_wrapper_child_port_maps` routes the table into a submodule
      `port_map`.

ACCEPTANCE (#648): an L2-style box-drawing `## Hierarchy` tree + an L8-style
prose "top instantiates one child" + "child instantiates one grandchild" → the
real end-to-end L9 `submodules` contains BOTH child names.

NO-LEAK: a doc with instantiation-flavoured prose but NO real backtick-fenced
submodule declarations → `submodules` stays [] and `no_submodules_in_input`
stays True (no fabrication).

chip-AGNOSTIC: box-drawing trees, prose "top instantiates child", and
wrapper→child port-map tables are universal hierarchical-SoC documentation
conventions — no chip / vendor / SKU literal participates. Fixture identifiers
use generic `top_wrapper` / `child_a` / `child_b` names.
"""
import json
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402
import _path_layout as _pl  # noqa: E402


# --- #648 discriminating input lines, quoted VERBATIM from the issue ---

# L2-style box-drawing tree under `## Hierarchy` (the verbatim child lines
# `└── child_a` / `    └── child_b`, here with a connector-less annotated root
# so the ≥3-node ASCII-tree floor is met).
L2_HIERARCHY_DOC = (
    "## Hierarchy\n"
    "\n"
    "top_wrapper (top)\n"
    "└── child_a\n"
    "    └── child_b\n"
)

# L8-style prose instantiation sentences (verbatim from the issue body).
L8_INSTANTIATION_DOC = (
    "## Submodule Integration\n"
    "\n"
    "- `top_wrapper` (top) instantiates exactly one `child_a`\n"
    "- `child_a #(.BITS(32))` instantiates one `child_b #(.BITS(32))`\n"
)

# Wrapper→child markdown port-map table (fix d).
PORTMAP_DOC = (
    "## Port-mapping\n"
    "\n"
    "| top_wrapper port | child_a port | width |\n"
    "| ---------------- | ------------ | ----- |\n"
    "| clk              | clk          | 1     |\n"
    "| rst_n            | reset_n      | 1     |\n"
)


def _run_l9(extracted):
    """Drive the REAL end-to-end L9 submodule extraction:
    `gen_l9_integration_spec` (builder: heading vocab + prose-instantiates +
    port-map) followed by the ASCII-art post-emit, against a tmp project, and
    return the parsed L9 doc."""
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        _pl.generated_docs_dir(proj).mkdir(parents=True, exist_ok=True)
        P.gen_l9_integration_spec(proj, extracted, {})
        P._v1_6_526_post_emit_ascii_art_hierarchy(proj, extracted)
        l9_path = _pl.generated_docs_dir(proj) / "L9_INTEGRATION_SPEC.json"
        return json.loads(l9_path.read_text(encoding="utf-8"))


def _names(l9):
    return [s.get("name") for s in l9.get("submodules", [])
            if isinstance(s, dict)]


# ----------------------------- ACCEPTANCE -----------------------------

def test_acceptance_box_tree_plus_prose_yields_both_children():
    """#648 acceptance: box-drawing `## Hierarchy` tree + prose
    "top instantiates one child" + "child instantiates one grandchild"
    → L9 submodules contains BOTH child names, end-to-end."""
    l9 = _run_l9({
        "L2_FRS_human.md": L2_HIERARCHY_DOC,
        "L8_INTEGRATION.md": L8_INSTANTIATION_DOC,
    })
    names = _names(l9)
    assert "child_a" in names, names
    assert "child_b" in names, names
    assert l9.get("no_submodules_in_input") is False, l9.get(
        "no_submodules_in_input")


def test_acceptance_prose_only_yields_both_children_no_parent_leak():
    """Prose instantiation sentences alone yield BOTH children and do NOT
    leak the parent subject (`top_wrapper`) as a submodule."""
    l9 = _run_l9({"L8_INTEGRATION.md": L8_INSTANTIATION_DOC})
    names = _names(l9)
    assert "child_a" in names, names
    assert "child_b" in names, names
    # The parent / subject is never emitted as a submodule of itself.
    assert "top_wrapper" not in names, names


# ---------------- (a) box-drawing ASCII tree walker ----------------

def test_box_drawing_node_regex_accepts_glyph_lines():
    """`└── child_a` / `    └── child_b` match the box-aware node regex and
    yield their identifiers; a connector-less annotated root also matches."""
    assert P._V1_0_38_ASCII_TREE_NODE_RE.match(
        "└── child_a").group("node") == "child_a"
    assert P._V1_0_38_ASCII_TREE_NODE_RE.match(
        "    └── child_b").group("node") == "child_b"
    assert P._V1_0_38_ASCII_TREE_NODE_RE.match(
        "top_wrapper (top)").group("node") == "top_wrapper"


def test_box_drawing_tree_walker_harvests_nodes():
    """The ASCII-art walker harvests the box-drawing tree nodes."""
    nodes = [e["name"] for e in
             P._v1_6_526_walk_ascii_art_hierarchy(L2_HIERARCHY_DOC)]
    assert "child_a" in nodes, nodes
    assert "child_b" in nodes, nodes


def test_box_glyph_spacer_tolerated():
    """A bare box-vertical `│` spacer is tolerated like the ASCII `|`."""
    assert P._V1_0_38_CONNECTOR_ONLY_RE.match("│")
    assert P._V1_0_38_CONNECTOR_ONLY_RE.match("    │  ")


# ---------------- (b) prose-instantiates parser ----------------

def test_prose_instantiates_parser_returns_children_only():
    """The parser returns the right-hand CHILD of each sentence (parent on
    the left is the subject, not emitted)."""
    children = P._v1_0_38_prose_instantiates_children(L8_INSTANTIATION_DOC)
    assert children == ["child_a", "child_b"], children


def test_prose_instantiates_count_qualifiers():
    """`exactly one` / `one` / `two` / a digit / `a` qualifiers are all
    accepted, and the `#(...)` param-override on the child is stripped."""
    doc = (
        "core_a instantiates two `lane_unit`.\n"
        "core_b instantiates 4 `bank_mem`.\n"
        "core_c instantiates a `dma_ctrl #(.W(8))`.\n"
    )
    assert P._v1_0_38_prose_instantiates_children(doc) == [
        "lane_unit", "bank_mem", "dma_ctrl"]


# ---------------- (c) broadened heading vocab ----------------

def test_heading_vocab_broadened():
    """Hierarchy / Instantiation tree / (Submodule) Integration /
    Port-mapping are now recognised submodule-inventory headings."""
    for h in ("## Hierarchy",
              "## Instantiation tree",
              "## Submodule Integration",
              "### Integration",
              "## Port-mapping",
              "## Port mapping"):
        assert P._RE_L9_BULLET_SUBMOD_HEADING_v1_6_313.search(h), h


def test_instantiation_bullet_subject_not_leaked_under_integration_heading():
    """Broadening the vocab must NOT let the bullet walker emit the
    instantiation-sentence SUBJECT (parent) as a submodule."""
    extracted = P._l9_bullet_submodule_extract(L8_INSTANTIATION_DOC)
    assert extracted == [], extracted  # subjects skipped; prose parser owns


def test_plain_bullet_list_under_heading_still_works():
    """Regression: a plain submodule bullet list still extracts normally."""
    doc = "## Submodules\n\n- `alu_core`\n- `regfile_bank`\n- `decode_unit`\n"
    assert P._l9_bullet_submodule_extract(doc) == [
        "alu_core", "regfile_bank", "decode_unit"]


# ---------------- (d) wrapper→child port-map table ----------------

def test_wrapper_child_port_map_router():
    """The router parses the child name + (parent_port -> child_port) pairs."""
    maps = P._v1_0_38_wrapper_child_port_maps(PORTMAP_DOC)
    assert len(maps) == 1
    assert maps[0]["child"] == "child_a"
    assert {"parent_port": "clk", "child_port": "clk"} in maps[0]["port_map"]
    assert {"parent_port": "rst_n", "child_port": "reset_n"} in \
        maps[0]["port_map"]


def test_port_map_table_attaches_port_map_in_l9():
    """End-to-end: a wrapper→child port-map table introduces the child as a
    submodule carrying a `port_map`."""
    l9 = _run_l9({"L8_INTEGRATION.md": PORTMAP_DOC})
    sub = next((s for s in l9.get("submodules", [])
                if isinstance(s, dict) and s.get("name") == "child_a"), None)
    assert sub is not None, _names(l9)
    pm = sub.get("port_map") or []
    assert {"parent_port": "clk", "child_port": "clk"} in pm, pm


# ----------------------------- NO-LEAK -----------------------------

def test_noleak_prose_without_real_submodule_declarations():
    """A doc with instantiation-flavoured prose but NO real backtick-fenced
    submodule declarations must NOT fabricate submodules: the gate
    `_is_real_submodule_name` rejects bare English words, so `submodules`
    stays [] and `no_submodules_in_input` stays True."""
    noleak = (
        "# Overview\n"
        "\n"
        "This design instantiates standard combinational logic and registers.\n"
        "The block diagram shows how data flows through the pipeline.\n"
        "No discrete child modules are declared in this document.\n"
    )
    l9 = _run_l9({"readme.md": noleak})
    assert _names(l9) == [], _names(l9)
    assert l9.get("no_submodules_in_input") is True, l9.get(
        "no_submodules_in_input")


def test_noleak_prose_parser_rejects_bare_english_words():
    """The prose parser itself emits a candidate token, but the call-site
    `_is_real_submodule_name` gate rejects bare-English tokens like
    `logic` is a stem (kept) while `combinational` etc. — confirm the gate
    drops a non-RTL-shaped token surfaced by the parser."""
    # parser surfaces "standard" as a candidate (token after "instantiates")
    cands = P._v1_0_38_prose_instantiates_children(
        "This design instantiates standard combinational logic.")
    # whatever the parser surfaces, the shared gate must reject the
    # bare-English candidate so it never reaches L9.
    for c in cands:
        if c in ("standard", "combinational"):
            assert P._is_real_submodule_name(c) is False, c


def test_empty_doc_no_submodules():
    """Empty / hierarchy-free doc yields no submodules and no fabrication."""
    assert P._v1_0_38_prose_instantiates_children("") == []
    assert P._v1_0_38_wrapper_child_port_maps("") == []
    assert P._v1_6_526_walk_ascii_art_hierarchy("just some prose\n") == []
