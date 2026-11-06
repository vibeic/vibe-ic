"""Issue #1988 — runner-owned identity must reach IP release documents.

The direct producer is correct to emit ``NOT_MEASURED`` when neither the
project nor its caller supplies a fact.  The defect is on the normal runner
path: the caller already owns the IC name, resolved PDK and plugin source SHA,
but used to invoke ``ip_release_docs_gen`` with only the project directory.

These tests keep both halves load-bearing:

* a bare ``input/project.json`` plus runner context measures the three
  Identification fields and names the real provenance channel;
* ``project.json`` remains the higher-priority declaration;
* a field absent from both the design input and runner context remains
  ``NOT_MEASURED`` rather than receiving a plausible default.

The fixture values are synthetic and chip/PDK/vendor agnostic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _release_docs_contract import NOT_MEASURED  # noqa: E402
from _release_kit import SUBJECT, build_project, docs_dir


PROGRAMS = Path(__file__).resolve().parents[1]
PRODUCER = PROGRAMS / "ip_release_docs_gen.py"
GATE = PROGRAMS / "release_docs_check.py"
CONTEXT_REL = "reports/orchestrator/phase3_release_docs_context.json"
SOURCE_SHA = "a" * 40


def _project(root: Path, *, with_layers=True) -> Path:
    """Use the common synthetic kit's strict receipt; no native claim."""
    return build_project(root, packages=(SUBJECT,), with_layers=with_layers)


def _run(path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRODUCER), str(path), *extra],
        capture_output=True, text=True)


def _context(project: Path, *, design: str = "runner_widget",
             pdk: str = "neutral_pdk", role: str | None = None) -> Path:
    path = project / CONTEXT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": "vibeic.phase3.release_docs_context.v1",
        "runner_invocation": {"ic_name": design, "pdk": pdk},
        "run_manifest": {"source_sha": SOURCE_SHA},
    }
    if role is not None:
        l9_path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        l9 = json.loads(l9_path.read_text(encoding="utf-8"))
        l9["module_role"] = role
        l9_path.write_text(json.dumps(l9, indent=2) + "\n", encoding="utf-8")
        body["l9_derivation"] = {
            "module_role": role,
            "source": "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
        }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def _rows(project: Path) -> dict[str, tuple[str, str]]:
    text = (docs_dir(project, SUBJECT) / "IP_DATASHEET.md").read_text(
        encoding="utf-8")
    rows: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 3 and cells[0] not in ("Field", "---"):
            rows[cells[0]] = (cells[1], cells[2])
    return rows


def test_bare_project_runner_context_measures_identification_with_named_sources(
        tmp_path):
    project = _project(tmp_path / "p")
    (project / "input/project.json").write_text("{}\n", encoding="utf-8")
    role = "A synchronous compute block integrated as a hard macro."
    _context(project, role=role)

    result = _run(project, "--run-context", CONTEXT_REL)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = _rows(project)

    assert rows["Design"] == (
        "runner_widget", f"`{CONTEXT_REL}` (runner invocation)")
    assert rows["Target PDK"] == (
        "neutral_pdk", f"`{CONTEXT_REL}` (runner invocation)")
    assert rows["Tree SHA"] == (
        SOURCE_SHA, f"`{CONTEXT_REL}` (run manifest)")
    assert rows["Module role"] == (
        role, "`phase1/generated_docs/L9_INTEGRATION_SPEC.json` "
              "(L9-derived module role)")

    gate = subprocess.run(
        [sys.executable, str(GATE), str(project), "--arm", "ip"],
        capture_output=True, text=True)
    assert gate.returncode == 0, gate.stdout + gate.stderr


def test_project_json_overrides_context_and_absent_role_stays_not_measured(
        tmp_path):
    project = _project(tmp_path / "p", with_layers=False)
    _context(project, design="lower_priority_design",
             pdk="lower_priority_pdk", role=None)

    result = _run(project, "--run-context", CONTEXT_REL)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = _rows(project)

    assert rows["Design"][1] == "`input/project.json`"
    assert rows["Target PDK"][1] == "`input/project.json`"
    assert rows["Design"][0] != "lower_priority_design"
    assert rows["Target PDK"][0] != "lower_priority_pdk"
    assert rows["Module role"][0] == NOT_MEASURED
    assert rows["Module role"][1].startswith("reason:")




@pytest.mark.parametrize("mutation", ["missing_receipt", "changed_view", "changed_input", "unbound_view"])
def test_release_docs_still_refuse_noncurrent_kit(tmp_path, mutation):
    project = _project(tmp_path / "p")
    hm = project / "phase3/stage4/hardmacro"
    receipt = hm / "current_kit.json"
    if mutation == "missing_receipt":
        receipt.unlink()
    elif mutation == "changed_view":
        path = hm / f"{SUBJECT}.lef"
        path.write_text(path.read_text() + "\n# changed after fixture issuance\n")
    elif mutation == "changed_input":
        path = project / "phase2/stage2/constraints/fixture.sdc"
        path.write_text(path.read_text().replace("20", "21"))
    else:
        record = json.loads(receipt.read_text())
        record["outputs"].pop("verilog")
        receipt.write_text(json.dumps(record))
    _context(project)
    result = _run(project, "--run-context", CONTEXT_REL)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "IP_KIT_CURRENT_REFUSED" in result.stdout + result.stderr
    assert not (docs_dir(project, SUBJECT) / "IP_DATASHEET.md").exists()
