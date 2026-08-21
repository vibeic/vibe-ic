"""W7 — the rule lives next to the code it binds (package_invariants_check).

Two halves, and the second is the one that matters.

CORPUS SWEEP: the shipped tree passes, with zero findings, over every enrolled
package. That is the positive control — a rule that fired on everything could
not survive it.

DISCRIMINATION: each finding code is driven to FAIL from a synthetic repo built
in tmp_path. VIOLATION, MISSING_FILE, EMPTY, UNENROLLED, STALE_ENROLLMENT and
NON_DISCRIMINATING each get their own test, because each one is a different way
this design could rot into decoration, and a code nobody has watched fire has
not been shown to check anything.

MISSING_FILE and EMPTY carry the whole weight of moving rules out of the centre:
deleting a package's invariant file, or emptying it, must NEVER read as "this
package has no constraints".
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import package_invariants_check as G  # noqa: E402

_REPO = Path(__file__).resolve().parents[5]
_PROGRAMS = Path(__file__).resolve().parent.parent

# The floor is the second memory that makes un-enrollment loud. Shrinking
# programs/package_invariants_enrolled.json alone is not enough to get a package
# out of the gate; this number has to be lowered too, in a different file, in
# the same change. Raise it when packages are added. Lower it only when a
# package is genuinely deleted, and say so in the commit.
_ENROLLMENT_FLOOR = 6


# ---------------------------------------------------------------- corpus sweep
def test_shipped_tree_passes():
    res = G.check(_REPO, _PROGRAMS)
    assert res["findings"] == [], res["findings"]
    assert res["verdict"] == "PASS"


def test_enrollment_floor():
    enrolled = G.load_enrollment(_PROGRAMS)
    assert len(enrolled) >= _ENROLLMENT_FLOOR, (
        f"enrollment shrank to {len(enrolled)}; a package may only leave the "
        f"gate when its directory is genuinely gone, and lowering this floor "
        f"is the visible half of that")
    assert len(enrolled) == len(set(enrolled)), "duplicate enrollment entry"


def test_every_enrolled_package_exists_and_declares_something():
    for pkg in G.load_enrollment(_PROGRAMS):
        d = _REPO / pkg
        assert d.is_dir(), f"enrolled package {pkg} is not a directory"
        f = d / G.INVARIANTS_FILENAME
        assert f.is_file(), f"{pkg} carries no {G.INVARIANTS_FILENAME}"
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["invariants"], f"{pkg} declares zero invariants"


def test_every_shipped_rule_rejects_every_counterexample_it_declares():
    """The negative control, stated as its own assertion rather than inferred
    from the overall PASS. A rule with more than one clause declares one
    counterexample per clause, and every one of them is driven here."""
    rules = counters = 0
    for pkg in G.load_enrollment(_PROGRAMS):
        doc = json.loads((_REPO / pkg / G.INVARIANTS_FILENAME)
                         .read_text(encoding="utf-8"))
        for inv in doc["invariants"]:
            rules += 1
            for ce in G.counterexamples(inv):
                hits = G.evaluate_rule(inv["rule"],
                                       G.counterexample_entries(ce))
                assert hits, (f"{pkg}:{inv['id']} — counterexample "
                              f"{ce['path']} ({ce.get('proves', '?')}) does "
                              f"not violate the rule it is supposed to violate")
                counters += 1
    assert rules >= 15, f"only {rules} rules swept"
    assert counters >= 25, f"only {counters} counterexamples swept"


# ------------------------------------------------------------ synthetic repo
def _mk_repo(tmp_path, packages, files=None):
    """A repo with a programs/ dir holding the enrollment, plus packages."""
    progs = tmp_path / "programs"
    progs.mkdir()
    (progs / G.ENROLLMENT_FILENAME).write_text(json.dumps(
        {"schema": 1, "kind": "vibeic.package-invariants-enrollment",
         "packages": sorted(packages)}) + "\n")
    for rel, content in (files or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path, progs


_GOOD_DOC = {
    "schema": 1,
    "package": "pkg",
    "invariants": [{
        "id": "pkg.no-todo",
        "statement": "No source file may carry a TODO.",
        "why": "because.",
        "rule": {"kind": "forbid_regex", "include": ["*.py"], "regex": "TODO"},
        "counterexample": {"path": "a.py", "content": "# TODO later\n"},
    }],
}


def _codes(res):
    return sorted({f["code"] for f in res["findings"]})


def test_clean_synthetic_package_passes(tmp_path):
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(_GOOD_DOC),
        "pkg/a.py": "x = 1\n"})
    assert G.check(repo, progs)["findings"] == []


def test_violation_fails(tmp_path):
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(_GOOD_DOC),
        "pkg/a.py": "x = 1  # TODO fix\n"})
    res = G.check(repo, progs)
    assert _codes(res) == ["VIOLATION"], res["findings"]
    assert "a.py" in res["findings"][0]["detail"]


def test_missing_invariants_file_fails(tmp_path):
    """DELETING the file must not read as 'no constraints'."""
    repo, progs = _mk_repo(tmp_path, ["pkg"], {"pkg/a.py": "x = 1\n"})
    res = G.check(repo, progs)
    assert _codes(res) == ["MISSING_FILE"], res["findings"]


def test_empty_invariants_file_fails(tmp_path):
    """An EMPTY file must not read as 'no constraints' either."""
    empty = dict(_GOOD_DOC, invariants=[])
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(empty), "pkg/a.py": "x = 1\n"})
    assert _codes(G.check(repo, progs)) == ["EMPTY"]


def test_unenrolled_invariants_file_fails(tmp_path):
    """A file in a package nobody enrolled is a file nobody would miss."""
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(_GOOD_DOC),
        "pkg/a.py": "x = 1\n",
        "other/INVARIANTS.json": json.dumps(dict(_GOOD_DOC, package="other")),
    })
    res = G.check(repo, progs)
    assert _codes(res) == ["UNENROLLED"], res["findings"]
    assert "other" in res["findings"][0]["package"]


def test_stale_enrollment_fails(tmp_path):
    repo, progs = _mk_repo(tmp_path, ["pkg", "deleted_pkg"], {
        "pkg/INVARIANTS.json": json.dumps(_GOOD_DOC), "pkg/a.py": "x = 1\n"})
    assert _codes(G.check(repo, progs)) == ["STALE_ENROLLMENT"]


def test_non_discriminating_rule_fails(tmp_path):
    """A rule whose counterexample does not violate it checks nothing."""
    doc = json.loads(json.dumps(_GOOD_DOC))
    doc["invariants"][0]["counterexample"] = {"path": "a.py",
                                              "content": "x = 1\n"}
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(doc), "pkg/a.py": "x = 1\n"})
    res = G.check(repo, progs)
    assert _codes(res) == ["NON_DISCRIMINATING"], res["findings"]


def test_schema_errors_fail(tmp_path):
    doc = json.loads(json.dumps(_GOOD_DOC))
    del doc["invariants"][0]["why"]
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(doc), "pkg/a.py": "x = 1\n"})
    assert _codes(G.check(repo, progs)) == ["SCHEMA"]


def test_package_field_must_name_itself(tmp_path):
    doc = json.loads(json.dumps(_GOOD_DOC))
    doc["package"] = "somewhere/else"
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(doc), "pkg/a.py": "x = 1\n"})
    assert _codes(G.check(repo, progs)) == ["SCHEMA"]


# --------------------------------------------------------------- rule engine
def _e(path, content="", is_dir=False):
    return [G.Entry(path, is_dir, content=content)]


def test_glob_star_does_not_cross_slash():
    assert G.glob_match("*.md", "a.md")
    assert not G.glob_match("*.md", "sub/a.md")
    assert G.glob_match("**/*.md", "sub/deep/a.md")
    assert G.glob_match("*/SKILL.md", "drc-fix/SKILL.md")
    assert not G.glob_match("*/SKILL.md", "a/b/SKILL.md")


def test_forbid_regex_both_directions():
    rule = {"kind": "forbid_regex", "include": ["*.py"], "regex": "TODO"}
    assert G.evaluate_rule(rule, _e("a.py", "# TODO\n"))
    assert not G.evaluate_rule(rule, _e("a.py", "ok\n"))
    assert not G.evaluate_rule(rule, _e("a.txt", "# TODO\n")), "include ignored"


def test_forbid_regex_exclude_is_honoured():
    rule = {"kind": "forbid_regex", "include": ["*.py"],
            "exclude": ["test_*.py"], "regex": "TODO"}
    assert not G.evaluate_rule(rule, _e("test_a.py", "# TODO\n"))
    assert G.evaluate_rule(rule, _e("a.py", "# TODO\n"))


def test_require_regex_both_directions():
    rule = {"kind": "require_regex", "include": ["*.md"], "regex": "\\A---\\n"}
    assert G.evaluate_rule(rule, _e("a.md", "# title\n"))
    assert not G.evaluate_rule(rule, _e("a.md", "---\nname: a\n"))


def test_require_companion_both_directions():
    rule = {"kind": "require_companion", "for_each": ["*"],
            "for_each_kind": "dir", "companion": "{path}/SKILL.md"}
    assert G.evaluate_rule(rule, _e("s", is_dir=True))
    entries = [G.Entry("s", True), G.Entry("s/SKILL.md", False, content="x")]
    assert not G.evaluate_rule(rule, entries)


def test_forbid_path_both_directions():
    rule = {"kind": "forbid_path", "glob": ["**/*.v"]}
    assert G.evaluate_rule(rule, _e("crypto/aes/aes.v", "module m; endmodule"))
    assert not G.evaluate_rule(rule, _e("crypto/aes/manifest.yaml", "a: b"))


def test_unknown_rule_kind_is_an_error_not_a_pass():
    try:
        G.evaluate_rule({"kind": "vibes"}, _e("a.py", "x"))
    except ValueError as exc:
        assert "vibes" in str(exc)
    else:
        raise AssertionError("an unknown rule kind must not evaluate clean")


# ------------------------------------------------------------------ cli / read
def test_main_exit_zero_on_shipped_tree(capsys):
    rc = G.main(["--repo-root", str(_REPO), "--programs-dir", str(_PROGRAMS)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert out.startswith("PASS:"), out


def test_touched_renders_the_rules_that_bind_the_edit():
    text = G.render_touched(
        _REPO, _PROGRAMS,
        ["vibe-ic-marketplace/plugins/vibe-ic/commands/vibe-ic-phase1.md"])
    assert "commands.command-declares-a-description" in text
    assert G.render_touched(_REPO, _PROGRAMS, ["README.md"]) == ""


def test_a_list_counterexample_is_checked_entry_by_entry(tmp_path):
    """One good counterexample must not cover for a bad one beside it."""
    doc = json.loads(json.dumps(_GOOD_DOC))
    doc["invariants"][0]["counterexample"] = [
        {"path": "a.py", "proves": "a TODO is caught", "content": "# TODO\n"},
        {"path": "a.py", "proves": "nothing", "content": "x = 1\n"},
    ]
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(doc), "pkg/a.py": "x = 1\n"})
    res = G.check(repo, progs)
    assert _codes(res) == ["NON_DISCRIMINATING"], res["findings"]
    assert "nothing" in res["findings"][0]["detail"]


def test_empty_counterexample_list_is_a_schema_error(tmp_path):
    doc = json.loads(json.dumps(_GOOD_DOC))
    doc["invariants"][0]["counterexample"] = []
    repo, progs = _mk_repo(tmp_path, ["pkg"], {
        "pkg/INVARIANTS.json": json.dumps(doc), "pkg/a.py": "x = 1\n"})
    assert _codes(G.check(repo, progs)) == ["SCHEMA"]
