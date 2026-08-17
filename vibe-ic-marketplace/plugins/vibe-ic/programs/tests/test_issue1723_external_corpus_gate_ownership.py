"""#1723: corpus gates move with their corpus, without disappearing.

The failure that prompted these controls was measurable on the first split
commit: ten BLOCKING gates still ran in ``repo_hygiene_gates.sh`` and returned
eight rc-2 refusals plus two rc-1 missing-directory failures.  A one-word
``run_tolerating_uncheckable`` edit would only hide that fact.  These tests pin
the ownership transfer and both fail-closed edges of the new external lane.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path


_HERE = Path(__file__).resolve()
_DEFAULT_ROOT = _HERE.parents[5]
ROOT = Path(os.environ.get("VIBE_IC_REPO_UNDER_TEST", _DEFAULT_ROOT)).resolve()
CONTRACT = ROOT / "tools/ci/benchmark_data_hygiene_contract.json"
CHECKER = ROOT / "tools/ci/benchmark_data_contract_check.py"
RUNNER = ROOT / "tools/ci/benchmark_data_hygiene_gates.sh"
LANDING = ROOT / "tools/ci/repo_hygiene_gates.sh"
PROGRAMS = ROOT / "vibe-ic-marketplace/plugins/vibe-ic/programs"
_RUN_RE = re.compile(r'^\s*run\s+"([^"]+)"', re.MULTILINE)


EXPECTED = [
    "L-doc field producer",
    "tracked-symlink portability",
    "tracked-symlink target present",
    "evidence citation resolves",
    "citation routing is true",
    "cross-layer reference regression",
    "step FAIL bubbles up",
    "L4 -> SystemRDL disposition",
    "published-evidence index honest",
    "published records not superseded",
]


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True)


def _module():
    spec = importlib.util.spec_from_file_location("benchmark_data_contract_check", CHECKER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _commit_all(repo: Path) -> None:
    _run("git", "init", "-q", str(repo))
    _run("git", "-C", str(repo), "config", "user.email", "fixture@example.invalid")
    _run("git", "-C", str(repo), "config", "user.name", "fixture")
    _run("git", "-C", str(repo), "remote", "add", "origin",
         "https://github.com/vibeic/benchmark-data.git")
    add = _run("git", "-C", str(repo), "add", "-A")
    assert add.returncode == 0, add.stderr
    commit = _run("git", "-C", str(repo), "commit", "-qm", "fixture")
    assert commit.returncode == 0, commit.stderr


def _corpus(tmp_path: Path, *, remote: str | None = None) -> Path:
    root = tmp_path / "benchmark-data"
    (root / "ic").mkdir(parents=True)
    (root / "ic/INDEX.md").write_text("# fixture\n", encoding="utf-8")
    (root / "ic/retention.json").write_text("{}\n", encoding="utf-8")
    (root / "evidence_citation_baseline.json").write_text(
        '{"unresolved": []}\n', encoding="utf-8")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    marker = {
        "schema_version": contract["schema_version"],
        "contract_id": contract["contract_id"],
        "owner_repository": contract["owner_repository"],
        "canonical_remote": contract["canonical_remote"],
        "tooling_repository": "vibeic/vibe-ic",
        "tooling_lock": ".vibe-ic-tooling-lock.json",
        "runner": contract["external_runner"],
        "gates": [row["label"] for row in contract["gates"]],
    }
    (root / ".vibe-ic-corpus.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    _commit_all(root)
    if remote is not None:
        _run("git", "-C", str(root), "remote", "set-url", "origin", remote)
    return root


def test_the_measured_gate_set_moved_instead_of_becoming_skips() -> None:
    """Pre-fix VALUE control: plugin_owned is the measured ten, not absence."""
    landing_labels = _RUN_RE.findall(LANDING.read_text(encoding="utf-8"))
    external_labels = (
        _RUN_RE.findall(RUNNER.read_text(encoding="utf-8"))
        if RUNNER.is_file() else []
    )
    plugin_owned = [label for label in landing_labels if label in EXPECTED]
    external_owned = [label for label in external_labels if label in EXPECTED]
    assert plugin_owned == [], f"plugin landing still owns {plugin_owned!r}"
    assert external_owned == EXPECTED, (
        f"external lane owns {external_owned!r}; expected {EXPECTED!r}"
    )


def test_local_contract_proves_exactly_ten_blocking_external_gates() -> None:
    report = _module().check_local(ROOT)
    assert report["gate_count"] == 10
    assert report["plugin_owned"] == []
    assert report["external_owned"] == EXPECTED


def test_external_runner_refuses_when_no_corpus_was_offered() -> None:
    env = dict(os.environ)
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    proc = subprocess.run(
        ["bash", str(RUNNER)], text=True, capture_output=True, env=env
    )
    assert proc.returncode == 2
    assert "no corpus was examined" in proc.stderr


def test_exact_clean_canonical_checkout_satisfies_preflight(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    report = _module().check_corpus(ROOT, corpus)
    assert report["tracked_paths"] == 4
    assert re.fullmatch(r"[0-9a-f]{40}", report["corpus_commit"])
    assert report["corpus_origin"] == "https://github.com/vibeic/benchmark-data"


def test_wrong_remote_is_not_accepted_as_the_canonical_corpus(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, remote="https://github.com/example/benchmark-data.git")
    proc = _run(
        "python3", str(CHECKER), "--plugin-root", str(ROOT),
        "--corpus", str(corpus),
    )
    assert proc.returncode == 1
    assert "canonical owner" in proc.stderr


def test_dirty_checkout_cannot_supply_published_evidence(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path)
    (corpus / "untracked-result.json").write_text("{}\n", encoding="utf-8")
    proc = _run(
        "python3", str(CHECKER), "--plugin-root", str(ROOT),
        "--corpus", str(corpus),
    )
    assert proc.returncode == 1
    assert "dirty" in proc.stderr


def test_subdirectory_pointer_is_rejected_instead_of_narrowing_silently(
    tmp_path: Path,
) -> None:
    corpus = _corpus(tmp_path)
    proc = _run(
        "python3", str(CHECKER), "--plugin-root", str(ROOT),
        "--corpus", str(corpus / "ic"),
    )
    assert proc.returncode == 1
    assert "exact checkout top level" in proc.stderr


def test_index_checker_understands_the_external_repository_layout(tmp_path: Path) -> None:
    root = tmp_path / "data"
    cell = root / "ic/design/v1.0.0_generic"
    (cell / "phase1/generated_docs").mkdir(parents=True)
    (cell / "reports/audit").mkdir(parents=True)
    (cell / "phase1/generated_docs/L1.json").write_text("{}\n", encoding="utf-8")
    (cell / "RESULT.md").write_text("OVERALL: PASS\n", encoding="utf-8")
    (cell / "reports/audit/phase23_completion_audit.json").write_text(
        json.dumps({
            "verdict": "PASS",
            "step_counts": {"PASS": 1, "FAIL": 0, "MISSING": 0, "WAIVED": 0},
        }) + "\n",
        encoding="utf-8",
    )
    (root / "ic/retention.json").write_text("{}\n", encoding="utf-8")
    _commit_all(root)

    write = _run(
        "python3", str(PROGRAMS / "benchmark_evidence_index.py"),
        "--write", "--data-root", str(root),
    )
    assert write.returncode == 0, write.stdout + write.stderr
    _run("git", "-C", str(root), "add", "ic/INDEX.md")
    _run("git", "-C", str(root), "commit", "-qm", "generated index")
    check = _run(
        "python3", str(PROGRAMS / "benchmark_evidence_index.py"),
        "--check", "--data-root", str(root),
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "1 cell row(s)" in check.stdout

    (cell / "RESULT.md").write_text("OVERALL: FAIL\n", encoding="utf-8")
    drift = _run(
        "python3", str(PROGRAMS / "benchmark_evidence_index.py"),
        "--check", "--data-root", str(root),
    )
    assert drift.returncode == 1
    assert "disagrees with the artefacts" in drift.stdout
