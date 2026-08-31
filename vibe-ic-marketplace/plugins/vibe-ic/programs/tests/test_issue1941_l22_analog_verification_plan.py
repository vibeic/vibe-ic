#!/usr/bin/env python3
"""vibe-ic#1941 — L22 must carry the analog/mixed-signal verification plan.

The Phase-1 producer already attributes electrical specifications to
``L5.analog_blocks[]`` and harvests the input's literal ``Verification
intent`` bullets into ``L7.verification_strategy[]``.  L22 nevertheless
contained only five fixed digital categories.  These tests pin the missing
general projection at the runner boundary:

* an analog-applicable IC class gets one L22 row per L5 block, preserving the
  L5 specification rows, the L5-derived intent, its input evidence, and the
  stated PVT matrix;
* a digital-only class is a byte-for-byte no-op — the adapter must not even
  rewrite L22;
* the IC-Expert handoff names the actual generated-layer contract, so an
  expectation author does not mistake L9 integration data for L19
  constraints.

All fixtures are neutral.  No design, vendor, process, or part literal is
used.  The rule is keyed on the IC-class registry's ``analog_applicable``
axis, never on a benchmark name.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import ic_expert_backup_pack as PACK  # noqa: E402
import phase1_doc_one_shot_runner as RUNNER  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


_DIGITAL_CATEGORIES = [
    "Register access (read/write to all register fields; reserved-bit behavior)",
    "Nominal transfer / transaction across the protocol's operating modes",
    "Error and fault condition detection and handling",
    "Reset behavior verification",
    "Back-to-back / sustained operation",
]


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _write_l22(project: Path) -> Path:
    path = project / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
    _write_json(path, {
        "doc_id": "L22",
        "doc_name": "L22_VERIFICATION_PLAN",
        "applicability": "APPLICABLE",
        "extraction_status": "EXTRACTED",
        "fields": {
            "coverage_goals": [],
            "formal_properties": [],
            "regression_matrix": {},
            "verification_plan_present": "implicit",
            "verification_categories_derived_from_spec": _DIGITAL_CATEGORIES,
        },
    })
    return path


def _write_analog_project(project: Path) -> Path:
    gd = project / "phase1/generated_docs"
    _write_json(gd / "L1_DATASHEET.json", {
        "doc_id": "L1",
        "class": "mixed_signal_adc",
        "description": (
            "A data converter with an analog conversion core and a digital "
            "serial output bitstream."),
    })
    _write_json(gd / "L5_ADI_SPEC.json", {
        "doc_id": "L5",
        "no_analog": False,
        "analog_blocks": [
            {
                "name": "supply_regulator",
                "type": "ldo",
                "low_confidence": False,
                "spec": {"specs": [
                    {"name": "Line regulation", "target_raw": "<= 1",
                     "unit": "mV/V", "source": "input/docs/L5_analog.md"},
                    {"name": "Load regulation", "target_raw": "<= 2",
                     "unit": "mV", "source": "input/docs/L5_analog.md"},
                ]},
            },
            {
                "name": "conversion_modulator",
                "type": "delta_sigma",
                "low_confidence": False,
                "spec": {"specs": [
                    {"name": "SNDR", "target_raw": ">= 72", "unit": "dB",
                     "source": "input/docs/L5_analog.md"},
                    {"name": "ENOB", "target_raw": ">= 11.5", "unit": "bit",
                     "source": "input/docs/L5_analog.md"},
                ]},
            },
        ],
        "signaling_summary": "Digital serial output bitstream.",
    })
    _write_json(gd / "L7_VERIFICATION.json", {
        "doc_id": "L7",
        "verification_strategy": [
            {
                "phase": "dc_operating_point_line_load_regulation",
                "method": (
                    "Run DC operating point plus line and load regulation "
                    "sweeps for the regulator."),
                "evidence": (
                    "input/docs/L5_analog.md (Verification intent section)"),
                "extraction_strategy": "verification_intent_bullet_v634",
            },
            {
                "phase": "sndr_enob_transient_input_sweep",
                "method": (
                    "Measure SNDR and ENOB with transient simulation and an "
                    "input sweep for the modulator."),
                "evidence": (
                    "input/docs/L5_analog.md (Verification intent section)"),
                "extraction_strategy": "verification_intent_bullet_v634",
            },
            {
                "phase": "full_pvt_corner_matrix",
                "method": "Run the full TT/SS/FF x -40/27/125 C corner matrix.",
                "evidence": (
                    "input/docs/L5_analog.md (Verification intent section)"),
                "extraction_strategy": "verification_intent_bullet_v634",
            },
        ],
    })
    return _write_l22(project)


def _write_digital_project(project: Path) -> Path:
    gd = project / "phase1/generated_docs"
    _write_json(gd / "L1_DATASHEET.json", {
        "doc_id": "L1",
        "class": "digital_arithmetic_primitive",
        "description": "A clocked integer datapath with no analog content.",
    })
    _write_json(gd / "L5_ADI_SPEC.json", {
        "doc_id": "L5", "no_analog": True, "analog_blocks": [],
    })
    _write_json(gd / "L7_VERIFICATION.json", {
        "doc_id": "L7",
        "verification_strategy": [{
            "phase": "directed_vectors",
            "method": "Compare directed vectors against the reference model.",
            "evidence": "input/docs/L7_verification.md",
            "extraction_strategy": "verification_plan_table",
        }],
    })
    return _write_l22(project)


def test_analog_class_projects_l5_rows_and_intent_into_l22(tmp_path):
    l22_path = _write_analog_project(tmp_path)

    emitted = RUNNER._post_emit_l22_analog_verification_plan(tmp_path)
    assert emitted == 2

    l22 = json.loads(l22_path.read_text(encoding="utf-8"))
    plan = l22["fields"]["verification_plan"]
    assert plan["ic_class"] == "data_converter"
    rows = plan["analog"]
    assert [r["block"] for r in rows] == [
        "supply_regulator", "conversion_modulator"]
    assert [s["name"] for s in rows[0]["specifications"]] == [
        "Line regulation", "Load regulation"]
    assert [s["name"] for s in rows[1]["specifications"]] == [
        "SNDR", "ENOB"]

    regulator_intent = json.dumps(rows[0]["verification_intent"])
    modulator_intent = json.dumps(rows[1]["verification_intent"])
    assert "line and load regulation" in regulator_intent
    assert "SNDR" not in regulator_intent
    assert "SNDR" in modulator_intent
    assert "line and load regulation" not in modulator_intent

    intent_blob = json.dumps(rows, ensure_ascii=False)
    for token in ("DC operating point", "line and load regulation", "SNDR",
                  "ENOB", "transient simulation", "input sweep"):
        assert token in intent_blob
    assert all(r["source_evidence"] for r in rows)
    assert all("input/docs/L5_analog.md" in json.dumps(
        r["source_evidence"]) for r in rows)
    assert plan["corner_matrix"] == {
        "process": ["TT", "SS", "FF"],
        "temperature_c": [-40, 27, 125],
        "source_evidence": [
            "input/docs/L5_analog.md (Verification intent section)"],
    }


def test_emitter_declares_advisory_enforcement():
    source = PROGRAMS / "l22_analog_verification_plan_emit.py"
    assert source.is_file()
    assert "ENFORCEMENT: ADVISORY PRODUCER" in source.read_text()[:2000]


def test_unusable_inputs_degrade_loudly(tmp_path, capsys):
    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 0
    assert "L22 analog verification plan SKIPPED (fail-open)" in \
        capsys.readouterr().err


def test_digital_only_l22_is_byte_identical(tmp_path):
    l22_path = _write_digital_project(tmp_path)
    before = l22_path.read_bytes()

    emitted = RUNNER._post_emit_l22_analog_verification_plan(tmp_path)

    assert emitted == 0
    assert l22_path.read_bytes() == before, (
        "the analog adapter rewrote a digital-only IC's L22")


def test_existing_verification_plan_sibling_is_preserved(tmp_path):
    l22_path = _write_analog_project(tmp_path)
    l22 = json.loads(l22_path.read_text())
    l22["fields"]["verification_plan"] = {
        "digital": [{"name": "pre_existing_digital_plan"}],
    }
    _write_json(l22_path, l22)

    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 2
    plan = json.loads(l22_path.read_text())["fields"]["verification_plan"]
    assert plan["digital"] == [{"name": "pre_existing_digital_plan"}]
    assert len(plan["analog"]) == 2


def test_existing_protocol_plan_list_is_preserved(tmp_path):
    l22_path = _write_analog_project(tmp_path)
    l22 = json.loads(l22_path.read_text())
    protocol_plan = [
        "Exercise the nominal serial transaction",
        "Inject malformed frames and verify recovery",
    ]
    l22["fields"]["verification_plan"] = protocol_plan
    _write_json(l22_path, l22)

    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 2
    plan = json.loads(l22_path.read_text())["fields"]["verification_plan"]
    assert plan["protocol"] == protocol_plan
    assert len(plan["analog"]) == 2


def test_rerun_removes_stale_emitter_owned_corner_matrix(tmp_path):
    l22_path = _write_analog_project(tmp_path)
    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 2
    assert "corner_matrix" in json.loads(
        l22_path.read_text())["fields"]["verification_plan"]

    l7_path = tmp_path / "phase1/generated_docs/L7_VERIFICATION.json"
    l7 = json.loads(l7_path.read_text())
    l7["verification_strategy"] = [
        row for row in l7["verification_strategy"]
        if row["phase"] != "full_pvt_corner_matrix"
    ]
    _write_json(l7_path, l7)

    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 2
    plan = json.loads(l22_path.read_text())["fields"]["verification_plan"]
    assert "corner_matrix" not in plan


def test_block_identity_outranks_shared_spec_vocabulary(tmp_path):
    l22_path = _write_analog_project(tmp_path)
    l5_path = tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json"
    l5 = json.loads(l5_path.read_text())
    for block in l5["analog_blocks"]:
        block["spec"]["specs"].append({
            "name": "Output voltage",
            "target_raw": "characterize",
            "unit": "V",
            "source": "input/docs/L5_analog.md",
        })
    _write_json(l5_path, l5)

    l7_path = tmp_path / "phase1/generated_docs/L7_VERIFICATION.json"
    l7 = json.loads(l7_path.read_text())
    l7["verification_strategy"] = [{
        "phase": "supply_output_voltage",
        "method": "Measure output voltage for the supply regulator.",
        "evidence": "input/docs/L5_analog.md (Verification intent section)",
        "extraction_strategy": "verification_intent_bullet_v634",
    }]
    _write_json(l7_path, l7)

    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 2
    rows = json.loads(l22_path.read_text())[
        "fields"]["verification_plan"]["analog"]
    assert len(rows[0]["verification_intent"]) == 1
    assert rows[1]["verification_intent"] == []

def test_full_block_identifier_breaks_same_type_identity_tie(tmp_path):
    l22_path = _write_analog_project(tmp_path)
    l5_path = tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json"
    l5 = json.loads(l5_path.read_text())
    l5["analog_blocks"] = [
        {
            "name": name,
            "type": "ldo",
            "spec": {"specs": [{
                "name": "Load regulation",
                "target_raw": "characterize",
                "unit": "mV",
                "source": "input/docs/L5_analog.md",
            }]},
        }
        for name in ("ldo_a", "ldo_b")
    ]
    _write_json(l5_path, l5)

    l7_path = tmp_path / "phase1/generated_docs/L7_VERIFICATION.json"
    l7 = json.loads(l7_path.read_text())
    l7["verification_strategy"] = [{
        "phase": "first_regulator_load_sweep",
        "method": "Measure load regulation for ldo_a.",
        "evidence": "input/docs/L5_analog.md (Verification intent section)",
        "extraction_strategy": "verification_intent_bullet_v634",
    }]
    _write_json(l7_path, l7)

    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 2
    rows = json.loads(l22_path.read_text())[
        "fields"]["verification_plan"]["analog"]
    assert len(rows[0]["verification_intent"]) == 1
    assert rows[1]["verification_intent"] == []

    l7 = json.loads(l7_path.read_text())
    l7["verification_strategy"][0]["method"] = (
        "Measure load regulation for the ldo blocks.")
    _write_json(l7_path, l7)
    assert RUNNER._post_emit_l22_analog_verification_plan(tmp_path) == 2
    plan = json.loads(l22_path.read_text())["fields"]["verification_plan"]
    assert all(row["verification_intent"] == [] for row in plan["analog"])
    assert len(plan["unscoped_intent"]) == 1


def test_runner_calls_projection_after_protocol_synth_overlays():
    source = PROGRAMS / "phase1_doc_one_shot_runner.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = {
        n.func.id: n.lineno
        for n in ast.walk(main)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in {
            "_apply_spi", "_post_emit_l22_analog_verification_plan"}
    }
    assert "_post_emit_l22_analog_verification_plan" in calls
    assert calls["_post_emit_l22_analog_verification_plan"] > calls["_apply_spi"]


def test_phase1_end_to_end_carries_analog_intent_into_l22(tmp_path):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "mixed_signal_spec.md").write_text(
        """# Mixed-signal data converter

The design contains a delta-sigma switched-capacitor analog modulator with an
integrator and emits a digital serial output bitstream.  A local low-dropout
regulator supplies the analog core.

## Analog blocks

## Block 1 — `delta_sigma` : switched-capacitor conversion modulator

| Spec | Target | Range | Unit | Note |
|---|---:|---:|---|---|
| SNDR | >= 72 | — | dB | transient input sweep |
| ENOB | >= 11.5 | — | bit | transient input sweep |

## Block 2 — `ldo` : low-dropout analog supply regulator

| Spec | Target | Range | Unit | Note |
|---|---:|---:|---|---|
| Line regulation | <= 1 | — | mV/V | DC sweep |
| Load regulation | <= 2 | — | mV | DC sweep |

## Verification intent

- Run DC operating point plus line/load regulation sweeps for the regulator.
- Measure SNDR and ENOB with transient simulation and an input sweep for the modulator.
- Run the full TT/SS/FF x -40/27/125 C corner matrix.
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_doc_one_shot_runner.py"),
         str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # This deliberately-small fixture has no complete package interface, so
    # unrelated Phase-1 semantic gates may reject the overall run.  The guard
    # is the L22 end-state produced before those post-checks, not their verdict.
    l22_path = tmp_path / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
    assert l22_path.is_file(), proc.stdout[-3000:] + proc.stderr[-1000:]
    l22 = json.loads(l22_path.read_text())
    observed = json.dumps(l22["fields"], ensure_ascii=False)
    assert "SNDR" in observed, observed
    assert "ENOB" in observed, observed
    assert "DC operating point" in observed, observed
    assert all(token in observed for token in ("TT", "SS", "FF", "-40",
                                                "27", "125")), observed


def test_checked_in_accepted_digital_fixtures_are_dry_run_noops():
    from l22_analog_verification_plan_emit import run

    root = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "stage_phase1_on_pass_review")
    projects = sorted(p for p in root.glob("accept_*") if p.is_dir())
    assert projects, "the checked-in accepted-fixture corpus is empty"
    for project in projects:
        l22_path = project / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
        l22 = json.loads(l22_path.read_text())
        before = l22_path.read_bytes()
        report = run(project, ic_class=l22.get("ic_class"), dry_run=True)
        assert report["status"] == "NOT_APPLICABLE", (project, report)
        assert report["emitted_count"] == 0, (project, report)
        assert l22_path.read_bytes() == before, project


def test_expert_handoff_states_the_generated_layer_contract(tmp_path):
    handoff = PACK.assemble(
        prompt="Review the generated L documents against this design input.",
        iface=None,
        target=None,
        expert_skills=[],
        verify_gates=["phase1_expert_parse_track"],
        out_dir=tmp_path,
        output_target="l_doc_expectations.json",
    )

    schema = handoff["generated_layer_contract"]
    assert schema["L9"] == "integration specification"
    assert schema["L19"] == "constraints and implementation context"
