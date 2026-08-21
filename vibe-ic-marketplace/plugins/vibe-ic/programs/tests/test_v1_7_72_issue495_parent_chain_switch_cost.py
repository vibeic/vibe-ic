"""re #495 Stage 4 — the breadcrumb switch, its measured cost, and why it is
NOT thrown here.

`gap_detect._parent_chain` does not split a breadcrumb `class_path`
("any-ic > digital-ic > apb-peripheral") to its leaf, while
`phase1_quality_parity_check`, `no_protocol_consistency_check` and
`layer_extension_presence_check` all do. Normalising it is the master switch:
it is the one change that makes the class-tree floors apply to real doc-sets.

MEASURED over all 201 tracked doc-sets, PYTHONHASHSEED=0, by monkey-patching
`_parent_chain` in-process against a fresh corpus copy:

    gap_detect gaps   0 -> 105     red   0/201 -> 3/201

All 105 land on ONE project, in its three doc-set views, at 35 gaps each. Of
those 35:

     5  the gate reads a key name the producer does not write — the Stage-0
        defect, still unrepaired on the `_fact_covers_path` side:
          L1.package                  producer writes package_info
          L1.electrical_characteristics    producer writes electrical_specs
          L2.requirements             producer writes functional_requirements
          L4.register_map             producer writes register_map_present
          L9.top_level_ports          producer writes ports
     8  `document_id`, on eight separate layers. any-ic.yaml marks it
        `defaultable: true` and no producer in the tree emits it at all; a
        bookkeeping default, not a design deficiency.
    ~9  facts the document EXPLICITLY declares absent from its source via the
        `no_*_in_input` sentinels it already carries (no_pin_table_in_input
        covers pinout + pin_count, no_package_in_input covers package, ...).
        `detect_gaps` has no honest-absence escape and cannot see them.
    ~9  apb-peripheral-specific facts (apb_spec_version / apb_addr_width /
        apb_data_width / wait_states / pslverr_supported / irq_count /
        irq_type / address_alignment / irq_clear_mechanism) demanded of a
        matmul accelerator whose `apb-peripheral` breadcrumb is itself the
        thing under suspicion.

    0   are demonstrably real design defects.

And the switch is not merely a reporting change. With a resolvable chain,
`auto_fill` fills 33 facts per doc-set, among them `L9.top_level_ports = []`
with provenance `defaulted`, which trips `l9_completeness_check`'s "Section
'top_level_ports' exists but is empty" ERROR. gap_detect's own
`_RETIRED_MECHANISMS` block predicted exactly this co-requisite hazard and
recorded that it is PRE-EXISTING and must be fixed first.

So the switch stays off, and these tests pin BOTH halves — the current
behaviour and the cost of changing it — so that throwing it is a deliberate act
with a failing test attached rather than a one-line change whose consequence
has to be rediscovered. Every test here is self-contained; none reads
benchmark-data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
TOOLS = PLUGIN / "tools"
KB = PLUGIN / "agents" / "class_kb"
for p in (str(PROGRAMS), str(TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import phase1_quality_parity_check as Q          # noqa: E402
import layer_extension_presence_check as X       # noqa: E402
import no_protocol_consistency_check as NP       # noqa: E402
from phase1_engine import ingest as ING          # noqa: E402
from phase1_engine import gap_detect as GD       # noqa: E402

BREADCRUMB = "any-ic > digital-ic > apb-peripheral"


def _tree():
    return GD._load_yaml(KB / "class-tree.yaml")


def _docset(tmp_path: Path) -> Path:
    """A minimal doc-set that carries the breadcrumb AND declares honest
    absences the way the real producers do."""
    d = tmp_path / "generated_docs"
    d.mkdir(parents=True)
    (d / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "fixture", "class_path": BREADCRUMB,
        "doc_class": "L1", "package_info": {"type": "QFN"},
        "electrical_specs": {"vdd": "1.8V"},
        "no_pin_table_in_input": True,
        "no_package_in_input": False,
    }))
    (d / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "fixture", "doc_class": "L2",
        "functional_requirements": ["multiply", "accumulate"],
    }))
    (d / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "ic_name": "fixture", "doc_class": "L9",
        "ports": [{"name": "clk"}, {"name": "rst_n"}],
    }))
    return d


# ------------------------------------------------ the inconsistency itself
def test_parent_chain_does_not_split_a_breadcrumb_but_the_others_do(
        tmp_path: Path) -> None:
    chain = GD._parent_chain(BREADCRUMB, _tree())
    assert chain == [BREADCRUMB], (
        "gap_detect._parent_chain now normalises the breadcrumb — the Stage-4 "
        "switch has been thrown; read this module's docstring for the measured "
        "cost and confirm the prerequisites are met")

    # the three other consumers all reduce it to the leaf
    docs = _docset(tmp_path)
    assert Q._resolve_class_path_from_l1(docs) == "apb-peripheral"
    assert NP._resolve_class_path_from_l1(docs) == "apb-peripheral"
    assert GD._parent_chain("apb-peripheral", _tree()) == [
        "any-ic", "digital-ic", "apb-peripheral"]


def test_switch_off_means_zero_gaps_for_a_breadcrumb_doc_set(
        tmp_path: Path) -> None:
    g = ING.from_existing_docs(_docset(tmp_path))
    assert g.class_path == BREADCRUMB
    assert GD.detect_gaps(g, class_kb_root=KB) == [], (
        "a breadcrumb class_path now produces gaps — the switch is on")


# ------------------------------------------------ what the switch would cost
def _normalised(class_path, class_tree, _orig=GD._parent_chain):
    return _orig(str(class_path).split(">")[-1].strip().lower(), class_tree)


def test_switch_on_flags_facts_the_document_declares_absent(
        tmp_path: Path, monkeypatch) -> None:
    """The prerequisite: detect_gaps has no honest-absence escape."""
    monkeypatch.setattr(GD, "_parent_chain", _normalised)
    g = ING.from_existing_docs(_docset(tmp_path))
    gaps = GD.detect_gaps(g, class_kb_root=KB)
    paths = {f"{x.layer}.{x.path}" for x in gaps}
    assert gaps, "switch-on must produce gaps for this fixture"

    # the doc says `no_pin_table_in_input: true`, and is flagged anyway
    assert "L1.pinout" in paths and "L1.pin_count" in paths, sorted(paths)


def test_switch_on_flags_facts_present_under_the_producer_key(
        tmp_path: Path, monkeypatch) -> None:
    """The prerequisite: _fact_covers_path reads names producers do not write."""
    monkeypatch.setattr(GD, "_parent_chain", _normalised)
    g = ING.from_existing_docs(_docset(tmp_path))
    paths = {f"{x.layer}.{x.path}"
             for x in GD.detect_gaps(g, class_kb_root=KB)}

    for demanded, produced in (("L1.package", "L1.package_info"),
                               ("L1.electrical_characteristics",
                                "L1.electrical_specs"),
                               ("L2.requirements",
                                "L2.functional_requirements"),
                               ("L9.top_level_ports", "L9.ports")):
        assert demanded in paths, f"{demanded} not flagged — re-derive"
        assert any(f.path.startswith(produced) for f in g.facts), (
            f"fixture no longer carries {produced}")


def test_switch_on_makes_auto_fill_write_an_empty_required_list(
        tmp_path: Path, monkeypatch) -> None:
    """The CO-REQUISITE HAZARD, pinned.

    gap_detect's own `_RETIRED_MECHANISMS` block records that making
    `class_path` resolve gap-fills the root any-ic template's required
    `L9.top_level_ports` with `[]`, which renders as an empty section and trips
    `l9_completeness_check`'s "exists but is empty" ERROR. It is PRE-EXISTING
    and unfixed, so the switch cannot be thrown without it.
    """
    monkeypatch.setattr(GD, "_parent_chain", _normalised)
    g = ING.from_existing_docs(_docset(tmp_path))
    summary = GD.auto_fill(g, class_kb_root=KB)
    assert summary["filled"] > 0, summary

    empties = [f for f in g.facts
               if f.path == "L9.top_level_ports" and f.value == []]
    assert empties, (
        "auto_fill no longer fills L9.top_level_ports with [] — the "
        "co-requisite hazard may be fixed; re-measure before throwing the "
        "switch")
    assert getattr(empties[0].provenance, "source", None) == "defaulted"


def test_prerequisite_one_is_still_unmet(tmp_path: Path, monkeypatch) -> None:
    """Prerequisite 1: `_fact_covers_path` does not read producer spellings.

    Behavioural, not prose: a fact IS in the graph under the producer's name
    and the matcher still reports the demanded name as missing. When that stops
    being true the recorded cost of the switch is stale and must be re-measured
    before it is thrown — so this test failing is the signal to re-measure, not
    a regression.
    """
    monkeypatch.setattr(GD, "_parent_chain", _normalised)
    g = ING.from_existing_docs(_docset(tmp_path))

    # the fact is present under the producer key ...
    assert any(f.path.startswith("L9.ports") for f in g.facts)
    # ... and the matcher for the demanded key still says "absent"
    assert GD._fact_covers_path(g, "L9.ports") is True
    assert GD._fact_covers_path(g, "L9.top_level_ports") is False, (
        "the required-fact matcher now reads the producer spelling — "
        "prerequisite 1 is met, so re-measure the switch cost recorded in "
        "_parent_chain's docstring before throwing it")
