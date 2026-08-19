#!/usr/bin/env python3
"""Tests for package_invariants_check (W7 — per-package invariants).

Three arms, and the reason there are three is that each one alone lies:

  * THE REAL TREE must be green. A gate that is red on arrival gets routed
    around, so this is the only arm that proves the nine shipped rules hold
    over the population they actually claim.
  * THE MUTATION ARM plants each rule's OWN counterexample as the whole body of
    a file that rule applies to, and requires the checker to object. Green on
    the real tree is not evidence of anything by itself: a `forbid` rule that
    matches nothing is byte-identical to a typo. This arm is SELF-EXTENDING —
    a rule added to any declaration tomorrow is proved to discriminate with no
    test edited here.
  * THE SYNTHETIC ARM builds throwaway repositories to reach the states the
    real tree cannot be put into: a deleted declaration, an unregistered one,
    a duplicate id, a shrunken registry, no git index at all.

`REGISTERED_PACKAGES` below is the THIRD pin on the package set, after the
registry JSON and `MIN_REGISTERED_PACKAGES` in the checker. Retiring a package
therefore costs three visible edits, the last of which is in a test.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROG = Path(__file__).resolve().parent.parent / "package_invariants_check.py"
REPO = PROG.resolve().parents[4]
sys.path.insert(0, str(PROG.parent))
import package_invariants_check as M  # noqa: E402

# The exact set, pinned by hand. Not derived from the registry — a pin computed
# from the thing it pins cannot notice that the thing changed.
REGISTERED_PACKAGES = {
    "tools/ci",
    "tools/phase1_engine",
    "vibe-ic-marketplace/plugins/vibe-ic/_shared",
    "vibe-ic-marketplace/plugins/vibe-ic/commands",
    "vibe-ic-marketplace/plugins/vibe-ic/hooks",
    "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/lib",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/gds_antenna",
}


def _run(root: Path, *extra: str):
    proc = subprocess.run(
        [sys.executable, str(PROG), str(root), *extra],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _run_synthetic(root: Path):
    """Synthetic repositories hold one or two packages, so the shrink ratchet
    written for the real tree would fire on every one of them and drown the
    finding under test. The floor itself is exercised by
    `test_the_ratchet_refuses_a_registry_that_shrank`, and
    `test_the_hygiene_wiring_does_not_lower_the_ratchet` pins that the GATE
    never passes this flag."""
    return _run(root, "--min-registered-packages", "0")


def _rm_tracked(root: Path, rel: str):
    """`git rm` refuses a staged-but-uncommitted file, and these repositories
    have no HEAD; unlink + re-add is the same effect on the index."""
    (root / rel).unlink()
    _git(root, "add", "-A")


def _git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def _mini_repo(root: Path, packages: dict[str, str], registry: list[str],
               extra: dict[str, str] | None = None) -> Path:
    """A throwaway repository: declarations, a registry, and nothing else."""
    _git_init(root)
    for pkg, body in packages.items():
        d = root / pkg
        d.mkdir(parents=True, exist_ok=True)
        (d / M.DECLARATION_NAME).write_text(body, encoding="utf-8")
    reg = root / M.REGISTRY_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({"schema": 1, "packages": registry}) + "\n")
    for rel, body in (extra or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(root, "add", "-A")
    return root


def _git_init(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)


def _decl(pkg: str, rid: str, *, forbid=None, require=None, applies=("*.py",),
          counter="BOOM\n", excludes=None) -> str:
    inv: dict = {"id": rid, "rule": "test rule", "applies_to": list(applies),
                 "counterexample": counter}
    if excludes:
        inv["excludes"] = list(excludes)
    if forbid is not None:
        inv["forbid"] = forbid
    if require is not None:
        inv["require"] = require
    return yaml.safe_dump({"package": pkg, "invariants": [inv]}, sort_keys=False)


# --------------------------------------------------------------------------
# ARM 1 — the real tree
# --------------------------------------------------------------------------

def _real_tree_or_skip():
    rc, out = _run(REPO)
    if rc == 2:
        pytest.skip(f"no git index under {REPO}; the synthetic arms still run. {out}")
    return rc, out


def test_the_shipped_declarations_hold_over_the_real_tree():
    rc, out = _real_tree_or_skip()
    assert rc == 0, out
    assert "[PASS]" in out


def test_the_pass_line_discloses_its_denominator():
    """A PASS that does not say how much it looked at is not checkable."""
    rc, out = _real_tree_or_skip()
    assert rc == 0, out
    for field in ("package(s)", "invariant(s)", "owned file(s)",
                  "file-rule pair(s) examined", "tracked"):
        assert field in out, f"{field!r} missing from: {out}"


def test_the_registry_matches_the_hand_pinned_set():
    reg = json.loads((REPO / M.REGISTRY_REL).read_text())
    assert set(reg["packages"]) == REGISTERED_PACKAGES
    assert len(reg["packages"]) == len(set(reg["packages"])), "duplicate row"


def test_the_ratchet_floor_matches_the_registered_set():
    """The floor may not drift below the set it is supposed to hold up."""
    assert M.MIN_REGISTERED_PACKAGES == len(REGISTERED_PACKAGES)


def test_every_registered_package_has_a_tracked_declaration():
    for pkg in REGISTERED_PACKAGES:
        assert (REPO / pkg / M.DECLARATION_NAME).is_file(), pkg


# --------------------------------------------------------------------------
# ARM 2 — self-extending mutation: every shipped rule must reject its own
#         counterexample, planted in a REAL file that rule owns.
#
# This arm deliberately has NO skip condition. It assembles its own throwaway
# repository from files already on disk, so there is no environment in which it
# can quietly report nothing — an arm that can vanish is an arm that eventually
# does, and nine silent skips read exactly like nine passes.
# --------------------------------------------------------------------------

def _shipped_rules():
    out = []
    for pkg in sorted(REGISTERED_PACKAGES):
        doc = yaml.safe_load((REPO / pkg / M.DECLARATION_NAME).read_text())
        for rule in doc["invariants"]:
            out.append((pkg, rule))
    return out


@pytest.mark.parametrize("pkg,rule", _shipped_rules(),
                         ids=[f"{p}:{r['id']}" for p, r in _shipped_rules()])
def test_each_shipped_rule_goes_red_when_a_file_it_owns_is_mutated(
        pkg, rule, tmp_path):
    """Plant the rule's own counterexample as a whole file it applies to.

    Uniform across both polarities: a `forbid` counterexample CONTAINS the
    banned text, and a `require` counterexample LACKS the required text, so
    "the counterexample is the entire file" is a violation either way.

    The subject is a SLICE of the real tree — every declaration, the registry,
    and one real file per rule — assembled in `tmp_path` and `git init`ed, so
    the real checkout is never written to and the slice is green before the
    mutation. Both halves are asserted; the clean half is what makes the red
    half attributable to the mutation and not to the slice.
    """
    root = tmp_path / "subject"
    _git_init(root)
    # Only what this one rule needs: its declaration, the registry, and one
    # real file from its population.
    for other in sorted(REGISTERED_PACKAGES):
        d = root / other
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / other / M.DECLARATION_NAME, d / M.DECLARATION_NAME)
    reg = root / M.REGISTRY_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / M.REGISTRY_REL, reg)

    inc = [M._glob_to_regex(g) for g in rule["applies_to"]]
    exc = [M._glob_to_regex(g) for g in (rule.get("excludes") or [])]
    victim = None
    for cand in sorted((REPO / pkg).rglob("*")):
        if not cand.is_file():
            continue
        sub = cand.relative_to(REPO / pkg).as_posix()
        if sub == M.DECLARATION_NAME:
            continue
        if any(r.match(sub) for r in inc) and not any(r.match(sub) for r in exc):
            victim = sub
            break
    assert victim, f"{rule['id']}: no real file in its population to mutate"

    # Every OTHER package keeps one clean population file so its own rules stay
    # non-vacuous; the whole run must go red for exactly one reason.
    for other_pkg, other_rule in _shipped_rules():
        oinc = [M._glob_to_regex(g) for g in other_rule["applies_to"]]
        oexc = [M._glob_to_regex(g) for g in (other_rule.get("excludes") or [])]
        for cand in sorted((REPO / other_pkg).rglob("*")):
            if not cand.is_file():
                continue
            osub = cand.relative_to(REPO / other_pkg).as_posix()
            if osub == M.DECLARATION_NAME:
                continue
            if any(r.match(osub) for r in oinc) and not any(
                    r.match(osub) for r in oexc):
                dst = root / other_pkg / osub
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy2(cand, dst)
                break

    _git(root, "add", "-A")
    rc_clean, out_clean = _run_synthetic(root)
    assert rc_clean == 0, f"the unmutated slice is not green: {out_clean}"

    (root / pkg / victim).write_text(rule["counterexample"], encoding="utf-8")
    _git(root, "add", "-A")
    rc, out = _run_synthetic(root)
    assert rc == 1, f"{rule['id']} did NOT fire on its own counterexample: {out}"
    assert rule["id"] in out
    assert victim in out


# --------------------------------------------------------------------------
# ARM 3 — synthetic states the real tree cannot be put into
# --------------------------------------------------------------------------

def test_a_violation_is_attributed_to_the_owning_package(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-no-boom", forbid="BOOM")},
        ["pkg/a"],
        {"pkg/a/x.py": "print('BOOM')\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1
    assert "pkg/a: aaa-no-boom" in out and "pkg/a/x.py:1" in out


def test_a_deleted_declaration_is_a_refusal_not_an_absence_of_rules(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-no-boom", forbid="BOOM"),
         "pkg/b": _decl("pkg/b", "bbb-no-boom", forbid="BOOM")},
        ["pkg/a", "pkg/b"],
        {"pkg/a/x.py": "ok\n", "pkg/b/y.py": "ok\n"},
    )
    assert _run_synthetic(root)[0] == 0
    _rm_tracked(root, "pkg/b/INVARIANTS.yaml")
    rc, out = _run_synthetic(root)
    assert rc == 1
    assert "MISSING" in out and "pkg/b" in out


def test_an_unregistered_declaration_is_a_refusal(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-no-boom", forbid="BOOM"),
         "pkg/b": _decl("pkg/b", "bbb-no-boom", forbid="BOOM")},
        ["pkg/a"],
        {"pkg/a/x.py": "ok\n", "pkg/b/y.py": "ok\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1 and "UNREGISTERED" in out and "pkg/b" in out


def test_the_ratchet_refuses_a_registry_that_shrank(tmp_path):
    """Deleting a declaration AND its registry row still does not read clean."""
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-no-boom", forbid="BOOM"),
         "pkg/b": _decl("pkg/b", "bbb-no-boom", forbid="BOOM")},
        ["pkg/a", "pkg/b"],
        {"pkg/a/x.py": "ok\n", "pkg/b/y.py": "ok\n"},
    )
    assert _run(root, "--min-registered-packages", "2")[0] == 0
    _rm_tracked(root, "pkg/b/INVARIANTS.yaml")
    reg = root / M.REGISTRY_REL
    reg.write_text(json.dumps({"schema": 1, "packages": ["pkg/a"]}) + "\n")
    _git(root, "add", "-A")
    rc, out = _run(root, "--min-registered-packages", "2")
    assert rc == 1 and "RATCHET" in out, out


def test_the_hygiene_wiring_does_not_lower_the_ratchet():
    """The override exists for the synthetic arms. If the GATE ever starts
    passing it, the floor is decoration."""
    wiring = (REPO / "tools" / "ci" / "repo_hygiene_gates.sh").read_text()
    line = [l for l in wiring.splitlines()
            if "package_invariants_check.py" in l and not l.lstrip().startswith("#")]
    assert line, "the checker is not wired into the hygiene gate list at all"
    for l in line:
        assert "--min-registered-packages" not in l, l


def test_a_toothless_rule_is_refused(tmp_path):
    """A forbid pattern that cannot match its own counterexample is a typo."""
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-typo", forbid="BOOOM")},
        ["pkg/a"],
        {"pkg/a/x.py": "print('BOOM')\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1 and "TOOTHLESS" in out


def test_a_rule_that_selects_no_file_is_refused_as_vacuous(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-no-boom", forbid="BOOM",
                        applies=("*.rs",))},
        ["pkg/a"],
        {"pkg/a/x.py": "ok\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1 and "VACUOUS" in out


def test_a_star_glob_does_not_reach_into_a_subdirectory(tmp_path):
    """`*.py` must not silently claim files a deeper package owns."""
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-no-boom", forbid="BOOM")},
        ["pkg/a"],
        {"pkg/a/x.py": "ok\n", "pkg/a/deep/y.py": "print('BOOM')\n"},
    )
    assert _run_synthetic(root)[0] == 0
    # ... and `**/` opts back in, so the miss above is scope, not blindness.
    (root / "pkg/a" / M.DECLARATION_NAME).write_text(
        _decl("pkg/a", "aaa-no-boom", forbid="BOOM", applies=("**/*.py",)))
    _git(root, "add", "-A")
    rc, out = _run_synthetic(root)
    assert rc == 1 and "pkg/a/deep/y.py:1" in out


def test_a_nested_package_takes_ownership_from_its_ancestor(tmp_path):
    """Nearest-ancestor: the deeper declaration owns the file, alone."""
    root = _mini_repo(
        tmp_path / "r",
        {"pkg": _decl("pkg", "outer-no-boom", forbid="BOOM",
                      applies=("**/*.py",)),
         "pkg/inner": _decl("pkg/inner", "inner-no-bang", forbid="BANG")},
        ["pkg", "pkg/inner"],
        {"pkg/x.py": "ok\n", "pkg/inner/y.py": "print('BOOM')\n"},
    )
    rc, out = _run(root)
    assert rc == 1, out
    # The outer rule never saw the inner file; the inner rule has no *.py left
    # to judge but its own, so the finding is the inner package's vacuity —
    # not a BOOM the outer rule was silently allowed to miss.
    assert "outer-no-boom" not in out
    assert "inner-no-bang" in out


def test_a_duplicate_id_is_refused(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "shared-id", forbid="BOOM"),
         "pkg/b": _decl("pkg/b", "shared-id", forbid="BOOM")},
        ["pkg/a", "pkg/b"],
        {"pkg/a/x.py": "ok\n", "pkg/b/y.py": "ok\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1 and "already owned by" in out


def test_a_declaration_that_misstates_its_own_directory_is_refused(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/elsewhere", "aaa-no-boom", forbid="BOOM")},
        ["pkg/a"],
        {"pkg/a/x.py": "ok\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1 and "disagrees with its own directory" in out


def test_both_polarities_at_once_is_refused(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-both", forbid="BOOM", require="OK")},
        ["pkg/a"],
        {"pkg/a/x.py": "ok\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1 and "exactly one of" in out


def test_a_require_rule_fires_when_the_pattern_is_absent(tmp_path):
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-needs-header", require=r"(?m)^HEADER",
                        counter="no header here\n")},
        ["pkg/a"],
        {"pkg/a/x.py": "HEADER\nok\n", "pkg/a/y.py": "ok\n"},
    )
    rc, out = _run_synthetic(root)
    assert rc == 1 and "pkg/a/y.py" in out and "required pattern absent" in out
    assert "pkg/a/x.py" not in out


# --- rc 2: could not look is not the same as looked and found nothing ------

def test_no_git_index_is_not_checked_never_pass(tmp_path):
    plain = tmp_path / "plain"
    (plain / "pkg/a").mkdir(parents=True)
    (plain / "pkg/a" / M.DECLARATION_NAME).write_text(
        _decl("pkg/a", "aaa-no-boom", forbid="BOOM"))
    rc, out = _run_synthetic(plain)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_zero_declarations_is_not_checked_never_pass(tmp_path):
    """Their `verify-package-invariants.ts` prints 0 conform and exits 0."""
    root = tmp_path / "r"
    _git_init(root)
    reg = root / M.REGISTRY_REL
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({"schema": 1, "packages": []}) + "\n")
    _git(root, "add", "-A")
    rc, out = _run_synthetic(root)
    assert rc == 2 and "NOT CHECKED" in out


def test_an_unreadable_registry_is_not_checked_never_pass(tmp_path):
    root = tmp_path / "r"
    _git_init(root)
    (root / "pkg/a").mkdir(parents=True)
    (root / "pkg/a" / M.DECLARATION_NAME).write_text(
        _decl("pkg/a", "aaa-no-boom", forbid="BOOM"))
    _git(root, "add", "-A")
    rc, out = _run_synthetic(root)
    assert rc == 2 and "registry unreadable" in out


def test_the_machine_record_carries_the_verdict_and_the_denominator(tmp_path):
    """`--json` is written through the atomic helper (vibe-ic#1082), so a
    reader never sees a half-written record."""
    root = _mini_repo(
        tmp_path / "r",
        {"pkg/a": _decl("pkg/a", "aaa-no-boom", forbid="BOOM")},
        ["pkg/a"],
        {"pkg/a/x.py": "print('BOOM')\n"},
    )
    out_json = tmp_path / "rec.json"
    rc, _ = _run(root, "--min-registered-packages", "0", "--json", str(out_json))
    assert rc == 1
    rec = json.loads(out_json.read_text())
    assert rec["verdict"] == "FAIL"
    assert rec["packages"] == 1 and rec["invariants"] == 1
    assert rec["files_examined"] == 1 and rec["tracked_files"] >= 2
    assert any("aaa-no-boom" in f for f in rec["findings"])

    (root / "pkg/a/x.py").write_text("ok\n")
    _git(root, "add", "-A")
    rc, _ = _run(root, "--min-registered-packages", "0", "--json", str(out_json))
    assert rc == 0
    rec = json.loads(out_json.read_text())
    assert rec["verdict"] == "PASS" and rec["findings"] == []


def test_the_refusal_record_says_not_checked_rather_than_an_empty_pass(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    out_json = tmp_path / "rec.json"
    rc, _ = _run(plain, "--json", str(out_json))
    assert rc == 2
    rec = json.loads(out_json.read_text())
    assert rec["verdict"] == "NOT_CHECKED" and rec["reason"]
    assert "findings" not in rec, "a refusal must not present an empty finding set"


def test_a_broken_git_producer_is_not_reported_as_an_empty_corpus(tmp_path):
    """`git ls-files` failing must not read as 'the corpus is clean'."""
    with pytest.raises(M.Refusal):
        M._tracked_files(tmp_path / "does-not-exist")
