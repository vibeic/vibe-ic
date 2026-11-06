"""A CLOCK IS NOT A DATAPATH — the authoring handoff must not be declared for a
design whose input contains nothing to author.

Lane czadcrtl, 2026-09-08. Measured on the live tip (main e2b3c08170b5, tree
75d478b34c17, host 8HD-4, load 6.7, image
`192.168.1.112:5000/vibeic-eda@sha256:89a8fd72…`), a `data_converter` front-door
run: `rtl_gen` WAIVEs to `spec-to-rtl` FOUR times — once plus three RTL-repair
retries, every one byte-identical — `phase2/stage1/rtl/` is never created, and
`rtl_validate` / `sim` / `reference_tb` / `yosys_synth` are all REFUSED-TO-RUN
on the absent tree. Phase 2 FAILs. The runner declared a handoff and then
charged the design with the fact that nobody took it.

`analog_interface_classify` already routes an ALL-ANALOG interface to the
analog track (#141) and its own source named the case it could not express:

    "A clocked-but-logic-free SC modulator (clock in, bitstream out, no data,
     no reset) is exactly the case that predicate cannot express."

`digital_datapath_absent` was `not (has_clk or has_rst or has_data)`, so ONE
clock pin re-asserted a digital datapath the rest of the pinout denied.

Chip-AGNOSTIC: every fixture below is a synthetic port list and a synthetic
L-doc set. No design name, PDK, vendor or class keyword is tested for.

THE POLARITY CONTROL IS THE POINT. `test_any_single_census_field_flips_it`
populates EACH census field alone and asserts the verdict flips — a check that
cannot fail is not a check, and a census that answered ABSENT regardless of its
inputs would satisfy the positive test and break every real design.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_interface_classify as AIC                # noqa: E402
import design_one_shot_runner as DOR                   # noqa: E402
import digital_rtl_subject_census as CEN               # noqa: E402

# The shape the defect was measured on: analog inputs, analog refs, raw 1-bit
# bitstream OUTPUTs, and clock INPUTs. No digital data input, no reset.
_CLOCKED_LOGIC_FREE = (
    [{"name": f"in{i}", "direction": "input"} for i in range(1, 7)]
    + [{"name": n, "direction": "inout"} for n in ("vhi", "vlo", "vldo", "vref")]
    + [{"name": f"out{i}", "direction": "output"} for i in range(1, 7)]
    + [{"name": "dout", "direction": "output"}]
    + [{"name": n, "direction": "input"} for n in ("ck4", "ck5", "ck6")]
)

# The same pinout plus ONE digital data input — the fail-safe direction.
_CLOCKED_WITH_DATA = _CLOCKED_LOGIC_FREE + [
    {"name": "start", "direction": "input"}]

#: Every census doc, empty. A field that is PRESENT in the doc and empty is a
#: measured emptiness; a field missing from the doc is NOT_MEASURED.
_EMPTY_DOCS = {
    "L3_CMD_PROTOCOL": {"opcodes": []},
    "L4_REGMAP": {"registers": []},
    "L6_CONTROL_LOGIC": {"fsm_states": [], "fsm_machines": [],
                         "pipeline_stages": []},
    "L9_INTEGRATION_SPEC": {"internal_wires": [], "memories": [],
                            "memory_map": []},
}


def _mk_project(tmp_path: Path, ports: list, docs: dict | None = None,
                omit: tuple = (), with_blocks: bool = True) -> Path:
    """A project carrying an L9 interface, the census L docs, and (as #141's
    own fixture does) a canonical analog block list — `_digital_backend_is_na`
    requires one before it will consider any interface signal at all."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    merged = {k: dict(v) for k, v in (docs or _EMPTY_DOCS).items()}
    l9 = merged.setdefault("L9_INTEGRATION_SPEC", {})
    l9["top_module"] = "dut"
    l9["top_ports"] = ports
    for stem, body in merged.items():
        if stem in omit:
            continue
        (gd / f"{stem}.json").write_text(json.dumps(body))
    if with_blocks:
        ad = tmp_path / "phase3" / "analog"
        ad.mkdir(parents=True, exist_ok=True)
        (ad / "analog_block_list.json").write_text(
            json.dumps({"blocks": ["modulator"]}))
    return tmp_path


def _with_field(stem: str, field: str, value) -> dict:
    docs = {k: dict(v) for k, v in _EMPTY_DOCS.items()}
    docs[stem][field] = value
    return docs


# ── A. the census program ──────────────────────────────────────────────────

def test_clocked_logic_free_has_no_rtl_subject(tmp_path):
    absent, why, ev = CEN.digital_rtl_subject_absent(
        _mk_project(tmp_path, _CLOCKED_LOGIC_FREE))
    assert absent is True, why
    assert ev["interface"]["has_digital_clock_input"] is True, (
        "the fixture must actually carry a clock — otherwise this test is "
        "passing through the pre-existing #141 disjunct, not the new one")
    assert ev["content_census"]["content_absent"] is True
    assert ev["content_census"]["unreadable"] == []


@pytest.mark.parametrize("stem,field", CEN.CENSUS_FIELDS)
def test_any_single_census_field_flips_it(tmp_path, stem, field):
    """THE POLARITY CONTROL. Each census field, populated ALONE, must return
    the verdict to PRESENT. A field nobody reads is not part of a census."""
    p = _mk_project(tmp_path / f"{stem}_{field}", _CLOCKED_LOGIC_FREE,
                    docs=_with_field(stem, field, [{"name": "x"}]))
    absent, why, _ev = CEN.digital_rtl_subject_absent(p)
    assert absent is False, f"{stem}.{field} populated but still ABSENT: {why}"
    assert f"{stem}.{field}" in why


@pytest.mark.parametrize("stem", sorted(_EMPTY_DOCS))
def test_an_unreadable_doc_is_not_an_empty_one(tmp_path, stem):
    """"Could not read it" is NOT "read it and it was empty". A missing census
    doc must keep the RTL track, never grant an emptiness it never saw."""
    if stem == "L9_INTEGRATION_SPEC":
        pytest.skip("L9 carries top_ports; its absence is the #141 fail-safe")
    p = _mk_project(tmp_path / stem, _CLOCKED_LOGIC_FREE, omit=(stem,))
    absent, why, ev = CEN.digital_rtl_subject_absent(p)
    assert absent is False, why
    assert "NOT_MEASURED" in why
    assert any(k.startswith(stem) for k in ev["content_census"]["unreadable"])


def test_a_data_input_keeps_the_rtl_track(tmp_path):
    p = _mk_project(tmp_path, _CLOCKED_WITH_DATA)
    absent, why, _ = CEN.digital_rtl_subject_absent(p)
    assert absent is False, why
    assert "information input" in why


def test_no_l9_is_failsafe_present(tmp_path):
    absent, why, _ = CEN.digital_rtl_subject_absent(tmp_path)
    assert absent is False, why


def test_census_cli_exit_codes(tmp_path):
    assert CEN.main([str(_mk_project(
        tmp_path / "a", _CLOCKED_LOGIC_FREE))]) == 0
    assert CEN.main([str(_mk_project(
        tmp_path / "b", _CLOCKED_WITH_DATA))]) == 1
    (tmp_path / "c").mkdir()
    assert CEN.main([str(tmp_path / "c")]) == 2


def test_submodules_is_deliberately_not_a_census_field():
    """Measured on the design that produced this defect: `L9.submodules` held
    ONE entry whose own `extraction_strategy` was
    `analog_block_multiplicity_v1_6_403` — an ANALOG block. A non-empty
    submodule list is not evidence of DIGITAL content, and counting it would
    have answered PRESENT for a design with no digital content at all."""
    assert ("L9_INTEGRATION_SPEC", "submodules") not in CEN.CENSUS_FIELDS


# ── B. the classifier's second disjunct ────────────────────────────────────

def test_classifier_reports_the_new_disjunct(tmp_path):
    absent, why, ev = AIC.digital_datapath_absent(
        _mk_project(tmp_path, _CLOCKED_LOGIC_FREE))
    assert absent is True, why
    assert "no digital RTL subject" in why
    assert ev["rtl_subject_census"]["absent"] is True


def test_classifier_port_field_is_unchanged():
    """(ii) must not have widened the PORT-level predicate. A clocked pinout is
    still `digital_datapath_absent=False` at `classify_top_ports`; only the
    project-level function, with its second signal, can say otherwise."""
    r = AIC.classify_top_ports(_CLOCKED_LOGIC_FREE)
    assert r["has_digital_clock_input"] is True
    assert r["digital_datapath_absent"] is False


def test_classifier_keeps_rtl_when_content_exists(tmp_path):
    p = _mk_project(tmp_path, _CLOCKED_LOGIC_FREE,
                    docs=_with_field("L4_REGMAP", "registers",
                                     [{"name": "CTRL", "offset": 0}]))
    absent, why, _ = AIC.digital_datapath_absent(p)
    assert absent is False, why
    assert "keep spec-to-rtl" in why


# ── C. the runner: the handoff is no longer declared ───────────────────────

def test_step_rtl_gen_stops_declaring_an_unservable_handoff(tmp_path):
    res = DOR.step_rtl_gen(_mk_project(tmp_path, _CLOCKED_LOGIC_FREE),
                           "data_converter")
    assert res.status == "PASS_WITH_WAIVERS"
    assert res.extras.get("fallback_skill") is None
    assert res.extras.get("deferred_to") == "analog_track"


def test_step_rtl_gen_still_declares_it_when_there_is_a_subject(tmp_path):
    """The control that matters most: a converter whose input DOES declare
    digital content keeps a DIGITAL path — it is not routed to analog.

    vibe-ic#2197 gave `data_converter` a deterministic generator, so the
    digital path this test guards is now reached in one of two ways: the
    generator emits (declared parameters present), or it refuses BY NAME and
    the class's declared author is offered. Both are the digital path; neither
    is `analog_track`. The assertion that was always load-bearing — "this
    design is NOT deferred to analog" — is unchanged and is checked first.
    This fixture declares no decimator parameters, so the refusal arm is the
    one it exercises."""
    p = _mk_project(tmp_path, _CLOCKED_LOGIC_FREE,
                    docs=_with_field("L4_REGMAP", "registers",
                                     [{"name": "CTRL", "offset": 0}]))
    res = DOR.step_rtl_gen(p, "data_converter")
    assert res.extras.get("deferred_to") != "analog_track"
    assert res.extras.get("fallback_skill") == "spec-to-rtl"
    assert res.status in ("PASS_WITH_WAIVERS", "FAIL"), res.detail
    if res.status == "FAIL":
        assert "does not state" in (res.detail or ""), res.detail


# ── D. the halting step, and every consumer of the one resolver ────────────







def test_phase3_gate_moves_with_the_resolver(tmp_path, monkeypatch):
    """The fourth consumer. `phase3_one_shot_runner` owns its own copy of the
    question; a design the phase-2 runner routes to the analog track must not
    be demanded a digital backend by phase 3."""
    import phase3_one_shot_runner as P3
    monkeypatch.setattr("ic_class_profile.detect_ic_class",
                        lambda proj: {"ic_class": "data_converter"})
    p = _mk_project(tmp_path, _CLOCKED_LOGIC_FREE)
    na, reason = P3._is_pure_analog_no_rtl_track(p)
    assert na is True, reason
    q = _mk_project(tmp_path / "q", _CLOCKED_LOGIC_FREE,
                    docs=_with_field("L4_REGMAP", "registers",
                                     [{"name": "CTRL", "offset": 0}]))
    na2, _ = P3._is_pure_analog_no_rtl_track(q)
    assert na2 is False
