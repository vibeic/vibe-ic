"""Q3 — handoff_bundle_check: the COMPLETENESS-CONTRACT gate for a Field
deep-resolution handoff.

A bundle ADMITs only when ALL SEVEN contract items hold:
  (1) root-cause statement per peeled layer (>=1), each naming station/program
  (2) candidate.patch non-empty + applies clean (git apply --check)
  (3) two-depth regression: surface test + deeper-layer test (>=2 files OR
      >=2 functions tied to distinct layers)
  (4) clean-room: two INDEPENDENT 0-residual rounds
  (5) fix_surface_classify verdict = ROOT-CAUSE (PRODUCER), not surface
  (6) chip-AGNOSTIC candidate (source_chip_agnostic_check clean on patched files)
  (7) version-less candidate (patch does NOT bump a .claude-plugin version
      file — the gatekeeper assigns ALL versions at merge)

§4.05 fail-closed: each of the seven missing-one variants → INCOMPLETE naming
the gap; an INCOMPLETE bundle NEVER ADMITs.

The fixtures build a REAL throwaway git repo so `git apply --check` runs for
real, and a REAL candidate patch that fix_surface_classify classifies as
PRODUCER and source_chip_agnostic_check scans for real.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import handoff_bundle_check as H  # noqa: E402


# ── helpers ─────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True, check=True)
    return out.stdout


def _init_repo(tmp_path: Path, target_body: str,
               target_rel: str = "programs/phase3_demo.py") -> Path:
    """A real git repo whose patched file lives under programs/ (so the
    chip-AGNOSTIC scan, which walks repo/{programs,skills,commands}, sees the
    same path the patch targets)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    tgt = repo / target_rel
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text(target_body, encoding="utf-8")
    _git(repo, "add", target_rel)
    _git(repo, "commit", "-q", "-m", "base")
    return repo


# A PRODUCER-shaped, chip-AGNOSTIC source file (def step_route → producer).
_CLEAN_SRC = (
    "def step_route(project, top, pdk, container):\n"
    "    tcl = _build_pnr_tcl(project, top)\n"
    "    return tcl\n"
)
# Same file but carrying a real deny-list token (md905) → chip-specific.
_CHIP_SRC = (
    "def step_route(project, top, pdk, container):\n"
    "    # tuned for md905 board reference\n"
    "    tcl = _build_pnr_tcl(project, top)\n"
    "    return tcl\n"
)


def _make_producer_patch(repo: Path,
                         target_rel: str = "programs/phase3_demo.py") -> str:
    """Edit the producer file, capture the diff, then revert so the patch
    applies clean against HEAD. The diff's enclosing symbol is step_route →
    fix_surface_classify = PRODUCER."""
    tgt = repo / target_rel
    body = tgt.read_text(encoding="utf-8")
    tgt.write_text(
        body.replace("_build_pnr_tcl(project, top)",
                     "_build_pnr_tcl(project, top, fix=True)"),
        encoding="utf-8")
    diff = _git(repo, "diff")
    _git(repo, "checkout", "--", target_rel)   # revert so patch applies clean
    assert diff.strip(), "expected a non-empty diff"
    return diff


def _make_consumer_patch(repo: Path) -> str:
    """A CONSUMER_ONLY patch: a verdict-message edit in a *_check.py file.
    Lives in its own committed file so the diff path is a checker module."""
    rel = "programs/demo_check.py"
    tgt = repo / rel
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text(
        "def _emit_verdict(ok):\n"
        '    msg = "old verdict text"\n'
        "    return msg\n", encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", "add checker")
    tgt.write_text(
        "def _emit_verdict(ok):\n"
        '    msg = "new verdict text"\n'
        "    return msg\n", encoding="utf-8")
    diff = _git(repo, "diff")
    _git(repo, "checkout", "--", rel)
    return diff


def _write_clean_room(p: Path, residual0: bool = True, marker: bool = True,
                      passing: bool = True) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if marker:
        lines.append("=== clean-room independent round ===")
    if residual0:
        lines.append("benchmark complete: 0 residual")
    else:
        lines.append("benchmark complete: residual: 3")
    if passing:
        lines.append("RESULT: PASS")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_bundle(tmp_path: Path, repo: Path, patch_text: str, *,
                  root_causes=None, surface_test=None, deeper_layer_test=None,
                  clean_room=None, candidate_name="candidate.patch",
                  write_tests=True) -> Path:
    """Assemble a complete bundle dir; callers omit/break ONE piece to make a
    missing-one INCOMPLETE variant."""
    b = tmp_path / "bundle"
    b.mkdir(exist_ok=True)
    (b / candidate_name).write_text(patch_text, encoding="utf-8")

    if write_tests:
        tdir = b / "tests"
        tdir.mkdir(exist_ok=True)
        (tdir / "test_surface.py").write_text(
            "# layer: surface\n"
            "def test_symptom_before_after():\n"
            "    assert True\n", encoding="utf-8")
        (tdir / "test_deeper.py").write_text(
            "# layer: deeper-1\n"
            "def test_next_layer_pinned():\n"
            "    assert True\n", encoding="utf-8")

    if root_causes is None:
        root_causes = [
            {"layer": "surface", "statement": "symptom: route DRC short",
             "station": "phase3.step_route", "program": "detailed_route"},
            {"layer": "deeper-1", "statement": "true cause: off-grid via",
             "station": "phase3.streamout", "program": "_gds_grid_snap"},
        ]
    if surface_test is None:
        surface_test = {"file": "tests/test_surface.py",
                        "function": "test_symptom_before_after",
                        "layer": "surface"}
    if deeper_layer_test is None:
        deeper_layer_test = {"file": "tests/test_deeper.py",
                             "function": "test_next_layer_pinned",
                             "layer": "deeper-1"}
    if clean_room is None:
        _write_clean_room(b / "clean_room" / "round1.log")
        _write_clean_room(b / "clean_room" / "round2.log")
        clean_room = {"round1": "clean_room/round1.log",
                      "round2": "clean_room/round2.log"}

    manifest = {
        "bundle_version": 1,
        "root_causes": root_causes,
        "candidate": candidate_name,
        "surface_test": surface_test,
        "deeper_layer_test": deeper_layer_test,
        "clean_room": clean_room,
        "repo_root": str(repo),
    }
    (b / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                     encoding="utf-8")
    return b


def _evaluate(bundle: Path):
    return H.evaluate(bundle_dir=bundle, manifest_path=None)


def _items(rep) -> dict:
    return {it.key: it for it in rep.items}


# ── (0) the complete bundle ADMITs ──────────────────────────────────────────

def test_complete_bundle_admits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    rep = _evaluate(bundle)
    assert rep.verdict == "ADMIT", rep.missing
    assert all(it.ok for it in rep.items)
    # every contract item is present + green
    keys = set(_items(rep))
    assert keys == {
        "root_cause_per_layer", "candidate_applies_clean",
        "two_depth_regression", "clean_room_two_rounds",
        "root_cause_not_surface", "chip_agnostic_candidate",
        "version_less_candidate",
    }


def test_complete_bundle_admits_via_manifest_flag(tmp_path: Path) -> None:
    """--manifest M path resolves the same bundle root from the manifest dir."""
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    rep = H.evaluate(bundle_dir=None, manifest_path=bundle / "manifest.json")
    assert rep.verdict == "ADMIT", rep.missing


# ── (1) missing root-cause-per-layer → INCOMPLETE ───────────────────────────

def test_missing_root_cause_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    # a root_cause entry that omits station/program (the deeper layer is
    # un-attributed) — the Field-hands-over-only-the-symptom failure mode.
    bundle = _build_bundle(tmp_path, repo, patch, root_causes=[
        {"layer": "surface", "statement": "symptom only",
         "station": "phase3.step_route", "program": "detailed_route"},
        {"layer": "deeper-1", "statement": "vague"},  # no station/program
    ])
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["root_cause_per_layer"].ok is False
    assert "station" in " ".join(rep.missing) or "program" in " ".join(rep.missing)


def test_empty_root_causes_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch, root_causes=[])
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["root_cause_per_layer"].ok is False


# ── (2) candidate patch missing / empty / non-applying → INCOMPLETE ─────────

def test_missing_candidate_patch_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    (bundle / "candidate.patch").unlink()  # remove the patch
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["candidate_applies_clean"].ok is False
    assert "missing" in _items(rep)["candidate_applies_clean"].detail.lower()


def test_empty_candidate_patch_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    (bundle / "candidate.patch").write_text("", encoding="utf-8")
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["candidate_applies_clean"].ok is False
    assert "empty" in _items(rep)["candidate_applies_clean"].detail.lower()


def test_non_applying_candidate_patch_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    # corrupt the hunk so it can no longer apply (wrong context lines)
    broken = patch.replace("_build_pnr_tcl(project, top)",
                           "THIS_CONTEXT_DOES_NOT_EXIST(project, top)")
    (bundle / "candidate.patch").write_text(broken, encoding="utf-8")
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["candidate_applies_clean"].ok is False
    assert "does not apply" in _items(rep)["candidate_applies_clean"].detail


# ── (3) single-layer test set → INCOMPLETE ──────────────────────────────────

def test_single_layer_test_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch, write_tests=False,
                           surface_test={"file": "tests/test_only.py",
                                         "function": "test_one",
                                         "layer": "surface"},
                           deeper_layer_test={"file": "tests/test_only.py",
                                              "function": "test_one",
                                              "layer": "surface"})
    # one file, one function, one layer — cannot pin the next layer down
    tdir = bundle / "tests"
    tdir.mkdir(exist_ok=True)
    (tdir / "test_only.py").write_text(
        "# layer: surface\n"
        "def test_one():\n"
        "    assert True\n", encoding="utf-8")
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["two_depth_regression"].ok is False
    assert "layer" in _items(rep)["two_depth_regression"].detail.lower()


def test_no_tests_dir_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    # remove the explicit pair AND the tests dir
    bundle = _build_bundle(tmp_path, repo, patch, write_tests=False,
                           surface_test=False, deeper_layer_test=False)
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["two_depth_regression"].ok is False


def test_two_distinct_files_satisfy_two_depth(tmp_path: Path) -> None:
    """Path B discovery: >=2 distinct test files (no explicit pair) passes."""
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch,
                           surface_test=False, deeper_layer_test=False)
    rep = _evaluate(bundle)
    # tests/ has test_surface.py + test_deeper.py (2 files, 2 layer tags)
    assert _items(rep)["two_depth_regression"].ok is True


# ── (4) clean-room rounds → INCOMPLETE ──────────────────────────────────────

def test_single_clean_room_round_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    # delete round2 → only one round (one round can hide order-dependence)
    (bundle / "clean_room" / "round2.log").unlink()
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["clean_room_two_rounds"].ok is False
    assert "round2" in _items(rep)["clean_room_two_rounds"].detail


def test_nonzero_residual_round_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    # round2 still shows residual → not a clean round
    _write_clean_room(bundle / "clean_room" / "round2.log", residual0=False)
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["clean_room_two_rounds"].ok is False
    assert "residual" in _items(rep)["clean_room_two_rounds"].detail.lower()


def test_same_log_twice_blocks(tmp_path: Path) -> None:
    """Two rounds pointing at the SAME log are not independent."""
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch,
                           clean_room={"round1": "clean_room/round1.log",
                                       "round2": "clean_room/round1.log"})
    _write_clean_room(bundle / "clean_room" / "round1.log")
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    assert _items(rep)["clean_room_two_rounds"].ok is False
    assert "INDEPENDENT" in _items(rep)["clean_room_two_rounds"].detail


# ── (5) surface-classify verdict not ROOT-CAUSE → INCOMPLETE ────────────────

def test_consumer_only_candidate_blocks(tmp_path: Path) -> None:
    """A CONSUMER_ONLY candidate (verdict-message edit) is a SURFACE fix —
    it must NOT ADMIT even though it applies clean and is chip-agnostic."""
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_consumer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    item = _items(rep)["root_cause_not_surface"]
    assert item.ok is False
    assert "CONSUMER_ONLY" in item.detail
    # but it DID apply clean — proving (5) blocks independently of (2)
    assert _items(rep)["candidate_applies_clean"].ok is True


def test_mixed_candidate_blocks_fail_closed(tmp_path: Path) -> None:
    """A MIXED candidate (touches producer AND consumer) cannot be PROVEN a
    root-cause fix → fail-closed INCOMPLETE."""
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    prod = _make_producer_patch(repo)
    cons = _make_consumer_patch(repo)
    mixed = prod + cons  # both surfaces in one patch → MIXED
    bundle = _build_bundle(tmp_path, repo, mixed, candidate_name="candidate.patch")
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    item = _items(rep)["root_cause_not_surface"]
    assert item.ok is False
    assert "MIXED" in item.detail


# ── (6) chip-specific candidate → INCOMPLETE ────────────────────────────────

def test_chip_specific_candidate_blocks(tmp_path: Path) -> None:
    """A candidate whose patched file carries a deny-list token (md905) is
    chip-specific → must NOT ADMIT (even though it is a PRODUCER patch that
    applies clean)."""
    repo = _init_repo(tmp_path, _CHIP_SRC)  # file already carries md905
    patch = _make_producer_patch(repo)       # producer edit on that file
    bundle = _build_bundle(tmp_path, repo, patch)
    rep = _evaluate(bundle)
    assert rep.verdict == "INCOMPLETE"
    item = _items(rep)["chip_agnostic_candidate"]
    assert item.ok is False
    assert "md905" in item.detail.lower()
    # the OTHER gates still pass — proving (6) blocks independently
    assert _items(rep)["candidate_applies_clean"].ok is True
    assert _items(rep)["root_cause_not_surface"].ok is True


# ── error handling / fail-closed structural ─────────────────────────────────

def test_missing_bundle_is_error(tmp_path: Path) -> None:
    rep = H.evaluate(bundle_dir=tmp_path / "nope", manifest_path=None)
    assert rep.verdict == "ERROR"


def test_bundle_without_manifest_is_error(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    rep = H.evaluate(bundle_dir=b, manifest_path=None)
    assert rep.verdict == "ERROR"
    assert "manifest" in " ".join(rep.missing).lower()


def test_incomplete_never_admits_invariant(tmp_path: Path) -> None:
    """§4.05: if ANY single item is missing, the verdict is NEVER ADMIT."""
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    # break clean-room only; everything else is complete
    bundle = _build_bundle(tmp_path, repo, patch)
    (bundle / "clean_room" / "round2.log").unlink()
    rep = _evaluate(bundle)
    assert rep.verdict != "ADMIT"
    assert rep.verdict == "INCOMPLETE"


# ── CLI smoke ───────────────────────────────────────────────────────────────

def test_cli_admit_exit0(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_producer_patch(repo)
    bundle = _build_bundle(tmp_path, repo, patch)
    out_json = tmp_path / "report.json"
    rc = H.main([str(bundle), "--json", str(out_json)])
    assert rc == 0
    rep = json.loads(out_json.read_text())
    assert rep["verdict"] == "ADMIT"
    assert rep["missing"] == []


def test_cli_incomplete_exit1(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, _CLEAN_SRC)
    patch = _make_consumer_patch(repo)  # surface fix
    bundle = _build_bundle(tmp_path, repo, patch)
    rc = H.main([str(bundle)])
    assert rc == 1


def test_cli_error_exit2(tmp_path: Path) -> None:
    rc = H.main([str(tmp_path / "does_not_exist")])
    assert rc == 2
