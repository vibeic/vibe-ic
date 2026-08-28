"""#587 — a runner report kept a foreign project path and its stale verdict.

`reports/phase3/analog_one_shot.json` carried

    "project": "<another operator's home>/AI_IC_design/_c2_adc_run/proj"
    "verdict": "FAIL"

while sitting inside a DIFFERENT project tree. The report was carried forward
from another run and brought its verdict with it, contradicting every per-step
gate that audits the same steps in the tree it now lives in. Nothing looked at
the `project` field.

The stale FAIL is the visible half. The dangerous half is a stale PASS: a report
attesting a clean run of a design that was never built here, in a directory a
reader takes as evidence about this one.

MEASURED over `benchmark-data/` before the checker was written:

    *_one_shot.json found          364
    carrying a `project` field     303
    naming a DIFFERENT tree         61   (20 %)

across sha256, edge_llm_matmul_accel, u_hawaii_adc and others, with both PASS
and FAIL verdicts among them — not one stray file.

WHY NO EXISTING GATE COVERS IT. `agent_report_presence_check` asks whether the
report EXISTS; `agent_report_sha256_attestation_check` asks whether it carries a
SHA256 table. Both are about CONTENT, and a foreign report satisfies both
perfectly — it was a complete, honest report of a different run. Neither asks
the prior question: is this report about this project at all?
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

from _published_corpus import corpus_root, needs_corpus

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "report_belongs_to_project_check.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "report_belongs_to_project_check_probe", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["report_belongs_to_project_check_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _report(project: pathlib.Path, claims: str, verdict: str = "PASS",
            rel: str = "reports/phase3/analog_one_shot.json"):
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"project": claims, "verdict": verdict}),
                 encoding="utf-8")
    return p


def _run(project):
    return _pr.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


# ── the defect ───────────────────────────────────────────────────────────────
def test_a_foreign_project_path_is_a_finding(tmp_path):
    proj = tmp_path / "mine"
    _report(proj, claims="/somewhere/else/theirs", verdict="FAIL")
    findings, stats = M.audit(proj)
    assert stats["foreign"] == 1, stats
    assert findings[0]["claims_project"] == "/somewhere/else/theirs"
    assert findings[0]["verdict"] == "FAIL"


def test_a_foreign_PASS_is_also_a_finding(tmp_path):
    """The dangerous direction. A stale FAIL is noisy; a stale PASS is a clean
    verdict about a design that was never built here."""
    proj = tmp_path / "mine"
    _report(proj, claims="/somewhere/else/theirs", verdict="PASS")
    findings, _ = M.audit(proj)
    assert len(findings) == 1 and findings[0]["verdict"] == "PASS"


def test_the_cli_fails_and_names_both_paths(tmp_path):
    proj = tmp_path / "mine"
    _report(proj, claims="/somewhere/else/theirs")
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "/somewhere/else/theirs" in r.stdout
    assert str(proj) in r.stdout, "the finding does not say where the report sits"


# ── the accept cases ─────────────────────────────────────────────────────────
def test_a_report_naming_its_own_project_passes(tmp_path):
    """Load-bearing: a checker that flagged everything would 'find' all 303
    attributed reports in the corpus and mean nothing."""
    proj = tmp_path / "mine"
    _report(proj, claims=str(proj))
    findings, stats = M.audit(proj)
    assert findings == [] and stats["foreign"] == 0
    assert _run(proj).returncode == 0


def test_a_relative_or_symlinked_spelling_is_not_a_finding(tmp_path):
    """Both sides are resolved, so the same tree spelled differently is the
    same tree. Without this the checker fires on every ordinary run."""
    proj = tmp_path / "mine"
    proj.mkdir(parents=True)
    _report(proj, claims=str(proj / "." / "..") + "/mine")
    findings, _ = M.audit(proj)
    assert findings == [], findings


def test_a_report_with_no_project_field_is_counted_not_failed(tmp_path):
    """A report that never claimed a project is not lying about one.

    Promoting that to a failure is a different and much larger change, so it is
    counted and disclosed instead — and the count is asserted so the case
    cannot be silently reclassified as clean.
    """
    proj = tmp_path / "mine"
    p = proj / "reports" / "phase3" / "analog_one_shot.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
    findings, stats = M.audit(proj)
    assert findings == []
    assert stats["unattributed"] == 1, stats


# ── the denominator, and refusing on an empty one ────────────────────────────
def test_a_tree_with_no_reports_refuses(tmp_path):
    """rc 2, not rc 0. Nothing was examined, so 'no foreign reports' is a
    statement about nothing — the #564 family."""
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS_PASS" in r.stderr


def test_the_denominator_is_stated_and_is_off_the_verdict_line(tmp_path):
    """The count is disclosed, and NOT on the last line.

    `gate_host_independence_check` compares the last non-empty line, and this
    program's count legitimately differs between trees — putting it on the
    verdict line would make an honest disclosure host-dependent (the lesson
    from waveform_artifact_hygiene_check in v1.9.0).
    """
    proj = tmp_path / "mine"
    _report(proj, claims=str(proj))
    out = _run(proj).stdout
    assert "examined 1 runner report(s)" in out, out
    last = [ln for ln in out.splitlines() if ln.strip()][-1]
    assert last.startswith(("PASS", "FAIL")), last
    assert "examined" not in last, last


def test_a_report_outside_a_reports_directory_is_undecidable(tmp_path):
    """This program locates the owning project as the path above `reports/`.
    With no `reports/` in the path it cannot say, and says so rather than
    guessing a root and reporting a finding against it."""
    proj = tmp_path / "mine"
    p = proj / "stray_one_shot.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"project": "/elsewhere"}), encoding="utf-8")
    findings, stats = M.audit(proj)
    assert findings == []
    assert stats["undecidable"] == 1, stats


# ── the corpus, so a parser regression is visible ────────────────────────────
@needs_corpus
def test_the_shape_exists_in_the_corpus():
    """Measured at 61 foreign of 303 attributed when this landed. A change that
    made `audit` always return nothing would pass every test above.

    ITS SUBJECT IS THE PUBLISHED RESULT CELLS, which moved to
    vibeic/benchmark-data. `benchmark-data/` still exists in this checkout — it
    holds the design INPUT — so `root.is_dir()`, the guard that used to stand
    here, is true on a tree that carries not one runner report: the old guard
    could not tell "no foreign report anywhere" from "no report anywhere", and
    reported the second as a defect. `_published_corpus` asks the question the
    denominator actually depends on (is a published CELL readable?) and the
    audit below now runs against the corpus the caller named.
    """
    root = corpus_root()
    findings, stats = M.audit(root)
    assert stats["attributed"] > 0, stats
    assert stats["foreign"] > 0, (
        "no foreign report anywhere in the corpus — either the corpus was "
        "cleaned or the predicate stopped firing; both are worth knowing")
