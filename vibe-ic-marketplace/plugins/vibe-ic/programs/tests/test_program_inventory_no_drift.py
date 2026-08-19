#!/usr/bin/env python3
"""Drift guard for every STATED count of the plugin's program corpus.

The MCP tool count has had a generator and a drift test since the website
claimed 48 tools for a server that registered 47. The program count had
neither, and drifted by 261 — `917` was a true measurement of `programs/*.py`
on 2026-07-20 and was still being printed in two READMEs, eight occurrences,
long after the tree passed 1,100.

This file is the program-corpus half of that guard. It fails when:

  * `PROGRAM_INVENTORY.json` no longer matches the filesystem (someone added a
    program and did not regenerate), or
  * any registered doc line states a number the filesystem does not yield
    (someone hand-edited a count), or
  * a registered site's pattern stops matching (the guard went blind — a
    silently-unmatched pattern reports PASS forever, so it is a FAILURE here).

Remedy for the first: `python3 programs/gen_program_inventory.py`.
Remedy for the second: fix the doc line the failure names.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GEN = PROGRAMS / "gen_program_inventory.py"
INV = PROGRAMS / "PROGRAM_INVENTORY.json"


def _gen():
    spec = importlib.util.spec_from_file_location("gen_program_inventory", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _gen()


@pytest.fixture(scope="module")
def live(gen):
    """`discover()` ast-parses every program to resolve `programs_catalogued`.
    Once per module, not once per test."""
    return gen.discover()


def test_committed_inventory_matches_filesystem(live) -> None:
    committed = json.loads(INV.read_text())
    assert committed["counts"] == live["counts"], (
        "PROGRAM_INVENTORY.json is stale vs the tree. Re-run "
        "`python3 programs/gen_program_inventory.py`. "
        f"committed={committed['counts']} filesystem={live['counts']}")


def test_every_count_states_what_it_counts(live) -> None:
    """A number without its population is how the drift hid — see the module
    docstring of the generator. Every key must carry a `counts` sentence."""
    missing = sorted(set(live["counts"]) - set(live["definitions"]))
    assert not missing, f"counts with no stated population: {missing}"
    for key, text in live["definitions"].items():
        assert len(text) > 30, f"definition for `{key}` says nothing: {text!r}"


def test_no_registered_site_has_gone_blind(gen, live) -> None:
    """A site pattern that matches nothing is not a pass.

    This is the failure mode a stated-count guard dies of: the prose is
    reworded, the regex stops matching, and the gate reports PASS over an
    empty set forever.
    """
    sites = gen.check_sites(live["counts"])
    assert not sites["blind"], (
        "registered stated-count site(s) matched NOTHING — the guard is blind "
        f"there: {sites['blind']}")
    assert sites["checked"] >= len(gen.STATED_SITES), (
        f"only {sites['checked']} stated count(s) resolved for "
        f"{len(gen.STATED_SITES)} registered site(s)")


def test_no_stated_count_has_drifted(gen, live) -> None:
    sites = gen.check_sites(live["counts"])
    assert not sites["drift"], "\n".join(
        f"{d['file']}:{d['line']} states {d['stated']} for `{d['key']}` "
        f"({d['note']}) — generated value is {d['generated']}"
        for d in sites["drift"])


def test_cli_check_exits_zero() -> None:
    """The gate as a runner invokes it: exit 0 is the only PASS."""
    r = subprocess.run([sys.executable, str(GEN), "--check"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (
        f"`gen_program_inventory.py --check` exited {r.returncode}\n"
        f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    assert "[PASS] gen_program_inventory:" in r.stdout, (
        "no PASS summary line printed — a run that printed no verdict is not a "
        f"pass.\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")


def test_check_fails_when_a_stated_count_is_hand_edited(tmp_path) -> None:
    """The discriminating half: change one stated number, the gate must FAIL
    and NAME THE FILE. Without this, a guard that always passes looks the same
    as a guard that works."""
    gen = _gen()
    counts = gen.discover()["counts"]
    site = next(s for s in gen.STATED_SITES if s.key == "programs_py")
    doc = gen.REPO_ROOT / site.path
    text = doc.read_text()

    import re
    m = re.search(site.pattern, text)
    assert m, f"site pattern no longer matches {site.path}"
    mutated = text[:m.start(1)] + str(counts["programs_py"] + 1) + text[m.end(1):]

    scratch = tmp_path / site.path
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text(mutated)

    real_root = gen.REPO_ROOT
    try:
        # Point the site resolver at the mutated copy; every other site falls
        # back to NOT DETERMINED, which is exactly what "file absent" means.
        gen.REPO_ROOT = tmp_path
        sites = gen.check_sites(counts)
    finally:
        gen.REPO_ROOT = real_root

    assert sites["drift"], "hand-edited count was not detected"
    assert any(d["file"] == site.path and d["stated"] == counts["programs_py"] + 1
               for d in sites["drift"]), sites["drift"]


def test_not_determined_is_not_a_pass(tmp_path) -> None:
    """rc=2 when nothing could be read. A gate that cannot see its inputs must
    say so, not report PASS over an empty set."""
    gen = _gen()
    real_root = gen.REPO_ROOT
    try:
        gen.REPO_ROOT = tmp_path          # no README anywhere below it
        sites = gen.check_sites(gen.discover()["counts"])
    finally:
        gen.REPO_ROOT = real_root
    assert sites["checked"] == 0
    assert not sites["drift"]
    assert len(sites["not_determined"]) == len(gen.STATED_SITES)


# ── the verdict, exercised directly ─────────────────────────────────
_CLEAN_SITES = {"checked": 5, "drift": [], "blind": [], "not_determined": []}


def _inv(gen):
    return {"counts": {"a": 1}, "definitions": {"a": "counts a"}}


def test_verdict_pass(gen) -> None:
    rc, fail = verdict_of(gen, _inv(gen), _CLEAN_SITES, {"counts": {"a": 1},
                                                         "definitions": {"a": "counts a"}})
    assert (rc, fail) == (0, [])


def verdict_of(gen, inv, sites, committed):
    return gen.verdict(inv, sites, committed)


def test_verdict_flags_a_stale_committed_inventory(gen) -> None:
    rc, fail = verdict_of(gen, _inv(gen), _CLEAN_SITES,
                          {"counts": {"a": 2}, "definitions": {"a": "counts a"}})
    assert rc == 1 and any("committed=2 filesystem=1" in f for f in fail)


def test_verdict_flags_a_blind_site(gen) -> None:
    sites = dict(_CLEAN_SITES, blind=[{"file": "R.md", "key": "a",
                                       "note": "n", "pattern": "p"}])
    rc, fail = verdict_of(gen, _inv(gen), sites,
                          {"counts": {"a": 1}, "definitions": {"a": "counts a"}})
    assert rc == 1 and any("gone blind" in f for f in fail)


def test_verdict_not_checked_when_nothing_was_readable(gen) -> None:
    sites = {"checked": 0, "drift": [], "blind": [],
             "not_determined": [{"file": "R.md", "key": "a", "why": "file absent"}]}
    rc, fail = verdict_of(gen, _inv(gen), sites,
                          {"counts": {"a": 1}, "definitions": {"a": "counts a"}})
    assert (rc, fail) == (2, []), "unreadable inputs must be rc=2, never PASS"


def test_a_definite_failure_outranks_not_checked(gen) -> None:
    """rc=2 must not swallow a measured contradiction."""
    sites = {"checked": 0, "drift": [], "blind": [],
             "not_determined": [{"file": "R.md", "key": "a", "why": "file absent"}]}
    rc, fail = verdict_of(gen, _inv(gen), sites,
                          {"counts": {"a": 99}, "definitions": {"a": "counts a"}})
    assert rc == 1 and fail


def test_a_not_determined_count_does_not_contradict_the_committed_one(gen) -> None:
    """A standalone install cannot resolve `programs_catalogued`. "I could not
    look" must not be reported as "the recorded number is wrong"."""
    inv = {"counts": {"a": None}, "definitions": {"a": "counts a"}}
    rc, fail = verdict_of(gen, inv, _CLEAN_SITES,
                          {"counts": {"a": 1112}, "definitions": {"a": "counts a"}})
    assert (rc, fail) == (0, [])


def test_verdict_flags_a_missing_inventory(gen) -> None:
    rc, fail = verdict_of(gen, _inv(gen), _CLEAN_SITES, None)
    assert rc == 1 and any("missing" in f for f in fail)
