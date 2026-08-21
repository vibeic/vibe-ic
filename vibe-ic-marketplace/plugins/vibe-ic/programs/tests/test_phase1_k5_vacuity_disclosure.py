#!/usr/bin/env python3
"""ORGANIC #491 — `phase1_k5_quality_check` must distinguish
"checked, nothing wrong" from "nothing to check".

Every test here DRIVES the functions with fixtures in the shape the corpus
ACTUALLY ships (measured at v1.7.68 over 196 tracked L9_INTEGRATION_SPEC.json
and 201 L1_DATASHEET.json / L6_CONTROL_LOGIC.json). None of them asserts on
source text.

The corpus shape, for reference — this is what the old code could not read:

    "submodules": [ {"name": "...", "instances": 1, "role": "...",
                     "type": "...", "evidence": {...},
                     "low_confidence": false,
                     "extraction_strategy": "..."} ]     # a LIST
    "top_ports":  [ {"name": "clk", "direction": "input", "width": 1} ]

The old code read `submodules` as a DICT and ports only from
`dtop_top_level.ports`; both are absent from every shipped document.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "phase1_k5_quality_check.py"

_spec = importlib.util.spec_from_file_location("_k5_491", PROG)
K5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(K5)


# --------------------------------------------------------------------------
# Corpus-shaped fixtures
# --------------------------------------------------------------------------
def _corpus_submodule_entry(name="datapath"):
    """A submodule entry with EXACTLY the keys the corpus ships.

    Measured over the 114 shipped entries: name 114, instances 76, role 76,
    type 60, evidence 58, low_confidence 52, extraction_strategy 31,
    instance_count 8, desc 3. Critically: `ports_mapped` 0."""
    return {
        "name": name,
        "instances": 1,
        "role": "documented submodule",
        "type": "markdown bullet under heading",
        "evidence": {"file": "input/docs/design_description.md"},
        "low_confidence": False,
        "extraction_strategy": "markdown_bullet_under_heading",
    }


def _corpus_port(name, direction="input", width=1, **extra):
    p = {"name": name, "mode": direction, "direction": direction,
         "io": None, "evidence": "input/docs/design_description.md",
         "width": width, "msb": width - 1, "lsb": 0}
    p.update(extra)
    return p


def _write(gen_dir: Path, layers: dict) -> Path:
    gen_dir.mkdir(parents=True, exist_ok=True)
    for name, obj in layers.items():
        (gen_dir / f"{name}.json").write_text(json.dumps(obj))
    return gen_dir


def _run_cli(target, *extra):
    return subprocess.run([sys.executable, str(PROG), str(target), *extra],
                          capture_output=True, text=True)


# ==========================================================================
# 1. The #491 defect itself — the retired checks stay retired, with reasons
# ==========================================================================
RETIRED = {
    "K5-C": "check_generic_port_map",
    "K5-M": "check_axi_not_threaded",
    "K5-N": "check_memory_macro_placeholder",
    "K5-O": "check_tristate_not_hoisted",
    "K5-J": "check_bus_summary_not_expanded",
    "K5-R": "check_ports_summary_signature_placeholder",
}


@pytest.mark.parametrize("check_id,fn_name", sorted(RETIRED.items()))
def test_retired_check_is_gone_and_documented(check_id, fn_name):
    """A retired check must be ABSENT from the module and PRESENT in the
    registry with a reason — deletion with a recorded rationale, not a
    silent disappearance (vibe-ic#439 precedent)."""
    assert not hasattr(K5, fn_name), (
        f"{fn_name} was retired in #491 because its only input key has never "
        f"been produced; it must not be resurrected without re-validating "
        f"that a producer now exists")
    assert check_id in K5._RETIRED_CHECKS
    entry = K5._RETIRED_CHECKS[check_id]
    assert entry["was"] == fn_name
    assert entry["read"] and len(entry["reason"]) > 80, (
        "a retirement must record WHAT it read and WHY that was unreadable")


def test_retired_checks_are_not_in_the_active_set():
    active = {cid for cid, _ in K5._CHECKS}
    assert not (active & set(K5._RETIRED_CHECKS)), (
        "a check cannot be both active and retired")


def test_ports_mapped_is_referenced_nowhere_in_the_active_check_set():
    """The key that made #491 vacuous must not be read by any live check.

    Driven, not grepped: build a doc carrying `ports_mapped` in the ONLY
    shape the retired check could ever have read, and assert no active check
    reports having examined it."""
    l9 = {"submodules": {"a": {"ports_mapped": {"clk": "clk", "rst_n": "rst_n",
                                               "in_bus": "i", "out_bus": "o"}},
                         "b": {"ports_mapped": {"clk": "clk", "rst_n": "rst_n",
                                               "in_bus": "i", "out_bus": "o"}},
                         "c": {"ports_mapped": {"clk": "clk", "rst_n": "rst_n",
                                               "in_bus": "i", "out_bus": "o"}}}}
    findings, census = _census_for({"L9_INTEGRATION_SPEC": l9})
    assert all(f["id"] not in K5._RETIRED_CHECKS for f in findings)


def _census_for(layers, tmp=None):
    import tempfile
    d = Path(tmp or tempfile.mkdtemp()) / "generated_docs"
    _write(d, layers)
    return K5.run_on_with_census(d)


# ==========================================================================
# 2. "checked, nothing wrong" vs "nothing to check"
# ==========================================================================
def test_clean_result_and_vacuous_result_are_distinguishable(tmp_path):
    """The defect class this issue is about.

    Two doc-sets, both yielding ZERO findings. One examined 3 ports; the
    other could not examine anything. They MUST NOT look the same."""
    clean = _write(tmp_path / "clean" / "generated_docs", {
        "L9_INTEGRATION_SPEC": {"top_ports": [
            _corpus_port("clk"), _corpus_port("rst_n"),
            _corpus_port("data_o", "output", 8)]}})
    empty = _write(tmp_path / "empty" / "generated_docs", {
        "L9_INTEGRATION_SPEC": {"top_ports": []}})

    f_clean, c_clean = K5.run_on_with_census(clean)
    f_empty, c_empty = K5.run_on_with_census(empty)

    k5d_clean = next(c for c in c_clean["checks"] if c["check_id"] == "K5-D")
    k5d_empty = next(c for c in c_empty["checks"] if c["check_id"] == "K5-D")

    # Both produce no findings ...
    assert [f for f in f_clean if f["id"] == "K5-D"] == []
    assert [f for f in f_empty if f["id"] == "K5-D"] == []
    # ... but only one of them actually looked at anything.
    assert k5d_clean["applicable"] is True and k5d_clean["examined"] == 3
    assert k5d_empty["applicable"] is False and k5d_empty["examined"] == 0
    assert k5d_empty["note"], "a not-applicable check must say why"


def test_every_not_applicable_result_carries_a_reason(tmp_path):
    """No check may report `applicable=False` without a note — that would
    reintroduce silence in a new shape."""
    d = _write(tmp_path / "generated_docs", {
        "L1_DATASHEET": {"class_path": "digital_arithmetic_primitive"},
        "L9_INTEGRATION_SPEC": {"submodules": [_corpus_submodule_entry()]}})
    _findings, census = K5.run_on_with_census(d)
    bad = [c for c in census["checks"]
           if not c["applicable"] and not c["note"]]
    assert bad == [], f"not-applicable without a reason: {bad}"


def test_census_covers_every_active_check(tmp_path):
    d = _write(tmp_path / "generated_docs", {"L1_DATASHEET": {}})
    _f, census = K5.run_on_with_census(d)
    assert {c["check_id"] for c in census["checks"]} == {c for c, _ in K5._CHECKS}
    assert census["checks_total"] == len(K5._CHECKS)


# ==========================================================================
# 3. The caller fix — rc 2 = NOT CHECKED, so the umbrella records a SKIP
# ==========================================================================
def test_rc_is_2_when_nothing_could_be_examined(tmp_path):
    """`flow_compliance_check._eval_gate_worker` maps rc 2 to a NAMED SKIP
    and ANY other non-1 rc to ("pass", None). Returning 0 with an empty
    finding list is what made this gate a permanent silent PASS inside a P0
    umbrella that advertises it as one of its checkers."""
    empty = tmp_path / "generated_docs"
    empty.mkdir(parents=True)
    r = _run_cli(empty)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT CHECKED" in r.stdout


def test_rc_is_0_and_denominator_disclosed_when_something_was_examined(tmp_path):
    d = _write(tmp_path / "generated_docs", {
        "L9_INTEGRATION_SPEC": {"top_ports": [_corpus_port("clk")]}})
    r = _run_cli(d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "unit(s) examined" in r.stdout
    assert "CHECKED     K5-D" in r.stdout


def test_pass_never_claims_clean_without_a_denominator(tmp_path):
    """The old output printed 'No K5 quality issues detected.' with no
    denominator whether it had examined 196 documents or nothing at all."""
    empty = tmp_path / "generated_docs"
    empty.mkdir(parents=True)
    r = _run_cli(empty)
    assert "No K5 quality issues detected" not in r.stdout, (
        "a gate that examined nothing must not print a clean verdict")


def test_json_mode_emits_the_census(tmp_path):
    d = _write(tmp_path / "generated_docs", {
        "L9_INTEGRATION_SPEC": {"top_ports": [_corpus_port("clk")]}})
    r = _run_cli(d, "--json")
    payload = json.loads(r.stdout)
    assert "census" in payload and "findings" in payload
    assert payload["census"]["examined_total"] >= 1
    assert set(payload["census"]["retired"]) == set(RETIRED)


# ==========================================================================
# 4. K5-D repair — reads the schema the corpus ACTUALLY ships
# ==========================================================================
def test_k5d_reads_v2_flat_schema_the_corpus_ships(tmp_path):
    """MEASURED: dtop_top_level 0/196, top_ports 141/196. The old check read
    only the former, so it returned [] on all 196."""
    d = _write(tmp_path / "generated_docs", {
        "L9_INTEGRATION_SPEC": {"top_ports": [
            _corpus_port("clk"), _corpus_port("q", "output")]}})
    _f, census = K5.run_on_with_census(d)
    k5d = next(c for c in census["checks"] if c["check_id"] == "K5-D")
    assert k5d["applicable"] and k5d["examined"] == 2


def test_k5d_still_reads_v1_nested_schema(tmp_path):
    """Repair must not break the schema-v1 form it was originally written
    for — this is a union, not a replacement."""
    d = _write(tmp_path / "generated_docs", {
        "L9_INTEGRATION_SPEC": {"dtop_top_level": {"ports": [
            _corpus_port("clk"), _corpus_port("q", "output")]}}})
    _f, census = K5.run_on_with_census(d)
    k5d = next(c for c in census["checks"] if c["check_id"] == "K5-D")
    assert k5d["applicable"] and k5d["examined"] == 2


def test_k5d_fires_on_a_port_carrying_both_dir_and_direction(tmp_path):
    """The assertion is live, not theoretical: `direction` (652 entries) and
    `dir` (106) both occur in the corpus — just never yet on one entry."""
    bad = _corpus_port("data_i")
    bad["dir"] = "input"
    d = _write(tmp_path / "generated_docs", {
        "L9_INTEGRATION_SPEC": {"top_ports": [_corpus_port("clk"), bad]}})
    findings, census = K5.run_on_with_census(d)
    k5d = [f for f in findings if f["id"] == "K5-D"]
    assert len(k5d) == 1 and "1/2" in k5d[0]["msg"]
    assert next(c for c in census["checks"]
                if c["check_id"] == "K5-D")["examined"] == 2


@pytest.mark.parametrize("key", ["top_ports", "ports", "top_level_ports",
                                 "top_module_pins"])
def test_k5d_accepts_every_shipped_port_key(key, tmp_path):
    """The #490 union — a doc that landed its ports in ANY accepted key must
    be examined, not silently skipped."""
    d = _write(tmp_path / key / "generated_docs", {
        "L9_INTEGRATION_SPEC": {key: [_corpus_port("clk")]}})
    _f, census = K5.run_on_with_census(d)
    assert next(c for c in census["checks"]
                if c["check_id"] == "K5-D")["examined"] == 1


# ==========================================================================
# 5. Container normalisation — the drift #491 reported
# ==========================================================================
def test_l9_submodules_reads_the_shipped_list_container():
    """36/196 shipped docs carry a non-empty LIST; 0 carry a dict."""
    l9 = {"submodules": [_corpus_submodule_entry("a"),
                         _corpus_submodule_entry("b")]}
    got = K5._l9_submodules(l9)
    assert [e["name"] for e in got] == ["a", "b"]


def test_l9_submodules_still_reads_a_dict_container():
    l9 = {"submodules": {"a": {"role": "x"}, "b": {"role": "y"}}}
    got = K5._l9_submodules(l9)
    assert sorted(e["name"] for e in got) == ["a", "b"]


def test_l9_submodules_keeps_bare_string_entries():
    """16 bare-string entries ship across 2 documents; dropping them
    silently is the same defect class in miniature."""
    got = K5._l9_submodules({"submodules": ["alu", "decoder"]})
    assert [e["name"] for e in got] == ["alu", "decoder"]


# ==========================================================================
# 6. CheckResult back-compatibility
# ==========================================================================
def test_check_result_behaves_exactly_like_a_list():
    r = K5.CheckResult([{"id": "X"}], check_id="X", examined=5)
    assert isinstance(r, list) and len(r) == 1
    assert K5.CheckResult(check_id="Y") == []      # equality is list equality
    acc = []
    acc += r
    assert acc == [{"id": "X"}]
    assert r.examined == 5 and r.applicable is True


def test_check_result_vacuous_property():
    assert K5._na("K5-Z", "because").vacuous is True
    assert K5._seen("K5-Z", [], 0).vacuous is True      # applicable but idle
    assert K5._seen("K5-Z", [], 3).vacuous is False


def test_run_on_still_returns_a_plain_findings_list(tmp_path):
    """Existing callers take `run_on` -> list of findings."""
    d = _write(tmp_path / "generated_docs", {"L1_DATASHEET": {}})
    fs = K5.run_on(d)
    assert isinstance(fs, list)
    assert all(isinstance(f, dict) and "id" in f for f in fs)


# ==========================================================================
# 7. A live check keeps working (guard against over-deletion)
# ==========================================================================
def test_k5p_still_fires_on_missing_class_path(tmp_path):
    """K5-P is the one check with a large real population: MEASURED 163/201
    tracked doc sets fire it. The #491 cleanup must not have disturbed it."""
    d = _write(tmp_path / "generated_docs", {"L1_DATASHEET": {"ic_name": "x"}})
    findings, census = K5.run_on_with_census(d)
    assert [f["id"] for f in findings if f["id"] == "K5-P"] == ["K5-P"]
    assert next(c for c in census["checks"]
                if c["check_id"] == "K5-P")["examined"] == 1


def test_k5p_does_not_blame_an_absent_document_for_a_missing_field(tmp_path):
    """Found while writing these tests. `docs.get("L1", {})` made a project
    with NO L1 at all indistinguishable from an L1 that omits `class_path`,
    so a doc-less project was reported as "L1 has no class_path field" — the
    same examined-nothing-but-spoke defect, one level down. MEASURED: this
    changes nothing on the corpus (all 201 tracked doc-sets carry an L1;
    K5-P still fires 163/201), it only stops the gate inventing a subject."""
    d = tmp_path / "generated_docs"
    d.mkdir(parents=True)
    findings, census = K5.run_on_with_census(d)
    assert [f for f in findings if f["id"] == "K5-P"] == []
    k5p = next(c for c in census["checks"] if c["check_id"] == "K5-P")
    assert k5p["applicable"] is False and "absent" in k5p["note"]


def test_k5p_is_clean_with_a_denominator_when_class_path_present(tmp_path):
    d = _write(tmp_path / "generated_docs", {
        "L1_DATASHEET": {"class_path": "digital_arithmetic_primitive"}})
    findings, census = K5.run_on_with_census(d)
    assert [f for f in findings if f["id"] == "K5-P"] == []
    k5p = next(c for c in census["checks"] if c["check_id"] == "K5-P")
    assert k5p["applicable"] and k5p["examined"] == 1   # checked, nothing wrong


def test_k5a_discloses_the_producer_gap_rather_than_returning_empty(tmp_path):
    """L6.submodule_control_logic is declared in the plugin's own class_kb /
    qbank schema but emitted by no shipping producer (0/201). The check is
    KEPT and must SAY it examined nothing."""
    d = _write(tmp_path / "generated_docs", {
        "L6_CONTROL_LOGIC": {"ic_name": "x", "fsm_states": ["IDLE", "RUN"]}})
    _f, census = K5.run_on_with_census(d)
    k5a = next(c for c in census["checks"] if c["check_id"] == "K5-A")
    assert k5a["applicable"] is False and k5a["examined"] == 0
    assert "submodule_control_logic" in k5a["note"]


def test_k5a_fires_when_the_producer_gap_is_closed(tmp_path):
    """And when a producer DOES emit it, the check must work — proving the
    disclosure is a producer gap, not a dead check."""
    shared = {"states": ["IDLE", "ACTIVE", "DONE"]}
    d = _write(tmp_path / "generated_docs", {
        "L6_CONTROL_LOGIC": {"submodule_control_logic": {
            "a": dict(shared), "b": dict(shared), "c": dict(shared)}}})
    findings, census = K5.run_on_with_census(d)
    assert [f["id"] for f in findings if f["id"] == "K5-A"] == ["K5-A"]
    assert next(c for c in census["checks"]
                if c["check_id"] == "K5-A")["examined"] == 3
