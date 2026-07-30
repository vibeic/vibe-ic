#!/usr/bin/env python3
"""vibe-ic — the CI step that was retired without a replacement.

`ci.yml` and `gatekeeper-ci.yml` both ran "Validate all JSON + YAML". When
Actions was disabled and `tools/gatekeeper-land.sh` took over, that step was not
carried across, and nothing noticed for two versions — a check that does not
exist is indistinguishable from one that passes.

Measured before writing this: `benchmark/CAPTURE_ROUTING.json` truncated
mid-string, all eight cheap-tier gates PASS. The flow dispatcher's routing table
could be landed unparseable.

Driven against a REAL git repository per test rather than a mocked `git
ls-files`, because the thing most likely to be wrong is the file discovery, and
a mock of it would agree with whatever I assumed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import tracked_json_yaml_parses_check as C  # noqa: E402


def _repo(tmp_path, files: dict, *, track_all=True) -> Path:
    """A real git repo. `files` maps relative path → content."""
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    if track_all and files:
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_an_unparseable_tracked_json_is_caught(tmp_path):
    """THE defect. The real corruption that got through: truncated mid-string."""
    r = _repo(tmp_path, {"a.json": '{"x": 1}',
                         "bad.json": '{"x": "unterminat'})
    rc = C.main(["--root", str(r)])
    assert rc == C.RC_UNPARSEABLE, f"a broken JSON exited {rc}"


def test_an_unparseable_tracked_yaml_is_caught(tmp_path):
    pytest.importorskip("yaml")
    r = _repo(tmp_path, {"ok.yaml": "a: 1\n",
                         "bad.yaml": "a: [1, 2\nb: {{{\n"})
    assert C.main(["--root", str(r)]) == C.RC_UNPARSEABLE


def test_a_clean_tree_passes(tmp_path):
    """…or the test above is met by a gate that always fails."""
    r = _repo(tmp_path, {"a.json": '{"x": 1}', "b.yaml": "k: v\n"})
    assert C.main(["--root", str(r)]) == C.RC_OK


def test_a_scan_that_found_nothing_is_not_a_clean_tree(tmp_path):
    """The shape this gate exists to reject, pointed at itself: zero files
    examined trivially yields zero errors, and that must never read as PASS."""
    r = _repo(tmp_path, {"readme.md": "no config here\n"})
    rc = C.main(["--root", str(r)])
    assert rc == C.RC_CANNOT_CHECK, f"an empty scan reported {rc}"


def test_not_a_git_repository_cannot_be_checked(tmp_path):
    """`git ls-files` failing is not 'the tree is clean'."""
    (tmp_path / "a.json").write_text('{"x": 1}')
    assert C.main(["--root", str(tmp_path)]) == C.RC_CANNOT_CHECK


def test_a_symlink_is_skipped_by_mode_not_parsed(tmp_path, capsys):
    """This repo tracks 160 symlinks, 114 of them named `.json`/`.yaml`.

    A symlink's blob is its TARGET PATH — `../../phase3/stage3/cts/clock_plan.json`
    — so parsing it as JSON fails on a file that is not JSON at all. It has to be
    excluded by git MODE (120000), which is a fact about the object, and never by
    whether it happens to resolve on this machine, which is a fact about the
    machine.
    """
    r = _repo(tmp_path, {"good.json": '{"x": 1}'})
    (r / "dangling.json").symlink_to("nowhere/absent.json")
    (r / "resolving.json").symlink_to("good.json")
    subprocess.run(["git", "add", "dangling.json", "resolving.json"],
                   cwd=r, check=True)

    rc = C.main(["--root", str(r)])
    err = capsys.readouterr().err
    assert rc == C.RC_OK, "a symlink was treated as a parse failure"
    assert "1 JSON" in err, \
        f"symlinks reached the denominator; got: {err.strip()}"


def test_the_verdict_is_identical_in_a_worktree(tmp_path):
    """The property `gate_host_independence_check` exists to enforce, and the one
    the first version of this gate failed.

    It walked the disk. A resolving symlink parses in a working checkout and is
    unreadable in a `git worktree` holding tracked content only, so the same
    commit produced two different verdict lines — decided by run leftovers that
    are not in the commit. Reading the index removes the disk from the question
    entirely, and this pins that.
    """
    r = _repo(tmp_path, {"a.json": '{"x": 1}', "b.yaml": "k: v\n"})
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "seed"], cwd=r, check=True)
    # A symlink whose target exists HERE and will not exist in the worktree,
    # because the target is deliberately left untracked.
    (r / "leftover.json").write_text('{"untracked": true}')
    (r / "points_at_leftover.json").symlink_to("leftover.json")
    subprocess.run(["git", "add", "points_at_leftover.json"], cwd=r, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "link"], cwd=r, check=True)

    wt = tmp_path.parent / (tmp_path.name + "_wt")
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(wt), "HEAD"],
                   cwd=r, check=True)
    try:
        here = C.check(r)
        there = C.check(wt)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=r, check=False)

    assert (here["json_total"], here["yaml_total"]) == \
           (there["json_total"], there["yaml_total"]), \
        f"host-dependent denominator: checkout {here} vs worktree {there}"
    assert here["unparseable"] == there["unparseable"], \
        "host-dependent findings"


def test_missing_pyyaml_is_not_a_pass_on_the_json_half(tmp_path, monkeypatch):
    """228 YAML files going unparsed is a fact about the RUN. Passing on the
    strength of the JSON half would be the gate lying about its own scope."""
    r = _repo(tmp_path, {"a.json": '{"x": 1}', "b.yaml": "k: v\n"})
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def no_yaml(name, *a, **k):
        if name == "yaml":
            raise ImportError("simulated: PyYAML absent")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", no_yaml)
    assert C.main(["--root", str(r)]) == C.RC_CANNOT_CHECK


def test_the_report_names_the_file_and_the_reason(tmp_path, capsys):
    """A gate that says "something is broken" without saying what costs a
    bisect. The parse error carries the line; it must reach the operator."""
    r = _repo(tmp_path, {"broken.json": '{"a": [1, 2,\n'})
    C.main(["--root", str(r)])
    err = capsys.readouterr().err
    assert "broken.json" in err
    assert "line" in err.lower() or "char" in err.lower()


def test_the_json_report_is_machine_readable(tmp_path):
    r = _repo(tmp_path, {"bad.json": "{"})
    out = tmp_path / "rep.json"
    C.main(["--root", str(r), "--json", str(out)])
    rep = json.loads(out.read_text())
    assert rep["program"] == "tracked_json_yaml_parses_check"
    assert len(rep["unparseable"]) == 1



def test_a_crash_is_could_not_check_not_a_finding(tmp_path, monkeypatch, capsys):
    """rc 1 MEANS "a tracked file does not parse". A crash exiting 1 would be
    read as a finding about the tree.

    Not hypothetical: the first version of this gate had a str/bytes mix-up in
    its `git cat-file` call, and the resulting TypeError made the landing gates
    report the commit as carrying unparseable config. The tree was fine.
    """
    r = _repo(tmp_path, {"a.json": '{"x": 1}'})

    def boom(_root):
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(C, "check", boom)
    rc = C.main(["--root", str(r)])
    assert rc == C.RC_CANNOT_CHECK, \
        f"a crash exited {rc}; rc 1 would claim the tree has broken config"
    assert "NOT CHECKED" in capsys.readouterr().err
if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
