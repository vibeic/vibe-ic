#!/usr/bin/env python3
"""Tests for cross_layer_reference_check.py (vibe-ic#376).

EVERY BEHAVIOUR IS ASSERTED IN BOTH DIRECTIONS. A gate that only ever
FAILs on a gutted fixture proves the fixture is gutted, not that the gate
works; a gate that only ever PASSes proves nothing at all. So each block
below builds ONE fixture, asserts the finding, then changes exactly the
one thing the finding is about and asserts it goes away.

The sharpest test in this file is `test_out_of_scope_join_is_refused`. It
reproduces the fixture that killed the first attempt at this join
(`skills/layer-contract-doctrine/SKILL.md` §7): a DFT layer declaring
`N = 4` and a port whose symbolic width is `N-1:0`. A corpus-global join
by bare name sizes that port to 4 bits and goes green. This mechanism must
REFUSE it and say why — and the test asserts both that it refuses and that
the refused value never reaches the resolved width.

All fixtures are SYNTHESIZED neutral data — invented signal and parameter
names on an invented block. No real design's files are copied, and no
design, vendor or PDK name appears anywhere.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "cross_layer_reference_check.py"

_spec = importlib.util.spec_from_file_location(
    "cross_layer_reference_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ─────────────────────────────────────────────────────── fixtures
def _docs(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(project: Path, name: str, payload) -> None:
    (_docs(project) / name).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _ports(width_symbolic=None, width=1):
    """One clock, one reset and one data port under test."""
    data = {"name": "sample_bus", "mode": "input", "direction": "input",
            "width": width}
    if width_symbolic is not None:
        data["width_symbolic"] = width_symbolic
    return [
        {"name": "clk_in", "mode": "input", "direction": "input", "width": 1},
        {"name": "rst_in", "mode": "input", "direction": "input", "width": 1},
        data,
    ]


def _build(project: Path, *, width_symbolic="ACCUM_W-1:0", width=1,
           params=(("ACCUM_W", "24"),), param_layer="L8_RTL_CONSTANTS.json",
           extra_layers=None):
    ports = _ports(width_symbolic, width)
    _write(project, "L1_DATASHEET.json",
           {"ic_name": "synth_block", "pin_table": ports})
    l9 = {"ic_name": "synth_block", "top_module": "synth_block",
          "top_ports": ports, "ports": ports}
    param_list = [{"name": n, "default": d} for n, d in params]
    if param_layer == "L9_INTEGRATION_SPEC.json":
        l9["parameters"] = param_list
    else:
        _write(project, param_layer, {"parameters": param_list})
    _write(project, "L9_INTEGRATION_SPEC.json", l9)
    _write(project, "L17_CHANNEL_SIGNAL_CATALOG.json",
           {"extraction_status": "EXTRACTION_FOUND_NOTHING",
            "channels": [], "global_signals": []})
    for name, payload in (extra_layers or {}).items():
        _write(project, name, payload)


def _run(project: Path):
    out = project / "verdict.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _codes(rep):
    return sorted(f["code"] for f in (rep or {}).get("findings", []))


# ─────────────────────────── the shipped row, both directions
def test_consumer_cannot_reach_is_reported(tmp_path):
    """Producer resolves; the consumer's own derivation does not."""
    _build(tmp_path)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert _codes(rep) == [mod.CONSUMER_BLIND]
    f = rep["findings"][0]
    # The reference resolved — this is not a "value missing" finding.
    assert f["resolved_value"] == 24
    assert f["observed_value"] == 1
    # Both halves of the id scheme are reported, keyed on the element's own
    # name and NOT on its array index.
    assert "L1:port:sample_bus" in f["producer_ids"]
    assert "L9:port:sample_bus" in f["producer_ids"]
    assert "phase2_scaffold_gen.derive_signals" in f["consumer"]


def test_consumer_that_reaches_the_value_passes(tmp_path):
    """The SAME fixture with the consumer able to see the width: PASS.

    Only `width` changes — the symbolic reference, the parameter and the
    layer set are byte-identical to the failing case above.
    """
    _build(tmp_path, width=24)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert rep["findings"] == []
    assert rep["elements_examined"] >= 1


def test_verdict_mode_is_declared_in_the_json(tmp_path):
    """#376: it must SAY what it is, not leave the mode to be inferred."""
    _build(tmp_path, width=24)
    _, rep = _run(tmp_path)
    assert rep["verdict_mode"] in ("BLOCKS", "ADVISES")
    assert rep["id_scheme"] == "L<layer>:<kind>:<name>"


# ─────────────────────────── dangling, both directions
def test_dangling_reference_is_reported(tmp_path):
    """The width names a parameter no layer declares."""
    _build(tmp_path, params=())
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert _codes(rep) == [mod.DANGLING]
    f = rep["findings"][0]
    assert f["identifier"] == "ACCUM_W"
    assert f["searched_layers"] == ["L8", "L9"]


def test_dangling_reference_repaired_by_declaring_the_parameter(tmp_path):
    _build(tmp_path, params=(("ACCUM_W", "24"),), width=24)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["findings"] == []


# ─────────────────────────── §7 — the join that must be REFUSED
def test_out_of_scope_join_is_refused(tmp_path):
    """MUTATION CONTROL for layer-contract-doctrine §7.

    An unrelated layer declares the identifier. A corpus-global join by
    bare name would size the port from it and report clean. This gate must
    refuse the join, name the layer it refused, and NOT let the refused
    value become a resolved width.
    """
    _build(tmp_path, width_symbolic="CHAIN_N-1:0", params=(),
           extra_layers={
               # A DFT plan's scan-chain count — a different entity that
               # happens to share the identifier.
               "L20_DFT_SCAN_TOPOLOGY.json": {
                   "parameters": [{"name": "CHAIN_N", "default": "4"}]},
           })
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert _codes(rep) == [mod.OUT_OF_SCOPE]
    f = rep["findings"][0]
    assert f["identifier"] == "CHAIN_N"
    assert f["scope_layers"] == ["L8", "L9"]
    assert "L20" in f["target_id"]
    # THE POINT: the refused value never became a width. If the join had
    # been taken, the port would have been sized 4 and the finding would
    # have been a (wrong) CONSUMER_CANNOT_REACH carrying resolved_value 4.
    assert "resolved_value" not in f
    assert mod.CONSUMER_BLIND not in _codes(rep)


def test_same_identifier_inside_the_scope_resolves(tmp_path):
    """The negative control for the refusal: identical fixture, identifier
    moved INTO the declared scope. Now it resolves and is used."""
    _build(tmp_path, width_symbolic="CHAIN_N-1:0",
           params=(("CHAIN_N", "4"),))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert _codes(rep) == [mod.CONSUMER_BLIND]
    assert rep["findings"][0]["resolved_value"] == 4


# ─────────────────────────── unusable target value
def test_unusable_target_value_is_reported_not_guessed(tmp_path):
    """A default the corpus really carries: markdown bold survived extraction.

    Digging `8` out of `**8**` would be guessing which number the design
    meant. The gate says the target is unusable instead.
    """
    _build(tmp_path, params=(("ACCUM_W", "**8**"),))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert _codes(rep) == [mod.UNUSABLE_TARGET]
    assert rep["findings"][0]["declared_value"] == "**8**"


def test_null_default_is_unusable_not_dangling(tmp_path):
    """A parameter declared with no default at all. It RESOLVES (the id
    exists) but carries no value — a different finding from dangling, and
    the distinction is what tells an author which half to repair."""
    _build(tmp_path, params=(("ACCUM_W", None),))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert _codes(rep) == [mod.UNUSABLE_TARGET]


def test_integer_default_resolves(tmp_path):
    _build(tmp_path, params=(("ACCUM_W", 24),), width=24)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep


# ─────────────────────────── scope: either layer of the namespace
def test_parameter_declared_in_l9_resolves(tmp_path):
    """phase1 promotes one parameter extraction into both L8 and L9; a row
    whose scope names both must resolve from either."""
    _build(tmp_path, param_layer="L9_INTEGRATION_SPEC.json", width=24)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep


# ─────────────────────────── vacuous vs clean
def test_design_with_no_reference_is_vacuous_not_pass(tmp_path):
    _build(tmp_path, width_symbolic=None, params=())
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["elements_examined"] == 0


# ─────────────────────────── degrade loudly
def test_missing_generated_docs_is_skip_not_pass(tmp_path):
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"


def test_unparseable_layer_is_error_not_quiet_pass(tmp_path):
    _build(tmp_path, width=24)
    (_docs(tmp_path) / "L9_INTEGRATION_SPEC.json").write_text(
        "{ this is not json", encoding="utf-8")
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "ERROR"
    assert "unparseable" in rep["detail"]


def test_manifest_without_scope_layers_is_rejected(tmp_path):
    """§7 again, at the manifest level: a row with no declared scope IS a
    corpus-global join, so it may not be expressed at all."""
    bad = tmp_path / "refs.json"
    bad.write_text(json.dumps({"references": [{
        "id": "r", "grammar": "symbolic_range",
        "producer": {"layers": ["L9"], "collections": ["ports"],
                     "key_field": "name", "reference_field": "width_symbolic"},
        "target": {"collections": ["parameters"]},
    }]}), encoding="utf-8")
    with pytest.raises(mod.ManifestError):
        mod.load_manifest(bad)


def test_unknown_grammar_is_a_manifest_error_not_a_design_finding(tmp_path):
    """A grammar this resolver cannot run means the row is unjudgeable. That
    is a configuration mistake, and dressing it up as one finding per port
    would blame the design for it."""
    bad = tmp_path / "refs.json"
    bad.write_text(json.dumps({"references": [{
        "id": "r", "grammar": "regex_soup",
        "producer": {"layers": ["L9"], "collections": ["ports"],
                     "key_field": "name", "reference_field": "width_symbolic"},
        "target": {"scope_layers": ["L8"], "collections": ["parameters"]},
    }]}), encoding="utf-8")
    with pytest.raises(mod.ManifestError):
        mod.load_manifest(bad)


def test_unregistered_consumer_adapter_is_a_manifest_error(tmp_path):
    bad = tmp_path / "refs.json"
    bad.write_text(json.dumps({"references": [{
        "id": "r", "grammar": "symbolic_range",
        "producer": {"layers": ["L9"], "collections": ["ports"],
                     "key_field": "name", "reference_field": "width_symbolic"},
        "target": {"scope_layers": ["L8"], "collections": ["parameters"]},
        "consumer": {"adapter": "nothing.at.all"},
    }]}), encoding="utf-8")
    with pytest.raises(mod.ManifestError):
        mod.load_manifest(bad)


def test_value_that_is_not_an_address_is_unparseable_not_dangling(tmp_path):
    """A producer/extractor defect and a missing target are different repairs
    in different files, so they are different codes."""
    _build(tmp_path, width_symbolic="not an address")
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert _codes(rep) == [mod.UNPARSEABLE]
    assert mod.DANGLING not in _codes(rep)


def test_empty_manifest_is_rejected(tmp_path):
    bad = tmp_path / "refs.json"
    bad.write_text(json.dumps({"references": []}), encoding="utf-8")
    with pytest.raises(mod.ManifestError):
        mod.load_manifest(bad)


def test_shipped_manifest_loads_and_declares_scope():
    rows = mod.load_manifest()
    assert rows
    for row in rows:
        assert row["target"]["scope_layers"]
        cons = row.get("consumer") or {}
        if cons.get("adapter"):
            assert cons["adapter"] in mod.CONSUMER_ADAPTERS


# ─────────────────────────── id scheme
def test_ids_are_keyed_on_identity_not_array_index(tmp_path):
    """Re-ordering an emitter's array must not move an id."""
    _build(tmp_path)
    _, rep_a = _run(tmp_path)
    docs = _docs(tmp_path)
    for name in ("L1_DATASHEET.json", "L9_INTEGRATION_SPEC.json"):
        p = docs / name
        payload = json.loads(p.read_text())
        for key in ("pin_table", "top_ports", "ports"):
            if isinstance(payload.get(key), list):
                payload[key] = list(reversed(payload[key]))
        p.write_text(json.dumps(payload), encoding="utf-8")
    _, rep_b = _run(tmp_path)
    assert (sorted(rep_a["findings"][0]["producer_ids"])
            == sorted(rep_b["findings"][0]["producer_ids"]))


# ─────────────────────────── waiver
def test_waiver_downgrades_but_only_with_a_real_rationale(tmp_path):
    _build(tmp_path)
    (tmp_path / "waivers.json").write_text(
        json.dumps({mod.WAIVER_KEY: "too short"}), encoding="utf-8")
    rc, _ = _run(tmp_path)
    assert rc == 1
    (tmp_path / "waivers.json").write_text(json.dumps({
        mod.WAIVER_KEY: ("the parametric width is intentional here and the "
                         "consumer is out of scope for this run")}),
        encoding="utf-8")
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS_WITH_WAIVER"


# ─────────────────────────── corpus mode + baseline, both directions
def _corpus(tmp_path, n_broken: int) -> Path:
    corpus = tmp_path / "corpus"
    for i in range(n_broken):
        _build(corpus / f"cell_{i}")
    _build(corpus / "cell_clean", width=24)
    return corpus


def test_corpus_regression_fails_on_a_new_break(tmp_path):
    corpus = _corpus(tmp_path, 1)
    base = tmp_path / "baseline.json"
    rc = mod.main(["--corpus", str(corpus), "--baseline", str(base),
                   "--write-baseline"])
    assert rc == 0
    assert json.loads(base.read_text())["recorded"] == {
        "port_width_symbolic_to_parameter": {mod.CONSUMER_BLIND: 1}}
    # A second cell grows the same break: that is a REGRESSION.
    _build(corpus / "cell_new")
    assert mod.main(["--corpus", str(corpus), "--baseline", str(base)]) == 1


def test_corpus_regression_passes_when_a_break_is_repaired(tmp_path):
    corpus = _corpus(tmp_path, 2)
    base = tmp_path / "baseline.json"
    mod.main(["--corpus", str(corpus), "--baseline", str(base),
              "--write-baseline"])
    _build(corpus / "cell_0", width=24)          # repaired
    assert mod.main(["--corpus", str(corpus), "--baseline", str(base)]) == 0


def test_corpus_reports_an_unparseable_cell_as_error(tmp_path):
    corpus = _corpus(tmp_path, 1)
    (_docs(corpus / "cell_clean") / "L1_DATASHEET.json").write_text(
        "{oops", encoding="utf-8")
    base = tmp_path / "baseline.json"
    assert mod.main(["--corpus", str(corpus), "--baseline", str(base)]) == 2


# ─────────────────────────── grammar units
@pytest.mark.parametrize("value,expect", [
    ("W-1:0", ("W-1", "0")),
    ("[W-1:0]", ("W-1", "0")),
    # The value is stripped as a whole; inner padding survives and the term
    # matchers tolerate it (see test_term_identifier / test_eval_term).
    (" ACCUM_W-1 : 0 ", ("ACCUM_W-1 ", " 0")),
    ("8", None),
    ("", None),
    (None, None),
    (32, None),
])
def test_parse_symbolic_range(value, expect):
    assert mod.parse_symbolic_range(value) == expect


@pytest.mark.parametrize("term,expect", [
    ("W", "W"), ("W-1", "W"), ("`W`+2", "W"), ("0", None), ("31", None),
    ("A*B", None),
])
def test_term_identifier(term, expect):
    assert mod.term_identifier(term) == expect


@pytest.mark.parametrize("value,expect", [
    (24, 24), ("24", 24), ("`8`", 8), ("**8**", None), (None, None),
    (True, None), ("1(enabled)", None), (2.5, None),
])
def test_target_int_refuses_to_guess(value, expect):
    assert mod.target_int(value) == expect


@pytest.mark.parametrize("term,expect", [
    ("W-1", 23), ("W", 24), ("W+1", 25), ("0", 0), ("MISSING", None),
])
def test_eval_term(term, expect):
    assert mod.eval_term(term, {"W": 24}) == expect


# ── gatekeeper addition at land time ────────────────────────────────────────
def test_the_corpus_is_the_published_cells_not_this_machines_disk(tmp_path):
    """The baseline records COUNTS, so the corpus population decides whether
    CI agrees with a developer. Measured at land time: `rglob` alone finds 46
    L1 documents in a working checkout and 23 in a git worktree — the extra
    ones are leftover local run directories that no reader who clones
    receives. The gate read 4 breaks here against a baseline of 3 recorded in
    a worktree, and FAILED for no change to the code.

    Second instance of this exact shape in one session; the first was
    `provenance_output_hash_completeness_check`, where "shipped" was likewise
    answered from the disk instead of from the published tree.
    """
    import subprocess as sp
    import cross_layer_reference_check as C

    corpus = tmp_path / "ic"
    for name in ("published", "local_leftover"):
        d = corpus / name / "phase1" / "generated_docs"
        d.mkdir(parents=True)
        (d / "L1_DATASHEET.json").write_text("{}")

    # Outside a repository nothing is published, so the disk is the answer.
    assert len(C.corpus_cells(corpus)) == 2

    sp.run(["git", "init", "-q", str(corpus)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        sp.run(["git", "-C", str(corpus), "config", k, v], check=True)
    sp.run(["git", "-C", str(corpus), "add",
            "published/phase1/generated_docs/L1_DATASHEET.json"], check=True)
    sp.run(["git", "-C", str(corpus), "commit", "-qm", "publish"], check=True)

    cells = C.corpus_cells(corpus)
    assert [c.name for c in cells] == ["published"], cells


def test_an_unpublished_run_tree_still_walks_the_disk(tmp_path):
    """The paired half. A run tree handed over on its own has published
    nothing, so restricting to tracked paths would walk zero cells and the
    gate would report a clean corpus it never looked at."""
    import cross_layer_reference_check as C

    corpus = tmp_path / "run"
    d = corpus / "cellA" / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L1_DATASHEET.json").write_text("{}")
    assert [c.name for c in C.corpus_cells(corpus)] == ["cellA"]
