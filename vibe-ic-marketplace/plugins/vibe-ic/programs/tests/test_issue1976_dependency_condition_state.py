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






def _resolve(project: Path, results: list):
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




def test_real_flow_opts_dt2_and_dt3_into_dependency_classification():
    """Real-artefact backing: the shipped flow, not a test-authored copy."""
    for step_id in ("DT2", "DT3"):
        step = _step(step_id)
        assert step.get("condition_kind") == "dependency_required", step
        assert step.get("condition_not_applicable") == {
            "l_doc": "L20",
            "applicability": ["NOT_APPLICABLE", "N/A", "NA"],
        }, step




# R-0915-140 — a row whose producer (a blocks_on blocker) FAILED was never owed
# its input and reads NOT_MEASURED(upstream_failed), never FAIL(missing_artefact)
# + blocked-by-upstream(<failed producer>). The attribution these tests pin --
# the note, the producer named, the missing artefact named -- is unchanged.
_NOT_OWED = ("NOT_MEASURED", "upstream_failed")
