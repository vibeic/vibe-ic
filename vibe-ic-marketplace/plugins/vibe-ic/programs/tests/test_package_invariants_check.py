"""Tests for package_invariants_check — per-package rules, next to the code.

TWO ARMS, AND THE SECOND ONE IS THE GATE
========================================
The SYNTHETIC arm exercises the engine's refusals on fixtures built here.
The REAL arm runs the checker over this repository's own tree and over verbatim
copies of the packages it constrains, and it is the arm that ENFORCES the
declarations: `test_the_repo_satisfies_every_declared_package_invariant` failing
is a red test and a blocked landing.

A suite whose tests are all fixtures authored alongside the change cannot
distinguish itself from its own absence — measured in this repo, where mutating
a guard killed 10 of 31 hand-typed tests and none of the 4 that read a
checked-in artefact. So the mutation proof here is driven by REAL files.

WHERE THE MUTATIONS COME FROM
=============================
`test_every_declared_invariant_actually_fires` does not carry a hand-written
violation per rule. It takes each declaration's own `counterexample`, plants it
in a REAL file that rule applies to, and requires the checker to fail and to
name that rule. A rule added tomorrow is therefore proved to discriminate by
this test on the day it lands, without anyone editing this file — and a rule
whose counterexample is wrong cannot reach that test at all, because the checker
refuses it as TOOTHLESS first.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from _hostpaths import repo_path

from package_invariants_check import (
    _DECL_BASENAME,
    check,
    derive_id,
    glob_to_re,
    load_package,
    main,
)

#: The ledger's membership, pinned in a THIRD place on purpose.
#:
#: A package's declaration can be deleted (the ledger then refuses, UNDECLARED)
#: and the ledger row can be deleted with it (nothing refuses — both halves of
#: the register are gone). Nothing can make a register unforgeable against an
#: author willing to edit every copy of it. What this constant buys is that the
#: deletion costs a THIRD visible edit, in a test file, which is a different
#: kind of act from dropping a line out of a data file.
LEDGERED_PACKAGES = {
    "tools/ci",
    "vibe-ic-marketplace/plugins/vibe-ic/commands",
    "vibe-ic-marketplace/plugins/vibe-ic/hooks",
    "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/gds_antenna",
    "vibe-ic-marketplace/plugins/vibe-ic/programs:l9",
}

_LEDGER_REL = ("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
               "package_invariants_ledger.json")


# ---------------------------------------------------------------------------
# synthetic fixtures


def _pkg(root: Path, rel_dir: str, body: str, name: str = _DECL_BASENAME) -> Path:
    d = root / rel_dir if rel_dir else root
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return p


def _ledger(root: Path, ids) -> Path:
    p = root / "ledger.json"
    p.write_text(json.dumps(
        {"schema": 1, "packages": [{"package": i} for i in sorted(ids)]}), encoding="utf-8")
    return p


def _one_rule(package_id: str, kind: str, pattern: str, counter: str,
              applies="['*.txt']", extra: str = "") -> str:
    return f"""
    package: {package_id}
    invariants:
      - id: synthetic-rule-under-test
        rule: |
          A synthetic rule, long enough to satisfy the prose floor that a
          declaration must be something a contributor can act on.
        applies_to: {applies}
        {kind}: '{pattern}'
        counterexample: '{counter}'
{extra}"""


def _codes(rep):
    return sorted({f.code for f in rep.findings})


# ---------------------------------------------------------------------------
# the engine: population and refusals


def test_a_root_that_is_not_a_directory_is_not_checked(tmp_path):
    missing = tmp_path / "nowhere"
    rep = check(missing)
    assert rep.rc == 2
    assert "not a directory" in rep.summary["verdict_reason"]


def test_zero_declarations_refuses_rather_than_passing(tmp_path):
    """The defect measured in the upstream this was studied against.

    Their discovery glob yields 0 owners on a moved corpus, the violation list
    is empty, and the script exits 0 announcing that everything conforms. An
    empty population must be NOT_CHECKED, never a pass.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("hello", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, []))
    assert rep.rc == 2
    assert rep.summary["packages"] == 0
    assert "NOT a pass" in rep.summary["verdict_reason"]


def test_the_denominator_is_disclosed_on_a_pass(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 0
    rendered = rep.render()
    assert "files_examined=1" in rendered
    assert "file_rule_pairs=1" in rendered
    assert "packages=1" in rendered


def test_forbid_fires_and_clears(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker"))
    target = tmp_path / "p" / "a.txt"
    ledger = _ledger(tmp_path, ["p"])

    target.write_text("nothing to see", encoding="utf-8")
    assert check(tmp_path, ledger).rc == 0, "clean file must pass"

    target.write_text("x\nTODO-marker here\n", encoding="utf-8")
    rep = check(tmp_path, ledger)
    assert rep.rc == 1
    assert _codes(rep) == ["VIOLATION"]
    detail = rep.findings[0].detail
    assert "a.txt:2" in detail, detail
    assert rep.findings[0].package == "p: synthetic-rule-under-test"


def test_require_fires_and_clears(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "require", "LICENCE-HEADER", "no header here"))
    target = tmp_path / "p" / "a.txt"
    ledger = _ledger(tmp_path, ["p"])

    target.write_text("LICENCE-HEADER\nbody\n", encoding="utf-8")
    assert check(tmp_path, ledger).rc == 0

    target.write_text("body only\n", encoding="utf-8")
    rep = check(tmp_path, ledger)
    assert rep.rc == 1
    assert _codes(rep) == ["VIOLATION"]


def test_a_rule_that_selects_no_file_is_vacuous(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker",
                                  applies="['*.rst']"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 1
    assert _codes(rep) == ["VACUOUS"]
    assert "selects 0 files" in rep.findings[0].detail


def test_a_counterexample_that_does_not_violate_is_toothless(tmp_path):
    """The guard on the guards: a rule nothing has been seen to fail."""
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "innocuous text"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 1
    assert "TOOTHLESS" in _codes(rep)
    assert "has never been seen to reject anything" in rep.findings[0].detail


def test_a_missing_counterexample_is_malformed(tmp_path):
    _pkg(tmp_path, "p", """
    package: p
    invariants:
      - id: synthetic-rule-under-test
        rule: |
          Long enough prose to clear the floor a declaration has to clear.
        applies_to: ['*.txt']
        forbid: 'TODO-marker'
    """)
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 1
    assert _codes(rep) == ["MALFORMED"]
    assert "counterexample` is mandatory" in rep.findings[0].detail


def test_two_packages_claiming_one_file_is_refused(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker"))
    _pkg(tmp_path, "p/inner", _one_rule("p/inner", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "p" / "inner" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p", "p/inner"]))
    assert rep.rc == 1
    assert "OVERLAP" in _codes(rep)
    assert "claimed by 2 packages" in " ".join(f.detail for f in rep.findings)


def test_one_id_may_have_only_one_owner(tmp_path):
    _pkg(tmp_path, "a", _one_rule("a", "forbid", "TODO-marker", "TODO-marker"))
    _pkg(tmp_path, "b", _one_rule("b", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "a" / "x.txt").write_text("clean", encoding="utf-8")
    (tmp_path / "b" / "x.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["a", "b"]))
    assert rep.rc == 1
    assert "DUPLICATE_ID" in _codes(rep)


def test_a_declaration_may_not_claim_another_location(tmp_path):
    _pkg(tmp_path, "p", _one_rule("elsewhere", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 1
    assert "MISPLACED" in _codes(rep)


@pytest.mark.parametrize("body,needle", [
    ("package: p\ninvariants: [\n", "unparsable YAML"),
    ("package: p\ninvariants: []\n", "non-empty list"),
    ("package: p\nowns: ['*']\ninvariants: []\n", "unknown top-level key"),
])
def test_a_malformed_declaration_is_refused_not_ignored(tmp_path, body, needle):
    _pkg(tmp_path, "p", body)
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 1
    assert needle in " ".join(f.detail for f in rep.findings)


def test_declaring_both_predicates_is_refused(tmp_path):
    _pkg(tmp_path, "p", """
    package: p
    invariants:
      - id: synthetic-rule-under-test
        rule: |
          Long enough prose to clear the floor a declaration has to clear.
        applies_to: ['*.txt']
        forbid: 'a'
        require: 'b'
        counterexample: 'a'
    """)
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 1
    assert "exactly one of" in " ".join(f.detail for f in rep.findings)


def test_an_uncompilable_pattern_is_refused(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "([unclosed", "x"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 1
    assert "not a valid regex" in " ".join(f.detail for f in rep.findings)


# ---------------------------------------------------------------------------
# the ledger: a missing declaration must not read as "no constraints"


def test_a_ledgered_package_with_no_declaration_is_refused(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    (tmp_path / "q").mkdir()
    (tmp_path / "q" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p", "q"]))
    assert rep.rc == 1
    assert "UNDECLARED" in _codes(rep)
    assert "does not mean 'no constraints'" in " ".join(f.detail for f in rep.findings)


def test_a_declaration_the_ledger_does_not_record_is_refused(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, []))
    assert rep.rc == 1
    assert "UNLEDGERED" in _codes(rep)


def test_an_absent_ledger_is_refused(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "p" / "a.txt").write_text("clean", encoding="utf-8")
    rep = check(tmp_path, tmp_path / "no-such-ledger.json")
    assert rep.rc == 1
    assert "ledger absent" in " ".join(f.detail for f in rep.findings)


# ---------------------------------------------------------------------------
# scope: the path rule, and the flat-namespace form


def test_a_prefix_package_owns_its_prefix_and_nothing_else(tmp_path):
    _pkg(tmp_path, "flat", _one_rule("flat:l9", "require", "LAYER-TOKEN",
                                     "no token", applies="['*.txt']"),
         name="l9.INVARIANTS.yaml")
    (tmp_path / "flat" / "l9_owned.txt").write_text("LAYER-TOKEN", encoding="utf-8")
    (tmp_path / "flat" / "l8_not_owned.txt").write_text("nothing", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["flat:l9"]))
    assert rep.rc == 0, rep.render()
    assert rep.summary["files_examined"] == 1


def test_a_directory_package_does_not_reach_outside_its_directory(tmp_path):
    _pkg(tmp_path, "p", _one_rule("p", "require", "LAYER-TOKEN", "no token"))
    (tmp_path / "p" / "in.txt").write_text("LAYER-TOKEN", encoding="utf-8")
    (tmp_path / "out.txt").write_text("nothing", encoding="utf-8")
    rep = check(tmp_path, _ledger(tmp_path, ["p"]))
    assert rep.rc == 0, rep.render()
    assert rep.summary["files_examined"] == 1


def test_a_glob_star_does_not_cross_a_directory_separator():
    """`fnmatch` would let `*.py` claim `a/b/c.py` and widen every rule."""
    assert glob_to_re("*.py").search("a.py")
    assert not glob_to_re("*.py").search("sub/a.py")
    assert glob_to_re("**/driver.py").search("x/y/driver.py")
    assert glob_to_re("**/driver.py").search("driver.py")


def test_the_id_is_derived_from_the_declarations_own_path():
    assert derive_id("tools/ci/INVARIANTS.yaml") == ("directory", "tools/ci", "", "tools/ci")
    assert derive_id("a/b/l9.INVARIANTS.yaml") == ("prefix", "a/b", "l9", "a/b:l9")


# ---------------------------------------------------------------------------
# the REAL arm — this is the enforcement


def _repo_root() -> Path:
    return repo_path()


def _materialise(dest: Path) -> Path:
    """Copy the real, tracked bytes of every ledgered package into `dest`.

    Real files, not fixtures: a mutation proof over hand-typed fixtures cannot
    tell the rule from its own absence. Returns the copied ledger's path.
    """
    root = _repo_root()
    ledger_src = root.joinpath(*_LEDGER_REL)
    if not ledger_src.is_file():
        pytest.skip(f"ledger not present in this checkout: {ledger_src}")
    ids = [e["package"] for e in json.loads(ledger_src.read_text())["packages"]]

    specs = []
    for pid in ids:
        directory, sep, prefix = pid.rpartition(":")
        specs.append(f"{directory}/{prefix}*" if sep else pid)
    specs.append("/".join(_LEDGER_REL))

    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--"] + specs,
                         capture_output=True, check=False)
    if out.returncode != 0:
        pytest.skip("not a git worktree; the real-artefact arm needs tracked bytes")
    rels = [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
    if not rels:
        pytest.skip("git listed no tracked files for the ledgered packages")
    for rel in rels:
        src = root / rel
        if not src.is_file():
            continue
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return dest.joinpath(*_LEDGER_REL)


@pytest.fixture(scope="module")
def real_run():
    rep = check(_repo_root(), _repo_root().joinpath(*_LEDGER_REL))
    return rep


def test_the_repo_satisfies_every_declared_package_invariant(real_run):
    """THE GATE. Every rule any package declares holds over this tree."""
    assert real_run.rc == 0, real_run.render()


def test_the_real_run_examined_a_non_empty_population(real_run):
    """A pass over nothing is the failure mode this whole program is about."""
    s = real_run.summary
    assert s["packages"] >= 6, s
    assert s["invariants"] >= 9, s
    assert s["files_examined"] > 0, s
    assert s["file_rule_pairs"] >= s["files_examined"], s


def test_the_ledger_membership_is_pinned_here(real_run):
    assert set(real_run.summary["package_ids"]) == LEDGERED_PACKAGES


def test_deleting_a_real_declaration_is_a_refusal(tmp_path):
    """A missing invariant file must not read as "no constraints"."""
    ledger = _materialise(tmp_path)
    assert check(tmp_path, ledger).rc == 0, "the verbatim copy must be clean first"

    victim = tmp_path / "tools" / "ci" / _DECL_BASENAME
    assert victim.is_file()
    victim.unlink()

    rep = check(tmp_path, ledger)
    assert rep.rc == 1, rep.render()
    undeclared = [f for f in rep.findings if f.code == "UNDECLARED"]
    assert [f.package for f in undeclared] == ["tools/ci"], rep.render()


def test_deleting_the_ledger_row_too_is_survived_only_by_the_pin(tmp_path):
    """The honest residual, asserted rather than claimed.

    Deleting BOTH halves of the register passes the checker — nothing is left
    to notice. What refuses it is `test_the_ledger_membership_is_pinned_here`,
    which is why that constant exists and why this test names the property out
    loud instead of leaving it to a reader of the source.
    """
    ledger = _materialise(tmp_path)
    (tmp_path / "tools" / "ci" / _DECL_BASENAME).unlink()
    doc = json.loads(ledger.read_text())
    doc["packages"] = [e for e in doc["packages"] if e["package"] != "tools/ci"]
    ledger.write_text(json.dumps(doc), encoding="utf-8")

    rep = check(tmp_path, ledger)
    assert rep.rc == 0, rep.render()
    assert set(rep.summary["package_ids"]) != LEDGERED_PACKAGES


def _collect_real_invariants():
    """Parametrisation over the real declarations — never SILENTLY empty.

    A parametrize list that collects nothing removes the test from the run
    without removing it from the file, and a run that never executed reads
    exactly like a run that passed. So every path that yields no cases yields
    ONE case that says why, and that case skips or fails on its own terms.
    """
    from _hostpaths import REPO_ROOT
    if REPO_ROOT is None:
        return [pytest.param(None, "no monorepo root (installed plugin cache?)",
                             id="NOT-COLLECTED-no-repo-root")]
    ledger_src = REPO_ROOT.joinpath(*_LEDGER_REL)
    if not ledger_src.is_file():
        return [pytest.param(None, f"ledger absent: {ledger_src}",
                             id="NOT-COLLECTED-no-ledger")]
    out = []
    findings = []
    for decl in sorted(
            p for p in _tracked(REPO_ROOT)
            if p.rsplit("/", 1)[-1] == _DECL_BASENAME
            or p.rsplit("/", 1)[-1].endswith("." + _DECL_BASENAME)):
        pkg = load_package(REPO_ROOT, decl, findings)
        if pkg is None:
            continue
        for inv in pkg.invariants:
            out.append(pytest.param(pkg, inv, id=inv.id))
    if not out:
        return [pytest.param(None, "no declaration was parsable in this tree",
                             id="NOT-COLLECTED-no-invariants")]
    return out


def _tracked(root: Path):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                         capture_output=True, check=False)
    if out.returncode != 0:
        return []
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


@pytest.mark.parametrize("pkg,inv", _collect_real_invariants())
def test_every_declared_invariant_actually_fires(tmp_path, pkg, inv):
    """Plant each rule's OWN counterexample in a REAL file the rule applies to.

    No hand-written violation per rule, so a rule added later is proved to
    discriminate without this file being touched. A guard never seen to fail
    has not been shown to check anything.
    """
    if pkg is None:
        pytest.skip(f"nothing to mutate: {inv}")
    ledger = _materialise(tmp_path)
    assert check(tmp_path, ledger).rc == 0, "the verbatim copy must be clean first"

    owned = [rel for rel in _relpaths(tmp_path) if pkg.owns(rel)]
    applicable = [
        rel for rel in owned
        if any(r.search(pkg.relative(rel)) for r in inv.applies_re)
        and not any(r.search(pkg.relative(rel)) for r in inv.excl_re)
    ]
    assert applicable, f"{inv.id} applies to nothing in the copy"
    target = tmp_path / applicable[0]

    if inv.kind == "forbid":
        target.write_text(target.read_text(encoding="utf-8", errors="replace")
                          + "\n" + inv.counterexample + "\n", encoding="utf-8")
    else:
        target.write_text(inv.counterexample, encoding="utf-8")

    rep = check(tmp_path, ledger)
    assert rep.rc == 1, rep.render()
    named = [f for f in rep.findings
             if f.code == "VIOLATION" and f.package.endswith(": " + inv.id)]
    assert named, f"{inv.id} did not fire on its own counterexample:\n{rep.render()}"
    assert applicable[0] in named[0].detail


def _relpaths(root: Path):
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# the CLI surface


def test_cli_writes_a_machine_record_and_returns_the_verdict(tmp_path, capsys):
    _pkg(tmp_path, "p", _one_rule("p", "forbid", "TODO-marker", "TODO-marker"))
    (tmp_path / "p" / "a.txt").write_text("TODO-marker\n", encoding="utf-8")
    out = tmp_path / "record.json"
    rc = main([str(tmp_path), "--ledger", str(_ledger(tmp_path, ["p"])),
               "--json", str(out)])
    assert rc == 1
    doc = json.loads(out.read_text())
    assert doc["kind"] == "vibeic.package-invariants"
    assert doc["rc"] == 1
    assert doc["findings"][0]["code"] == "VIOLATION"
    assert "package_invariants: FAIL" in capsys.readouterr().out
