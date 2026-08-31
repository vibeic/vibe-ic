#!/usr/bin/env python3
"""The cross-layer sweep's denominator, measured against the EMITTERS.

`cross_layer_reference_check --corpus` held its reach with ONE instrument: a
recorded total in `cross_layer_reference_baseline.json`, compared against the
total this sweep reached. That number answers two questions at once and can
tell neither from the other, and it is blind to the first whenever it happens
without the second.

MEASURED on main at `e9ec0ce1c1`, on this host, with two clones of the
published-corpus repository:

    ~/benchmark-data/ic        (current)   9 records reached, recorded 9  PASS
    ~/_matrix_benchmark_data/ic (stale)    6 records reached, recorded 9  FAIL
        "[FAIL] ... LOST REACH: examined 9 -> 6 ... an emitter renamed the
         field or the collection, moved the layer, or the corpus shrank"

No emitter had renamed anything. Reach PER PRODUCING CELL was identical in the
two checkouts — 4 carriers each, the stale one simply had one fewer producing
cell. And in BOTH, the manifest reached 3 of those 4: every published cell
emits `width_symbolic` in `L1.pin_table`, `L9.ports`, `L9.top_ports` AND
`L9.top_module_pins`, and the row declared the first three. The checker's own
`evaluate_row` docstring names the fourth. The recorded 9 could never have
shown it, because 9 is exactly what a 3-of-4 reach over 3 cells sums to.

So the denominator is now asked of the documents in front of the sweep —
`offered` (what the emitters carry under the row's producer layers, in any
collection) against `examined` (what the manifest selects) — and the two
outcomes the single total conflated are separated by name.

BOTH DIRECTIONS THROUGHOUT. Each loss is asserted RED with the repair asserted
GREEN beside it, and the paired guard is the one that matters here: an arm that
called every corpus under-reaching would satisfy the first half of every test
below and measure nothing.

All fixtures are SYNTHESIZED neutral data. No design, vendor or PDK name.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "cross_layer_reference_check.py"
_MANIFEST = _HERE.parent / "cross_layer_references.json"

_spec = importlib.util.spec_from_file_location(
    "cross_layer_reference_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

ROW = "port_width_symbolic_to_parameter"

#: The carrier the shipped emitters add and the shipped manifest did not name.
#: Spelled once so a rename of the fixture cannot silently stop testing it.
FOURTH_CARRIER = "top_module_pins"


# ─────────────────────────────────────────────────────────── fixtures
def _ports(width_symbolic="ACCUM_W-1:0", width=1):
    return [
        {"name": "clk_in", "mode": "input", "direction": "input", "width": 1},
        {"name": "sample_bus", "mode": "input", "direction": "input",
         "width": width, "width_symbolic": width_symbolic},
    ]


def _cell(project: Path, *, carriers=("pin_table", "top_ports", "ports"),
          width=1) -> Path:
    """One cell whose L9 carries the reference in `carriers`.

    `pin_table` is L1's carrier and the rest are L9's — the same shape the
    published cells emit, so `offered` counts what a real cell offers.
    """
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    ports = _ports(width=width)

    def _w(name, payload):
        (docs / name).write_text(json.dumps(payload), encoding="utf-8")

    _w("L1_DATASHEET.json",
       {"ic_name": "synth_block",
        "pin_table": ports if "pin_table" in carriers else []})
    l9 = {"ic_name": "synth_block", "top_module": "synth_block"}
    for coll in ("top_ports", "ports", FOURTH_CARRIER):
        l9[coll] = ports if coll in carriers else []
    _w("L9_INTEGRATION_SPEC.json", l9)
    _w("L8_RTL_CONSTANTS.json",
       {"parameters": [{"name": "ACCUM_W", "default": "24"}]})
    _w("L17_CHANNEL_SIGNAL_CATALOG.json",
       {"extraction_status": "EXTRACTION_FOUND_NOTHING",
        "channels": [], "global_signals": []})
    return project


def _manifest_without(tmp_path, collection: str) -> Path:
    """The SHIPPED manifest with one producer collection removed.

    Removing from the shipped row rather than writing a fresh one keeps the
    fixture a statement about what ships: if the shipped manifest ever stops
    declaring `collection`, this helper raises rather than quietly testing an
    arm against a row that never had it.
    """
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    colls = data["references"][0]["producer"]["collections"]
    assert collection in colls, (
        f"the shipped manifest no longer declares {collection}; this fixture "
        f"exists to remove it from a row that has it")
    colls.remove(collection)
    out = tmp_path / "manifest_without.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def _sweep(corpus: Path, base: Path, manifest: Path = None, json_out=None,
           write=False):
    argv = ["--corpus", str(corpus), "--baseline", str(base)]
    if manifest:
        argv += ["--manifest", str(manifest)]
    if json_out:
        argv += ["--json", str(json_out)]
    if write:
        argv.append("--write-baseline")
    return mod.main(argv)


# ───────────────────── the defect: a carrier the manifest never named
def test_an_undeclared_carrier_is_lost_reach_with_the_total_unchanged(
        tmp_path, capsys):
    """THE HEADLINE, and the exact state main shipped in.

    The emitters carry the reference in a fourth collection. The manifest does
    not declare it. The recorded total was MEASURED THROUGH THAT HOLE, so it
    matches perfectly and the ratchet is silent — while a quarter of the
    records the corpus carries are never judged.
    """
    corpus = tmp_path / "corpus"
    _cell(corpus / "cell_0")
    base = tmp_path / "baseline.json"
    manifest = _manifest_without(tmp_path, FOURTH_CARRIER)

    # Record the baseline through the hole, exactly as it was recorded on main.
    assert _sweep(corpus, base, manifest, write=True) == 0
    recorded = json.loads(base.read_text())["examined"][ROW]

    # Now the emitters add the fourth carrier — one more record per cell.
    _cell(corpus / "cell_0",
          carriers=("pin_table", "top_ports", "ports", FOURTH_CARRIER))
    capsys.readouterr()
    out_json = tmp_path / "r.json"
    rc = _sweep(corpus, base, manifest, out_json)
    rep = json.loads(out_json.read_text())

    assert rep["examined"][ROW] == recorded, (
        "precondition: the RECORDED TOTAL is unchanged, so only a measurement "
        "against the emitters can carry this signal")
    assert rep["offered"][ROW] > rep["examined"][ROW]
    assert rc == 1, "the sweep reaches 3 of 4 carriers and reported success"
    err = capsys.readouterr().err
    assert "LOST REACH" in err
    assert f"L9.{FOURTH_CARRIER}" in err, (
        "a reader must be told WHICH collection to declare, not that a "
        "number moved")


def test_declaring_the_carrier_restores_reach_and_the_gate_goes_green(
        tmp_path):
    """THE PAIRED DIRECTION. Same corpus, same baseline; the only change is
    that the row names the collection the emitters emit."""
    corpus = tmp_path / "corpus"
    _cell(corpus / "cell_0",
          carriers=("pin_table", "top_ports", "ports", FOURTH_CARRIER))
    base = tmp_path / "baseline.json"
    partial = _manifest_without(tmp_path, FOURTH_CARRIER)
    # The register is recorded through the hole — rc 1, because the arm this
    # change adds already refuses the 3-of-4 reach that recorded it.
    assert _sweep(corpus, base, partial, write=True) == 1
    assert json.loads(base.read_text())["examined"][ROW] == 3

    out_json = tmp_path / "r.json"
    assert _sweep(corpus, base, None, out_json) == 0
    rep = json.loads(out_json.read_text())
    assert rep["offered"][ROW] == rep["examined"][ROW] == 4
    assert rep["unreached"][ROW] == []


def test_the_shipped_manifest_reaches_every_carrier_a_published_cell_emits(
        tmp_path):
    """THE REPAIR, pinned against the shipped row rather than a fixture copy.

    The four carriers are what every producing cell in the published corpus
    emits (measured at `e9ec0ce1c1`: 3 producing cells x 4 = 12 records). A
    shipped manifest that stops naming one of them is reach the mechanism
    silently does not have.
    """
    project = _cell(tmp_path / "cell",
                    carriers=("pin_table", "top_ports", "ports",
                              FOURTH_CARRIER))
    rows = mod.load_manifest()
    layers = mod.load_layers(project)
    offered, unreached = mod.row_reach(rows[0], layers)
    assert offered == 4, offered
    assert unreached == [], (
        f"the shipped manifest does not declare {unreached}, which the "
        f"emitters carry this reference in")


# ─────────────── the other half of the conflation: a smaller population
def test_a_smaller_corpus_is_not_reported_as_an_emitter_rename(
        tmp_path, capsys):
    """THE SHARD'S RED, and the sentence that was false.

    Reach per cell is intact — the manifest selects everything this corpus
    offers — and there is simply one cell fewer. The verdict stays rc 1 and the
    findings drop is still refused as repair; what may not survive is an
    accusation the sweep never measured.
    """
    corpus = tmp_path / "corpus"
    _cell(corpus / "cell_0")
    _cell(corpus / "cell_1")
    base = tmp_path / "baseline.json"
    assert _sweep(corpus, base, write=True) == 0

    import shutil
    shutil.rmtree(corpus / "cell_1")
    capsys.readouterr()
    out_json = tmp_path / "r.json"
    rc = _sweep(corpus, base, None, out_json)
    rep = json.loads(out_json.read_text())
    cap = capsys.readouterr()

    assert rep["offered"][ROW] == rep["examined"][ROW], (
        "precondition: the manifest still reaches everything this corpus "
        "offers, so nothing about the emitters changed")
    assert rc == 1, "a smaller population is not a pass either"
    assert "SMALLER POPULATION" in cap.err
    assert "LOST REACH" not in cap.err, (
        "no emitter renamed a field, and the verdict may not say one did")
    assert "improved" not in cap.out, (
        "the findings drop across a population change is not a repair")


def test_a_renamed_field_is_still_lost_reach_not_a_smaller_population(
        tmp_path, capsys):
    """THE GUARD THAT KEEPS THE SPLIT HONEST.

    A rename leaves NO collection to name — `offered` goes to zero with
    `examined` — so a naive "examined == offered means population" rule would
    launder the sharpest form of the original defect into a corpus excuse.
    """
    corpus = tmp_path / "corpus"
    _cell(corpus / "cell_0")
    base = tmp_path / "baseline.json"
    assert _sweep(corpus, base, write=True) == 0

    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    data["references"][0]["producer"]["reference_field"] = "width_sym"
    renamed = tmp_path / "renamed.json"
    renamed.write_text(json.dumps(data), encoding="utf-8")

    capsys.readouterr()
    rc = _sweep(corpus, base, renamed)
    err = capsys.readouterr().err
    assert rc == 1
    assert "LOST REACH" in err
    assert "SMALLER POPULATION" not in err


def test_a_row_that_reaches_everything_offered_is_never_called_under_reaching(
        tmp_path, capsys):
    """THE PAIRED GUARD FOR THE NEW ARM. An arm that fired on every corpus
    would satisfy every RED assertion above and be worth nothing."""
    corpus = tmp_path / "corpus"
    _cell(corpus / "cell_0",
          carriers=("pin_table", "top_ports", "ports", FOURTH_CARRIER))
    _cell(corpus / "cell_1",
          carriers=("pin_table", "top_ports", "ports", FOURTH_CARRIER))
    base = tmp_path / "baseline.json"
    assert _sweep(corpus, base, write=True) == 0
    capsys.readouterr()
    assert _sweep(corpus, base) == 0
    assert "LOST REACH" not in capsys.readouterr().err


def test_a_repair_at_full_reach_still_passes_and_is_still_called_improved(
        tmp_path, capsys):
    """The direction that decides whether the arm is usable: a genuine fix
    drops the findings while reach holds, and must still read as a win."""
    corpus = tmp_path / "corpus"
    _cell(corpus / "cell_0",
          carriers=("pin_table", "top_ports", "ports", FOURTH_CARRIER))
    _cell(corpus / "cell_1",
          carriers=("pin_table", "top_ports", "ports", FOURTH_CARRIER))
    base = tmp_path / "baseline.json"
    assert _sweep(corpus, base, write=True) == 0
    # Repair one cell: the width now agrees, so the finding goes, and every
    # producer record is still emitted and still selected.
    _cell(corpus / "cell_0", width=24,
          carriers=("pin_table", "top_ports", "ports", FOURTH_CARRIER))
    capsys.readouterr()
    out_json = tmp_path / "r.json"
    assert _sweep(corpus, base, None, out_json) == 0
    rep = json.loads(out_json.read_text())
    assert rep["examined"][ROW] == rep["offered"][ROW] == 8
    assert "improved" in capsys.readouterr().out


# ───────────────── project mode discloses the gap without judging on it
def test_project_mode_says_the_design_emits_carriers_nobody_looks_at(
        tmp_path, capsys):
    """DISCLOSED, NOT JUDGED — and the disclosure is the point.

    Reddening every design for a gap in the MANIFEST would punish the designs
    for the gate's own hole, so the per-design verdict is unchanged. What a
    reader may not have is silence: a PASS printed over 3 of the 4 records the
    design emits is not the reach that line reads as.
    """
    project = _cell(tmp_path / "cell",
                    carriers=("pin_table", "top_ports", "ports",
                              FOURTH_CARRIER),
                    width=24)
    manifest = _manifest_without(tmp_path, FOURTH_CARRIER)
    rc = mod.main([str(project), "--manifest", str(manifest),
                   "--json", str(tmp_path / "p.json")])
    out = capsys.readouterr().out
    assert rc == 0, "the design is clean; the manifest is what is short"
    assert "[PASS]" in out
    assert f"(reach) this design emits the declared reference in L9.{FOURTH_CARRIER}" \
        in out, out
    rep = json.loads((tmp_path / "p.json").read_text())
    assert rep["records_offered"] == 4
    assert rep["collections_unreached"] == [f"L9.{FOURTH_CARRIER}"]


def test_project_mode_is_silent_when_the_manifest_reaches_everything(
        tmp_path, capsys):
    """THE PAIRED GUARD. A disclosure printed over every design is noise, and
    a reader who learns to skip it will skip the one that matters."""
    project = _cell(tmp_path / "cell",
                    carriers=("pin_table", "top_ports", "ports",
                              FOURTH_CARRIER),
                    width=24)
    assert mod.main([str(project)]) == 0
    assert "(reach)" not in capsys.readouterr().out
