from pathlib import Path

import execution_adapters_backend as adapters
from execution_backend_worker import resolve_input_contract


CANONICAL_L19 = "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
OTHER_MISSING = {
    "phase3/stage3/pnr/post_hold.def",
    "phase1/pdk_staging_read.json",
    "reports/phase2/dft",
    "reports/pdk_via_patch_legalization.json",
    "phase3/stage3/pnr",
}


def _step21_contract():
    return adapters._backend_input_contract("21", adapters.BACKEND_ROWS["21"])


def _canonical_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    l19 = project / CANONICAL_L19
    l19.parent.mkdir(parents=True)
    l19.write_text('{"pdk":"neutral_process"}\n')
    return project


def _phase1_locator_contract():
    return tuple(
        item for item in _step21_contract()
        if isinstance(item, str)
        and item in {"phase1/generated_docs", CANONICAL_L19,
                     "phase1/merged_docs"}
    )


def test_step21_canonical_generated_l19_passes_the_locator_contract(tmp_path):
    project = _canonical_project(tmp_path)

    assert _phase1_locator_contract() == (
        "phase1/generated_docs", CANONICAL_L19)
    assert resolve_input_contract(project, _phase1_locator_contract()) == []


def test_step21_missing_canonical_l19_refuses(tmp_path):
    project = _canonical_project(tmp_path)
    (project / CANONICAL_L19).unlink()
    (project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json").write_text("{}\n")

    assert resolve_input_contract(project, _phase1_locator_contract()) == [
        CANONICAL_L19]


def test_step21_foreign_merged_l19_cannot_substitute(tmp_path):
    project = _canonical_project(tmp_path)
    (project / CANONICAL_L19).unlink()
    (project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json").write_text("{}\n")
    foreign = project / "phase1/merged_docs/L19_CONSTRAINTS_PDK.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text('{"pdk":"foreign_process"}\n')

    missing = resolve_input_contract(project, _phase1_locator_contract())

    assert missing == [CANONICAL_L19]
    assert "phase1/merged_docs" not in _step21_contract()


def test_step21_other_missing_dependencies_still_refuse(tmp_path):
    project = _canonical_project(tmp_path)

    missing = set(resolve_input_contract(project, _step21_contract()))

    assert CANONICAL_L19 not in missing
    assert OTHER_MISSING <= missing
