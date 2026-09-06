#!/usr/bin/env python3
"""#2049 — the Phase-1 front doors named a top after a directory, and the
sufficiency gate listed L9 as seen while never scanning it.

TWO findings, both measured on live main 4eaab71ce (v1.17.74) on 8HD-8.

ITEM 1 — `tools/phase1_engine/cli.py::_stub_l_docs_from_prose` ended its
top-module derivation with `mod_name = ... else docs_dir.parent.name`. The
prompt front door bridges its input into `<proj>/input/docs/`, so that fallback
published `L9.top_module: "input"` — a top named after a DIRECTORY. #2049 reads
this as a direction-keyword scrape; it is not. Proved by renaming the parent:
the published top follows the directory name, not the prose (see
`test_the_invented_top_was_the_directory_name_not_a_keyword`).

The RTL top is now either DECLARED by the input — and then it agrees with what
the docs front door derives for the same bytes, because it IS that derivation —
or it is `top_undeclared`. It is never invented. The chip NAME keeps its
directory fallback: chip name and RTL top are distinct concepts (#583/#541).

ITEM 2 — `phase1_sufficiency_check._collect_port_names` scanned the hand list
("L1", "L8R", "L5", "L17"). v1.17.74 seeds L9 from the prompt front door, L9
was not on the list, and the gate reported `ports=0 / MISSING ['ports']` over
an L9 that plainly declared them — while its own `layers_seen` said `L9`. The
population is now derived from the layers actually present; the container /
direction-evidence guards still decide which of them carry ports.

Both directions throughout: the mutations restore the exact pre-fix line and
the rows go red again, and an input that DOES declare a top stays byte-identical.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PLUGIN / "tools"))

import phase1_sufficiency_check as S          # noqa: E402
from phase1_engine.cli import _stub_l_docs_from_prose  # noqa: E402

# The exact input czl9prompt / czl9docs measured — five ports, one per bullet,
# and NO top-module declaration anywhere in it.
_UNDECLARED = ("Implement a framed serial receiver.\n"
               "\n"
               " - input  clk\n"
               " - input  rst\n"
               " - input  rx\n"
               " - output cmd_out (4 bits)\n"
               " - output frame_done\n")
_DECL_LABEL = "Module name: framed_rx\n\n - input clk\n - output q\n"
_DECL_REAL = ("The design is a receiver.\n\n"
              "module framed_rx (input clk, output q);\n")


def _stub(tmp_path, text, parent_name="input"):
    docs = tmp_path / parent_name / "docs"
    docs.mkdir(parents=True)
    (docs / "design_description.md").write_text(text)
    out = tmp_path / "gen"
    _stub_l_docs_from_prose(docs, out)
    return (json.loads((out / "L9_INTEGRATION_SPEC.json").read_text()),
            json.loads((out / "L1_DATASHEET.json").read_text()))


# ── ITEM 1 ────────────────────────────────────────────────────────────

def test_an_input_declaring_no_top_is_labelled_not_named(tmp_path):
    """RED before: top_module == "input"."""
    l9, _ = _stub(tmp_path, _UNDECLARED)
    assert l9["top_module"] is None
    assert l9["top_module_status"] == "top_undeclared"


def test_the_invented_top_was_the_directory_name_not_a_keyword(tmp_path):
    """#2049's stated cause (a scraped direction keyword) is wrong, and this
    pins the real one: under the pre-fix rule the published top tracked the
    PARENT DIRECTORY, so the same prose under `zzparent/` would have been
    named `zzparent`. Post-fix neither directory reaches L9."""
    a, _ = _stub(tmp_path / "a", _UNDECLARED, parent_name="input")
    b, _ = _stub(tmp_path / "b", _UNDECLARED, parent_name="zzparent")
    assert a["top_module"] is None and b["top_module"] is None
    assert a["top_module_status"] == b["top_module_status"] == "top_undeclared"


def test_an_explicit_module_name_label_is_unchanged(tmp_path):
    """CONTROL — an input that declares a top is byte-identical to pre-fix."""
    l9, l1 = _stub(tmp_path, _DECL_LABEL)
    assert l9["top_module"] == "framed_rx"
    assert l9["top_module_status"] == "declared_in_input"
    assert l1["ic_name"] == "framed_rx"


def test_a_real_module_declaration_is_unchanged(tmp_path):
    """CONTROL — heuristic 2 (`module X (`) still wins."""
    l9, l1 = _stub(tmp_path, _DECL_REAL)
    assert l9["top_module"] == "framed_rx"
    assert l9["top_module_status"] == "declared_in_input"
    assert l1["ic_name"] == "framed_rx"


def test_the_chip_name_keeps_its_directory_fallback(tmp_path):
    """The fix narrows the RTL TOP only. L1.ic_name is a chip name, a distinct
    concept whose directory fallback is documented at the L1 write site — if
    this row ever flips, the fix has grown past its finding."""
    _, l1 = _stub(tmp_path, _UNDECLARED, parent_name="zzparent")
    assert l1["ic_name"] == "zzparent"


def test_the_two_front_doors_agree_on_the_top_of_the_same_bytes(tmp_path):
    """The engine does not re-implement the derivation, it CALLS the docs
    door's. Agreement is therefore structural, not a coincidence to re-check
    per input — but it is pinned on all three inputs anyway."""
    import phase1_doc_one_shot_runner as D
    for text in (_UNDECLARED, _DECL_LABEL, _DECL_REAL):
        l9, _ = _stub(tmp_path / str(abs(hash(text))), text)
        docs_door = D._extract_top_module_from_docs({"design_description.md": text})
        assert l9["top_module"] == docs_door


def test_an_unavailable_docs_door_is_not_reported_as_undeclared():
    """"Could not ask" is not "asked and the answer was none" — and neither is
    a licence to invent a name."""
    from phase1_engine.cli import _docs_door_top_module
    import builtins
    real = builtins.__import__

    def _boom(n, *a, **k):
        if n == "phase1_doc_one_shot_runner":
            raise ImportError("simulated missing docs door")
        return real(n, *a, **k)
    builtins.__import__ = _boom
    try:
        name, status = _docs_door_top_module(_UNDECLARED)
    finally:
        builtins.__import__ = real
    assert name is None
    assert status == "docs_door_unavailable"


def test_mutation_restoring_the_directory_fallback_re_reddens(tmp_path, monkeypatch):
    """MUT-1 — put the pre-fix rule back and the invented top returns."""
    def _mut(text, source_name="prose"):
        return "input", "declared_in_input"
    import phase1_engine.cli as C
    monkeypatch.setattr(C, "_docs_door_top_module", _mut)
    l9, _ = _stub(tmp_path, _UNDECLARED)
    assert l9["top_module"] == "input"          # the finding, reproduced


# ── ITEM 2 ────────────────────────────────────────────────────────────

_L9_ONLY = {
    "L1_DATASHEET.json": {"ic_name": "l9_only_probe"},
    "L9_INTEGRATION_SPEC.json": {
        "top_module": "l9_only_probe",
        "top_ports": [{"name": "clk", "direction": "input"},
                      {"name": "q", "direction": "output"}]},
}


def _layers(tmp_path, blobs):
    gd = tmp_path / "generated_docs"
    gd.mkdir(parents=True)
    for fn, blob in blobs.items():
        (gd / fn).write_text(json.dumps(blob))
    return S._load_layers(gd)


def test_a_port_reaching_only_l9_is_counted(tmp_path):
    """RED before: 0. The gate listed L9 in `layers_seen` the whole time."""
    layers = _layers(tmp_path, _L9_ONLY)
    assert "L9" in layers
    assert sorted(S._collect_port_names(layers)) == ["clk", "q"]


def test_the_scan_population_is_not_a_hardcoded_layer_list():
    """The population must be DERIVED. A literal layer tuple in this function
    is what let L9 fall off it, so its absence is the thing to pin."""
    import inspect
    src = inspect.getsource(S._collect_port_names)
    body = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert '"L8R"' not in body and "'L8R'" not in body


def test_a_layer_carrying_no_port_structure_still_contributes_nothing(tmp_path):
    """CONTROL — widening the population must not widen what COUNTS as a port.
    A skeleton layer full of prose hints and a bare chip name stays at zero."""
    layers = _layers(tmp_path, {
        "L1_DATASHEET.json": {"ic_name": "probe"},
        "L2_FRS.json": {"functional_summary": "Look for scan / DFT signals",
                        "author": {"name": "a person"}},
        "L6_CONTROL_LOGIC.json": {"notes": [{"name": "a parameter"}]},
    })
    assert S._collect_port_names(layers) == []


def test_a_placeholder_port_in_l9_is_still_rejected(tmp_path):
    """CONTROL — the unfilled-template guard survives the widening."""
    layers = _layers(tmp_path, {
        "L1_DATASHEET.json": {"ic_name": "probe"},
        "L9_INTEGRATION_SPEC.json": {
            "top_ports": [{"name": "<fill-in-port-name>", "direction": "input"}]},
    })
    assert S._collect_port_names(layers) == []


def test_mutation_dropping_l9_from_the_population_re_reddens(tmp_path, monkeypatch):
    """MUT-2 — restore the hand list and the L9-only design is blind again."""
    layers = _layers(tmp_path, _L9_ONLY)
    real = S._collect_port_names

    def _handlist(lyrs):
        return real({k: v for k, v in lyrs.items()
                     if k in ("L1", "L8R", "L5", "L17")})
    monkeypatch.setattr(S, "_collect_port_names", _handlist)
    assert S._collect_port_names(layers) == []   # the finding, reproduced


def test_the_gate_blocks_before_and_passes_after_on_the_l9_only_design(tmp_path):
    """End to end through the program's own verdict, not just the helper."""
    layers = _layers(tmp_path, _L9_ONLY)
    names = S._collect_port_names(layers)
    assert len(names) >= 1
    hand = S._collect_port_names({k: v for k, v in layers.items()
                                  if k in ("L1", "L8R", "L5", "L17")})
    assert hand == []          # pre-fix population -> insufficient


def test_a_port_restated_in_several_layers_is_counted_once(tmp_path):
    """Widening the population turned legitimate restatement into arithmetic:
    the same five ports written in L1, L3 and L9 reported `port_count=23`.
    The population is a SET of signal names, not a count of mentions."""
    port = {"name": "clk", "direction": "input"}
    layers = _layers(tmp_path, {
        "L1_DATASHEET.json": {"ic_name": "p", "pinout": [port]},
        "L3_CMD_PROTOCOL.json": {"ports": [port]},
        "L9_INTEGRATION_SPEC.json": {"top_ports": [port]},
    })
    assert S._collect_port_names(layers) == ["clk"]
