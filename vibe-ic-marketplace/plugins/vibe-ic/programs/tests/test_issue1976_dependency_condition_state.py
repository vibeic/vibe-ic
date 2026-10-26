"""#1976 — DT2/DT3 dependency absence is not design inapplicability.

The condition evaluator can only answer whether its files exist.  These tests
pin the post-evaluation distinction required by the flow:

* explicit L20 NOT_APPLICABLE -> honest SKIPPED-CONDITION, declaration cited;
* failed/attempted DFT -> DT2 blocked by the missing DT1 grade;
* pre-route DFT -> DT2 blocked by step 22's missing SPEF;
* completed DT1 + step 22 -> DT2 reaches its own required-output verdict;
* completed DT2 -> DT3 reaches its own required-output verdict.

The module can be run against an older tree by setting ``VIBEIC_I1976_ROOT``.
The new resolver is obtained with ``getattr`` so the old code still executes
every assertion and answers with the wrong observed status; RED is not an
AttributeError/ModuleNotFoundError presence check.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml


_OVERRIDE = os.environ.get("VIBEIC_I1976_ROOT")
_ROOT = (Path(_OVERRIDE).resolve() if _OVERRIDE else
         Path(__file__).resolve().parents[5])
_PLUGIN = _ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
_PROGRAMS = _PLUGIN / "programs"
_TESTS = _PROGRAMS / "tests"
for _path in (str(_TESTS), str(_PROGRAMS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import _hostpaths  # noqa: E402


def _load_flow_module():
    spec = importlib.util.spec_from_file_location(
        f"flow_compliance_check_i1976_{abs(hash(str(_ROOT)))}",
        _PROGRAMS / "flow_compliance_check.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


F = _load_flow_module()


def _flow_path() -> Path:
    # Real checked-in flow artefact, via the repository's portable resolver.
    return _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")


def _flow_steps() -> list[dict]:
    return yaml.safe_load(_flow_path().read_text())["steps"]


def _step(step_id) -> dict:
    return next(step for step in _flow_steps()
                if str(step.get("id")) == str(step_id))


def _result(step_id, status: str, reasons=None):
    step = _step(step_id)
    return F.StepResult(
        id=step_id, name=step.get("name", ""), stage=step.get("stage", ""),
        status=status, reasons=list(reasons or []))


def _condition_skip(step_id):
    step = _step(step_id)
    return _result(
        step_id, "NOT_APPLICABLE",
        [f"condition not met: {step['condition']}"])


def _resolve(project: Path, results: list):
    resolver = getattr(F, "_resolve_dependency_condition_results", None)
    if resolver is not None:
        resolver(project, results, _flow_steps())
    return {str(result.id): result for result in results}


def _write_json(project: Path, rel: str, payload: dict) -> Path:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def _l20(project: Path, applicability: str) -> Path:
    return _write_json(
        project,
        "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json",
        {
            "doc_id": "L20",
            "applicability": applicability,
            "fields": ({"dft_present": False, "scan_chains": []}
                       if applicability == "NOT_APPLICABLE" else
                       {"dft_present": True,
                        "scan_chains": [{"name": "chain0", "length": 8}]}),
            "extraction_status": "EXTRACTED",
            "extraction_evidence": {"source": "synthetic neutral fixture"},
        },
    )


def _touch_grade(project: Path, rel: str) -> None:
    _write_json(project, rel, {"verdict": "PASS", "records": [1]})


def _default_dt2(project, monkeypatch):
    """Real Default condition consumer; only unrelated PDK setup is supplied."""
    import phase3_one_shot_runner as runner
    monkeypatch.setattr(runner, "_backend_parameter_values", lambda *_args: {})
    return runner._default_pnr_rows(
        project, "neutral_core", SimpleNamespace(name="neutral"), "unused",
        ["DT2"], report_name="default_backend")


def test_default_dt2_explicit_design_na_does_not_dispatch(tmp_path, monkeypatch):
    import phase3_one_shot_runner as runner
    _l20(tmp_path, "NOT_APPLICABLE")
    calls = []
    monkeypatch.setattr(runner, "_run_at_speed_atpg_producer",
                        lambda *args, **kwargs: calls.append(args))

    result = _default_dt2(tmp_path, monkeypatch)

    row = result.extras["canonical_steps"][0]
    assert row["status"] == "NOT_APPLICABLE", row
    assert "NOT_APPLICABLE" in row["detail"], row
    assert calls == []


@pytest.mark.parametrize("cached_inputs", [False, True])
def test_default_dt2_retained_unextracted_authority_blocks_dispatch(
        tmp_path, monkeypatch, capsys, cached_inputs):
    import phase3_one_shot_runner as runner
    artifact = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "l20_applicable_unextracted_retained.json")
    declaration = tmp_path / "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json"
    declaration.parent.mkdir(parents=True)
    declaration.write_bytes(artifact.read_bytes())
    # Neutral input has no DFT terms: pre-fix, the real corroboration scanner
    # wrongly lets skeleton defaults stand down this explicit APPLICABLE L20.
    text = tmp_path / "input/docs/neutral.md"
    text.parent.mkdir(parents=True)
    text.write_text("A synchronous arithmetic core computes output data.\n")
    if cached_inputs:
        _write_json(tmp_path, "reports/phase2/dft/transition_coverage.json",
                    {"fixture": "presence is not DFT authority"})
        spef = tmp_path / "phase3/stage3/extracted/neutral.spef"
        spef.parent.mkdir(parents=True)
        spef.write_text("*SPEF fixture\n")
    calls = []
    monkeypatch.setattr(runner, "_run_at_speed_atpg_producer",
                        lambda *args, **kwargs: calls.append(args))

    result = _default_dt2(tmp_path, monkeypatch)

    row = result.extras["canonical_steps"][0]
    assert row["status"] == "NOT_MEASURED", row
    assert result.status == "NOT_MEASURED", result
    assert row["reason_class"] == "input_absent", row
    assert calls == []
    assert "L20_DFT_AUTHORITY_NOT_ESTABLISHED" in capsys.readouterr().err
    assert declaration.read_bytes() == artifact.read_bytes()


def test_default_dt2_source_bound_scope_reaches_launch_admission(
        tmp_path, monkeypatch):
    import flow109_admission
    from l20_dft_scan_topology_extract import extract_dft_scan_topology
    text = tmp_path / "input/docs/neutral.md"
    text.parent.mkdir(parents=True)
    text.write_text(
        "# DFT scan topology\n"
        "| name | length | scan_in | scan_out | clock |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| chain0 | 8 | test_in | test_out | clk |\n")
    fields = extract_dft_scan_topology(tmp_path)
    assert fields and fields["scan_chains"][0]["source"]["document_sha256"]
    _write_json(tmp_path, "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json", {
        "doc_id": "L20", "applicability": "APPLICABLE",
        "extraction_status": "EXTRACTED", "fields": fields,
        "source_documents": ["input/docs/neutral.md"],
        "extraction_evidence": fields["scan_topology_sources"],
    })
    _write_json(tmp_path, "reports/phase2/dft/transition_coverage.json",
                {"fixture": "dispatch eligibility only"})
    spef = tmp_path / "phase3/stage3/extracted/neutral.spef"
    spef.parent.mkdir(parents=True)
    spef.write_text("*SPEF fixture\n")
    calls = []

    class StopBeforeNative(BaseException):
        pass

    def observe_admission(project, sid, params):
        calls.append((project, sid))
        raise StopBeforeNative

    monkeypatch.setattr(flow109_admission, "require_launch_admission",
                        observe_admission)
    with pytest.raises(StopBeforeNative):
        _default_dt2(tmp_path, monkeypatch)
    assert calls == [(tmp_path, "DT2")]


def test_real_flow_opts_dt2_and_dt3_into_dependency_classification():
    """Real-artefact backing: the shipped flow, not a test-authored copy."""
    for step_id in ("DT2", "DT3"):
        step = _step(step_id)
        assert step.get("condition_kind") == "dependency_required", step
        assert step.get("condition_not_applicable") == {
            "l_doc": "L20",
            "applicability": ["NOT_APPLICABLE", "N/A", "NA"],
        }, step


def test_explicit_no_dft_remains_skip_and_cites_its_declaration(tmp_path):
    declaration = _l20(tmp_path, "NOT_APPLICABLE")
    results = [
        _result(11, "NOT_APPLICABLE"),
        _result("DT1", "NOT_APPLICABLE"),
        _condition_skip("DT2"),
        _condition_skip("DT3"),
    ]

    by_id = _resolve(tmp_path, results)

    for step_id in ("DT2", "DT3"):
        result = by_id[step_id]
        assert result.status == "NOT_APPLICABLE", result
        assert not result.cascade_note, result
        reason = "\n".join(result.reasons)
        assert str(declaration.relative_to(tmp_path)) in reason, reason
        assert "NOT_APPLICABLE" in reason, reason


# R-0915-140 — a row whose producer (a blocks_on blocker) FAILED was never owed
# its input and reads NOT_MEASURED(upstream_failed), never FAIL(missing_artefact)
# + blocked-by-upstream(<failed producer>). The attribution these tests pin --
# the note, the producer named, the missing artefact named -- is unchanged.
_NOT_OWED = ("NOT_MEASURED", "upstream_failed")


def test_failed_dft_blocks_dt2_and_dt3_on_the_missing_upstream_grades(tmp_path):
    _l20(tmp_path, "APPLICABLE")
    # Route/extraction completed, isolating the missing DT1 grade.
    _write_json(tmp_path, "phase3/stage3/extracted/core.spef",
                {"format": "synthetic"})
    results = [
        _result(11, "FAIL", ["ATPG failed"]),
        _result("DT1", "FAIL", ["PASS voided: dependency [11]"]),
        _result(22, "PASS"),
        _condition_skip("DT2"),
        _condition_skip("DT3"),
    ]

    by_id = _resolve(tmp_path, results)

    dt2 = by_id["DT2"]
    assert (dt2.status, dt2.reason_class) == _NOT_OWED, dt2
    assert dt2.cascade_note == "blocked-by-upstream(DT1)", dt2
    dt2_reason = "\n".join(dt2.reasons)
    assert "step DT1" in dt2_reason, dt2_reason
    assert "reports/phase2/dft/transition_coverage.json" in dt2_reason, dt2_reason

    dt3 = by_id["DT3"]
    assert (dt3.status, dt3.reason_class) == _NOT_OWED, dt3
    assert dt3.cascade_note == "blocked-by-upstream(DT2)", dt3
    dt3_reason = "\n".join(dt3.reasons)
    assert "step DT2" in dt3_reason, dt3_reason
    assert "reports/phase2/dft/path_delay_coverage.json" in dt3_reason, dt3_reason


def test_pre_route_dft_blocks_dt2_on_step22_missing_spef(tmp_path):
    _l20(tmp_path, "APPLICABLE")
    _touch_grade(tmp_path, "reports/phase2/dft/transition_coverage.json")
    results = [
        _result(11, "PASS"),
        _result("DT1", "PASS"),
        _result(22, "FAIL", ["SPEF was not produced"]),
        _condition_skip("DT2"),
        _condition_skip("DT3"),
    ]

    by_id = _resolve(tmp_path, results)

    dt2 = by_id["DT2"]
    assert (dt2.status, dt2.reason_class) == _NOT_OWED, dt2
    assert dt2.cascade_note == "blocked-by-upstream(22)", dt2
    reason = "\n".join(dt2.reasons)
    assert "step 22" in reason, reason
    assert "phase3/stage3/extracted/*.spef" in reason, reason


def test_completed_dt1_and_step22_reach_dt2s_own_missing_grade(tmp_path):
    _l20(tmp_path, "APPLICABLE")
    _touch_grade(tmp_path, "reports/phase2/dft/transition_coverage.json")
    _write_json(tmp_path, "phase3/stage3/extracted/core.spef",
                {"format": "synthetic"})
    dt2 = _result("DT2", "FAIL", [
        "no required_outputs found: reports/phase2/dft/path_delay_coverage.json"
    ])
    results = [
        _result("DT1", "PASS"), _result(22, "PASS"), dt2,
        _condition_skip("DT3"),
    ]

    by_id = _resolve(tmp_path, results)

    # DT2 WAS owed (DT1 and 22 passed): its own missing grade stays FAIL.
    assert by_id["DT2"].status == "FAIL", by_id["DT2"]
    assert not by_id["DT2"].cascade_note, by_id["DT2"]
    # DT3 waits on DT2, which FAILED: not owed.
    assert (by_id["DT3"].status, by_id["DT3"].reason_class) == _NOT_OWED, (
        by_id["DT3"])
    assert by_id["DT3"].cascade_note == "blocked-by-upstream(DT2)", by_id["DT3"]


def test_completed_dt2_paths_reach_dt3s_own_missing_grade(tmp_path):
    _l20(tmp_path, "APPLICABLE")
    _touch_grade(tmp_path, "reports/phase2/dft/transition_coverage.json")
    _touch_grade(tmp_path, "reports/phase2/dft/path_delay_coverage.json")
    _write_json(tmp_path, "phase3/stage3/extracted/core.spef",
                {"format": "synthetic"})
    dt3 = _result("DT3", "FAIL", [
        "no required_outputs found: reports/phase2/dft/sdd_coverage.json"
    ])
    results = [_result("DT1", "PASS"), _result(22, "PASS"),
               _result("DT2", "PASS"), dt3]

    by_id = _resolve(tmp_path, results)

    assert by_id["DT3"].status == "FAIL", by_id["DT3"]
    assert not by_id["DT3"].cascade_note, by_id["DT3"]
    assert "sdd_coverage.json" in "\n".join(by_id["DT3"].reasons)


def test_dependency_condition_is_blocking_in_the_real_cli(tmp_path):
    """Prove-by-run: the post-pass changes the strict flow's exit code."""
    project = tmp_path / "project"
    project.mkdir()
    _l20(project, "APPLICABLE")
    flow = tmp_path / "flow.yaml"
    flow.write_text(yaml.safe_dump({
        "stages": [{"id": "upstream"}, {"id": "stage4"}],
        "steps": [
            {"id": "DT1", "name": "transition grade", "stage": "upstream",
             "required_outputs": [
                 "reports/phase2/dft/transition_coverage.json"]},
            {"id": 22, "name": "parasitic extraction", "stage": "upstream",
             "required_outputs": ["phase3/stage3/extracted/*.spef"]},
            {"id": "DT2", "name": "path-delay grade", "stage": "stage4",
             "condition_kind": "dependency_required",
             "condition_not_applicable": {
                 "l_doc": "L20",
                 "applicability": ["NOT_APPLICABLE", "N/A", "NA"]},
             "condition": {"files_exist": [
                 "reports/phase2/dft/transition_coverage.json",
                 "phase3/stage3/extracted/*.spef"]},
             "required_outputs": [
                 "reports/phase2/dft/path_delay_coverage.json"],
             "blocks_on": ["DT1", 22]},
        ],
    }, sort_keys=False))

    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / "flow_compliance_check.py"),
         str(project), "--flow-def", str(flow), "--stage-id", "stage4",
         "--skip-yosys-gates"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "VIBE_IC_COMPLIANCE_WORKERS": "1"},
    )

    assert proc.returncode == 1, proc.stdout
    # R-0915-85 — the rendered label is the WORD, and the reason is printed
    # beside it. `MISSING` was both at once; `FAIL (missing_artefact)` is the
    # same fact with the two halves separated, so both are asserted.
    assert "[FAIL             ] Step DT2" in proc.stdout, proc.stdout
    assert "(missing_artefact)" in proc.stdout, proc.stdout
    assert "blocked-by-upstream(DT1)" in proc.stdout, proc.stdout
    assert "reports/phase2/dft/transition_coverage.json" in proc.stdout, proc.stdout
