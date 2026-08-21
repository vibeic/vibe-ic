"""Two PRs carrying the same filename are two measurements (vibe-ic#1468).

The map in #1468 was built by dropping every PR's new program into ONE tree and
running the gate once. Four filenames are added by more than one open PR, so the
later drop overwrote the earlier one and five PRs were told they had nothing to
convert when in fact they each carry a site. `test_two_prs_same_filename_both_
reported` is that defect, in miniature: it is red against any implementation
that keys a shared tree by filename, and green only against one that scans per
(file, PR).

The rest is the refusal contract. A gate that is absent, a PR that could not be
read, and a PR that is clean must produce three DIFFERENT answers -- rc 2, rc 2
with the sites named as a floor, and rc 0 -- because the whole point of the
instrument is that a number nobody could measure is not a zero.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _plugin_tree import plugin_path

TOOL = plugin_path("programs", "atomic_write_pr_attribution.py")
#: The path a PR tree carries its programs at -- the fixture repos below are
#: built with this shape because that is what the tool has to recognise.
PROGRAMS_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs"
REAL_GATE = plugin_path("programs", "atomic_artifact_write_check.py")

#: Stands in for the gate when this checkout does not have it -- it arrives in
#: vibe-ic#1110 and is not on main, so on main this file would otherwise test
#: nothing. It is NOT authoritative: the rule's own test is #1110's
#: `test_issue1082_atomic_artefact_naming`. It is safe here because the fixture
#: programs below are written so the crude rule and the real rule return the
#: same verdict on them -- an offender reaches its `--json` destination through
#: `.write_text`, and a converted one has no `.write_text` at all, so no
#: difference between the two rules can move an assertion.
STAND_IN_GATE = '''\
import ast
def scan_program(path):
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError):
        return []
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("write_text", "write_bytes")):
            out.append({"line": node.lineno, "form": ".%s(...)" % node.func.attr})
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "open" and len(node.args) >= 2
              and isinstance(node.args[1], ast.Constant)
              and "w" in str(node.args[1].value)):
            out.append({"line": node.lineno,
                        "form": "open(..., %r)" % node.args[1].value})
    return out
'''

OFFENDER = '''\
#!/usr/bin/env python3
"""fixture program: writes its declared report destination non-atomically."""
import argparse, json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()
    rep = {"ok": True}
{padding}
    from pathlib import Path
    Path(args.json_out).write_text(json.dumps(rep) + "\\n")
    return 0
'''

CONVERTED = '''\
#!/usr/bin/env python3
"""fixture program: same report, written whole or not at all."""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()
    rep = {"ok": True}
    from _atomic_artefact import write_json
    write_json(args.json_out, rep)
    return 0
'''


def offender(padding_lines: int = 0) -> str:
    """The offender with its write pushed to a chosen line number.

    Line number is the whole point of the map, so the fixtures differ in it.
    """
    pad = "\n".join("    # pad" for _ in range(padding_lines)) if padding_lines else ""
    # str.replace, not str.format: the fixture body contains dict braces.
    return OFFENDER.replace("{padding}\n", pad + "\n" if pad else "")


def write_line_of(src: str) -> int:
    for i, line in enumerate(src.splitlines(), start=1):
        if ".write_text(" in line:
            return i
    raise AssertionError("fixture has no .write_text")


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# --------------------------------------------------------------------------
# fixture repository
# --------------------------------------------------------------------------
def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                       text=True, timeout=45)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a main branch and a real programs dir.

    The gate is committed on main because the tool loads it from the WORKING
    checkout, not from a PR head -- it is the instrument, not the subject.
    """
    r = tmp_path / "repo"
    (r / PROGRAMS_REL).mkdir(parents=True)
    git(r, "init", "--quiet", "-b", "main")
    git(r, "config", "user.email", "t@example.invalid")
    git(r, "config", "user.name", "t")

    gate_src = REAL_GATE.read_text() if REAL_GATE.is_file() else STAND_IN_GATE
    (r / PROGRAMS_REL / "atomic_artifact_write_check.py").write_text(gate_src)
    (r / PROGRAMS_REL / "_atomic_artefact_residual.json").write_text(
        json.dumps({"offenders": ["already_in_the_residual.py"]}) + "\n")
    (r / PROGRAMS_REL / "already_in_the_residual.py").write_text(offender())
    git(r, "add", "-A")
    git(r, "commit", "--quiet", "-m", "base")
    git(r, "branch", "origin/main")          # the tool's default --main-ref
    return r


def add_pr(repo: Path, pr: int, filename: str, source: str,
           cache: Path, status: str = "added") -> None:
    """Commit `source` as `filename` on the local ref the tool reads for `pr`."""
    git(repo, "checkout", "--quiet", "-B", f"pr{pr}", "main")
    (repo / PROGRAMS_REL / filename).write_text(source)
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", f"pr{pr}")
    git(repo, "checkout", "--quiet", "main")
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"{pr}.tsv").write_text(f"{status}\t{PROGRAMS_REL}/{filename}\n")


def run(repo: Path, prs, cache: Path, *extra):
    # --programs-dir is explicit: the tool defaults to its OWN directory, and
    # that is the live plugin tree, not this fixture.
    argv = [sys.executable, str(TOOL), "--repo", str(repo), "--offline",
            "--programs-dir", str(repo / PROGRAMS_REL),
            "--cache-dir", str(cache)]
    for p in prs:
        argv += ["--pr", str(p)]
    argv += list(extra)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


# --------------------------------------------------------------------------
# the two arms
# --------------------------------------------------------------------------
def test_red_a_pr_carrying_a_non_atomic_write_is_named(repo, tmp_path):
    cache = tmp_path / "cache"
    src = offender()
    add_pr(repo, 4242, "fixture_report_gen.py", src, cache)

    r = run(repo, [4242], cache)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"fixture_report_gen.py:{write_line_of(src)}" in r.stdout
    assert "#4242" in r.stdout
    # the md5 that makes this arm and the green arm provably the same tree
    assert md5(src) == md5((repo / PROGRAMS_REL / "already_in_the_residual.py")
                           .read_text())


def test_green_the_converted_form_is_not_named(repo, tmp_path):
    cache = tmp_path / "cache"
    add_pr(repo, 4242, "fixture_report_gen.py", CONVERTED, cache)

    r = run(repo, [4242], cache)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "fixture_report_gen.py" not in r.stdout


def test_the_two_arms_differ_only_in_the_programs_bytes(repo, tmp_path):
    """Same repo, same tool, same PR number -- only the file's bytes change."""
    cache = tmp_path / "cache"
    red_src, green_src = offender(), CONVERTED
    assert md5(red_src) != md5(green_src)

    add_pr(repo, 4242, "fixture_report_gen.py", red_src, cache)
    red = run(repo, [4242], cache)
    add_pr(repo, 4242, "fixture_report_gen.py", green_src, cache)
    green = run(repo, [4242], cache)

    assert (red.returncode, green.returncode) == (1, 0), \
        f"red={red.returncode} green={green.returncode}\n{red.stdout}{green.stdout}"


# --------------------------------------------------------------------------
# the defect this instrument exists to remove
# --------------------------------------------------------------------------
def test_two_prs_same_filename_both_reported(repo, tmp_path):
    """#1468's map lost one of these. Per-(file, PR) scanning keeps both."""
    cache = tmp_path / "cache"
    early, late = offender(padding_lines=0), offender(padding_lines=6)
    early_line, late_line = write_line_of(early), write_line_of(late)
    assert early_line != late_line, "the fixtures must differ in line number"

    add_pr(repo, 1145, "artefact_like_ledger.py", early, cache)
    add_pr(repo, 1165, "artefact_like_ledger.py", late, cache)

    r = run(repo, [1145, 1165], cache)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"artefact_like_ledger.py:{early_line}" in r.stdout
    assert f"artefact_like_ledger.py:{late_line}" in r.stdout
    assert "#1145" in r.stdout and "#1165" in r.stdout


def test_json_report_records_both_pr_owners(repo, tmp_path):
    cache = tmp_path / "cache"
    add_pr(repo, 1145, "artefact_like_ledger.py", offender(0), cache)
    add_pr(repo, 1165, "artefact_like_ledger.py", offender(6), cache)
    out = tmp_path / "out.json"

    r = run(repo, [1145, 1165], cache, "--json", str(out))
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads(out.read_text())
    assert rep["complete"] is True
    assert rep["attributed_file_count"] == 1
    assert rep["attributed_pr_count"] == 2
    assert {s["pr"] for s in rep["attributed_sites"]} == {1145, 1165}


# --------------------------------------------------------------------------
# discrimination: whose debt is it
# --------------------------------------------------------------------------
def test_a_name_already_in_the_residual_is_not_billed_to_the_pr(repo, tmp_path):
    cache = tmp_path / "cache"
    add_pr(repo, 7001, "already_in_the_residual.py", offender(3), cache,
           status="modified")

    r = run(repo, [7001], cache)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already_in_the_residual.py" not in r.stdout


def test_a_file_main_already_offends_is_reported_but_not_attributed(repo, tmp_path):
    """main writes it non-atomically already; the PR that edits it did not."""
    cache = tmp_path / "cache"
    git(repo, "checkout", "--quiet", "main")
    (repo / PROGRAMS_REL / "old_offender.py").write_text(offender())
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "main gains an offender")
    git(repo, "branch", "--quiet", "-f", "origin/main", "main")
    add_pr(repo, 7002, "old_offender.py", offender(5), cache, status="modified")

    r = run(repo, [7002], cache)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "not attributed" in r.stdout
    assert "old_offender.py" in r.stdout


# --------------------------------------------------------------------------
# the refusals
# --------------------------------------------------------------------------
def test_absent_gate_is_not_checked_not_a_zero(repo, tmp_path):
    cache = tmp_path / "cache"
    add_pr(repo, 4242, "fixture_report_gen.py", offender(), cache)
    (repo / PROGRAMS_REL / "atomic_artifact_write_check.py").unlink()

    r = run(repo, [4242], cache)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT CHECKED" in r.stderr
    assert "atomic_artifact_write_check.py" in r.stderr
    assert "[PASS]" not in r.stdout


def test_absent_baseline_is_not_checked(repo, tmp_path):
    cache = tmp_path / "cache"
    add_pr(repo, 4242, "fixture_report_gen.py", offender(), cache)
    (repo / PROGRAMS_REL / "_atomic_artefact_residual.json").unlink()

    r = run(repo, [4242], cache)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "_atomic_artefact_residual.json" in r.stderr


def test_an_unreadable_pr_makes_the_count_a_floor(repo, tmp_path):
    """One PR readable and offending, one not readable at all."""
    cache = tmp_path / "cache"
    add_pr(repo, 4242, "fixture_report_gen.py", offender(), cache)
    # 9999 has no cached file list and --offline forbids asking gh
    r = run(repo, [4242, 9999], cache)

    assert r.returncode == 2, r.stdout + r.stderr
    assert "floor" in r.stdout.lower() or "FLOOR" in r.stdout
    assert "9999" in r.stderr
    # the site it DID find is still named -- a floor is not a blank
    assert "fixture_report_gen.py" in r.stdout


def test_a_pr_whose_head_ref_is_missing_is_a_floor_not_a_clean_pr(repo, tmp_path):
    cache = tmp_path / "cache"
    add_pr(repo, 4242, "fixture_report_gen.py", offender(), cache)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "8888.tsv").write_text(f"added\t{PROGRAMS_REL}/never_committed.py\n")

    r = run(repo, [4242, 8888], cache)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "8888" in r.stderr and "never_committed.py" in r.stderr


def test_a_clean_pr_and_an_unreadable_pr_do_not_encode_the_same(repo, tmp_path):
    cache = tmp_path / "cache"
    add_pr(repo, 4242, "fixture_report_gen.py", CONVERTED, cache)
    clean = run(repo, [4242], cache)
    unreadable = run(repo, [4242, 9999], cache)

    assert clean.returncode == 0
    assert unreadable.returncode == 2
    assert clean.returncode != unreadable.returncode


# --------------------------------------------------------------------------
# scope
# --------------------------------------------------------------------------
def test_nested_paths_are_out_of_scope_because_the_gate_globs_one_level(
        repo, tmp_path):
    cache = tmp_path / "cache"
    git(repo, "checkout", "--quiet", "-B", "pr7003", "main")
    (repo / PROGRAMS_REL / "tests").mkdir(parents=True, exist_ok=True)
    (repo / PROGRAMS_REL / "tests" / "helper_gen.py").write_text(offender())
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "pr7003")
    git(repo, "checkout", "--quiet", "main")
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "7003.tsv").write_text(
        f"added\t{PROGRAMS_REL}/tests/helper_gen.py\n")

    r = run(repo, [7003], cache)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "helper_gen.py" not in r.stdout


def test_which_gate_ran_is_stated_so_a_stand_in_run_is_not_mistaken():
    """A skip that looks like a pass is the failure mode this repo removes."""
    if REAL_GATE.is_file():
        assert "scan_program" in REAL_GATE.read_text()
    else:
        pytest.skip(
            f"NOT CHECKED against the real rule: {REAL_GATE} is absent on this "
            "tree (it arrives in vibe-ic#1110). Every other test in this file "
            "ran against the stand-in scanner and proves the TOOL, not the rule.")
