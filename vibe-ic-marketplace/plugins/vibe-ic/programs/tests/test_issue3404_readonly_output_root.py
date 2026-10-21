"""Issue #3404: a read-only audit copy retains original-root references."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / "project_outputs_in_tree_check.py"


def _run(project: Path, original: Path | None = None):
    env = dict(os.environ)
    env.pop("VIBEIC_AUDIT_RELOCATED_FROM", None)
    if original is not None:
        env["VIBEIC_AUDIT_RELOCATED_FROM"] = str(original)
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True, env=env)


def _pair(tmp_path: Path):
    original = tmp_path / "source" / "design"
    report = original / "reports" / "producer.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "future_output": str(original / "reports" / "future.json.tmp"),
    }))
    copy = tmp_path / "audit" / "design"
    shutil.copytree(original, copy)
    return original, copy, report.relative_to(original)


def test_declared_exact_relocation_keeps_original_self_reference_in_tree(tmp_path):
    original, copy, _ = _pair(tmp_path)
    assert _run(original).returncode == 0
    without = _run(copy)
    assert without.returncode == 1, without.stdout + without.stderr
    actual = _run(copy, original)
    assert actual.returncode == 0, actual.stdout + actual.stderr
    assert "in-tree self-reference" in actual.stdout


def test_relocation_does_not_excuse_unrelated_external_storage(tmp_path):
    original, copy, rel = _pair(tmp_path)
    outside = Path("/tmp") / f"issue3404-{tmp_path.name}" / "artifact.gds"
    payload = json.loads((copy / rel).read_text())
    payload["external"] = str(outside)
    (copy / rel).write_text(json.dumps(payload))
    actual = _run(copy, original)
    assert actual.returncode == 1, actual.stdout + actual.stderr
    assert str(outside) in actual.stdout


def test_wrong_relocation_root_excuses_nothing(tmp_path):
    original, copy, _ = _pair(tmp_path)
    wrong = tmp_path / "other" / "design"
    wrong.mkdir(parents=True)
    actual = _run(copy, wrong)
    assert actual.returncode == 1, actual.stdout + actual.stderr
    assert str(original) in actual.stdout
