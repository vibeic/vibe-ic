"""ORGANIC #720 — repo hygiene: gitignore root-level scratch Workflow scripts.

Session scratch Workflow/orchestration scripts are created at the REPO ROOT as
`_*.js` (e.g. `_review_backlog_*.js`, `_sweep_workflow.js`, …). They were NOT
gitignored, so a stray `git add` could sweep template/scratch code to github.
Fix: a ROOT-ANCHORED `/_*.js` rule in the repo-root `.gitignore`.

Acceptance (verbatim from the issue):
  - `.gitignore` carries the `/_*.js` rule.
  - `git check-ignore <root>/_anything.js` → ignored.
  - `git check-ignore <subdir>/_registry.js` → NOT ignored (root-anchored).
  - No existing tracked file is newly removed from tracking.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_GUARD = _PROGRAMS / "gitignore_scratch_guard.py"


def _repo_root() -> Path:
    cp = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent))
    if cp.returncode != 0:
        pytest.skip("not in a git repo")
    return Path(cp.stdout.strip())


def _check_ignored(root: Path, rel: str) -> bool:
    """True iff `rel` (relative to repo root) is git-ignored."""
    return subprocess.run(
        ["git", "check-ignore", rel],
        cwd=str(root), capture_output=True, text=True).returncode == 0


def test_gitignore_carries_root_anchored_scratch_rule():
    root = _repo_root()
    gi = root / ".gitignore"
    assert gi.is_file()
    assert "/_*.js" in gi.read_text().splitlines()


def test_end_state_root_scratch_js_is_ignored():
    """END-STATE: a root-level `_*.js` scratch script is ignored."""
    root = _repo_root()
    assert _check_ignored(root, "_review_backlog_600_newest.js")
    assert _check_ignored(root, "_sweep_workflow.js")
    assert _check_ignored(root, "_anything.js")


def test_noleak_subdir_underscore_js_not_ignored():
    """§ root-anchor no-leak: a tracked `_*.js` in a SUBDIR (e.g. the mcp-eda
    devices `_registry.js`) must NOT be matched by the root-anchored rule."""
    root = _repo_root()
    subdir_reg = ("vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices/"
                  "_registry.js")
    if (root / subdir_reg).is_file():
        assert not _check_ignored(root, subdir_reg)
    # a nested scratch-looking name is also not matched by the root anchor
    assert not _check_ignored(root, "some/sub/_helper.js")


def test_noleak_no_tracked_file_removed_by_rule():
    """§ the rule must not newly UN-track any committed file (a tracked file is
    not affected by .gitignore — guard that none of our `_*.js` are tracked at
    root, and the subdir `_registry.js` stays tracked)."""
    root = _repo_root()
    tracked = subprocess.run(["git", "ls-files"], cwd=str(root),
                             capture_output=True, text=True).stdout.splitlines()
    # no tracked file lives at repo root matching _*.js
    assert not [f for f in tracked
                if "/" not in f and f.startswith("_") and f.endswith(".js")]
    # the legitimate subdir _registry.js remains tracked
    assert any(f.endswith("mcp-eda/src/devices/_registry.js") for f in tracked)


def test_end_state_guard_program_passes_on_real_repo(tmp_path):
    """END-STATE via the real program: gitignore_scratch_guard exits 0 and its
    evidence shows the rule present + correctly root-anchored on this repo."""
    out = tmp_path / "ev.json"
    cp = subprocess.run(
        [sys.executable, str(_GUARD), "--json", str(out)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent))
    assert cp.returncode == 0, cp.stderr
    ev = json.loads(out.read_text())
    assert ev["ok"] is True
    assert ev["rule_present"] and ev["root_scratch_ignored"]
    assert ev["subdir_registry_ignored"] is False


def test_end_state_guard_fails_when_rule_absent(tmp_path):
    """END-STATE (defect-artifact fixture): a git repo WITHOUT the /_*.js rule
    makes the guard FAIL (exit 1) — proving the guard really enforces the rule,
    not a trivially-true check."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    (repo / ".gitignore").write_text("*.log\n")          # rule ABSENT
    (repo / "keep.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    cp = subprocess.run([sys.executable, str(_GUARD), "--root", str(repo)],
                        capture_output=True, text=True)
    assert cp.returncode == 1
    assert '"rule_present": false' in cp.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def _mkrepo(root: Path, gitignore: str, plant_subdir: bool = True) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text(gitignore)
    add = [".gitignore"]
    if plant_subdir:
        sub = root / ("vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/"
                      "devices/_registry.js")
        sub.parent.mkdir(parents=True, exist_ok=True)
        sub.write_text("x\n")
        add.append(str(sub.relative_to(root)))
    subprocess.run(["git", "add", "-f", *add], cwd=str(root), check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=str(root), check=True)
    return root


def test_a_scratch_path_in_the_tree_is_REPORTED_behind_an_explicit_flag(tmp_path):
    """Probing a rule proves the rule; listing the tree proves the outcome.

    #720 fixed the extension it happened to meet (`/_*.js`) and this guard
    probed that one rule with one synthetic filename. It reported rc 0 while
    four scratch paths sat untracked-and-unignored in the working tree for
    three to nine days: `scratchpad/`, `scratchpad_pr487_msg.txt`,
    `_gds_closure/`, and `vibe-ic-marketplace/scratch_geom_signoff_tests/`.

    WHY THIS HALF IS NOW BEHIND `--include-worktree`, and why that is not a
    weakening. `git status` untracked output is BY DEFINITION not in the
    commit, and every gate wired into `tools/ci/repo_hygiene_gates.sh` is
    re-run by `gate_host_independence_check` against a fresh worktree at the
    same commit and must give the same verdict line and rc. Wiring this half
    there would make that probe report HOST_DEPENDENT_VERDICT the moment any
    agent left a scratch file in the tree — measured, and it is why the guard
    is wired with the flag OFF in the CI script and ON (report-only) from
    `tools/gatekeeper-land.sh`, where "what is in THIS tree" is the question.

    All four original paths are ignored at origin/main (`.gitignore` 139-143),
    so this population's one measured instance is closed; it reports rather
    than blocks unless `--worktree-blocking` is also given.
    """
    import gitignore_scratch_guard as G

    r = _mkrepo(tmp_path / "r", "/_*.js\n", plant_subdir=False)
    (r / "scratchpad").mkdir()
    (r / "scratchpad" / "note.txt").write_text("x")

    default = G.audit(r)
    assert "unignored_scratch_in_tree" not in default, \
        "the DEFAULT population must be commit-determined only"
    assert default["ok"] is True

    ev = G.audit(r, include_worktree=True)
    assert ev["unignored_scratch_in_tree"], \
        "a scratch directory sitting in the tree was not noticed"
    assert ev["worktree_violations"]
    assert ev["ok"] is True, "worktree findings REPORT; they do not block"

    (r / ".gitignore").write_text("/_*.js\n/scratchpad\n")
    assert not G.audit(r, include_worktree=True)["unignored_scratch_in_tree"]


def test_defect_a_the_anchoring_assertion_can_actually_fire(tmp_path):
    """`subdir_registry_ignored` was a CONSTANT, so the docstring's second
    purpose could not be enforced.

    Plain `git check-ignore` returns 1 for a TRACKED path whatever the rules
    say. `_registry.js` is tracked, so the conjunct was always False and a
    mis-anchored rule passed. Proven with a mutant that plants BOTH the
    anchored and the unanchored rule: `check-ignore --no-index` says the subdir
    file IS captured (rc 0) while the pre-fix guard returned 0 PASS.
    """
    import gitignore_scratch_guard as G

    r = _mkrepo(tmp_path / "mut", "/_*.js\n_*.js\n")
    sub = ("vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices/"
           "_registry.js")
    truth = subprocess.run(["git", "check-ignore", "--no-index", "--", sub],
                           cwd=str(r), capture_output=True, text=True)
    assert truth.returncode == 0, "fixture is wrong: the subdir file is not captured"
    assert subprocess.run(["git", "check-ignore", "--", sub], cwd=str(r),
                          capture_output=True).returncode == 1, \
        "the pre-fix probe would have to change behaviour for this to be moot"

    ev = G.audit(r)
    assert ev["subdir_registry_ignored"] is True
    assert ev["ok"] is False
    assert any("MIS-ANCHORED" in v for v in ev["violations"])


def test_defect_b_cannot_measure_is_rc2_and_never_a_finding(tmp_path):
    """"I could not look" must not be reported as "the rule is missing".

    The old guard's precedence — `A or (B and C)` — made rc 2 unreachable for
    any existing directory, so a plain non-repo exited 1 with
    `rule_present: false`: the repo's own vacuous-pass doctrine inverted.
    """
    nonrepo = tmp_path / "notarepo"
    nonrepo.mkdir()
    cp = subprocess.run([sys.executable, str(_GUARD), "--root", str(nonrepo)],
                        capture_output=True, text=True)
    assert cp.returncode == 2, cp.stdout + cp.stderr
    assert "not a pass" in (cp.stdout + cp.stderr).lower()
    assert "rule_present" not in cp.stdout

    missing = subprocess.run(
        [sys.executable, str(_GUARD), "--root", str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert missing.returncode == 2


def test_the_wired_invocation_is_commit_determined(tmp_path):
    """The exact argv wired into `tools/ci/repo_hygiene_gates.sh` must give the
    same verdict line whatever untracked junk the checkout carries — that is
    the contract `gate_host_independence_check` enforces on that script."""
    r = _mkrepo(tmp_path / "hi", "/_*.js\n")

    def verdict():
        cp = subprocess.run([sys.executable, str(_GUARD), "--root", str(r)],
                            capture_output=True, text=True)
        lines = [x for x in cp.stdout.splitlines() if x.strip()]
        return cp.returncode, lines[-1]

    before = verdict()
    (r / "scratch_agent_notes.txt").write_text("x")
    (r / "scratchpad").mkdir()
    after = verdict()
    assert before == after, (
        "the default population read something that is not in the commit: "
        f"{before} != {after}")


def test_the_ci_script_wires_the_guard_with_the_flag_off():
    """A gate wired somewhere that never executes is the defect moved. Assert
    the wiring exists AND that it does not carry the host-dependent flag."""
    root = _repo_root()
    script = (root / "tools" / "ci" / "repo_hygiene_gates.sh").read_text()
    wired = [ln for ln in script.splitlines()
             if "gitignore_scratch_guard.py" in ln and ln.lstrip().startswith("run")]
    assert len(wired) == 1, wired
    assert "--include-worktree" not in wired[0]

    land = (root / "tools" / "gatekeeper-land.sh").read_text()
    assert "gitignore_scratch_guard.py" in land
    assert "--include-worktree" in land
