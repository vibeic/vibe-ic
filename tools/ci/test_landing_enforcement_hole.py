"""The enforcement hole, and the two halves that close it.

BIDIRECTIONAL NEGATIVE CONTROL is the point of this file, not coverage: every
test that asserts a REFUSAL is paired with one that asserts the same input
passes once the single offending variable is removed.  A test that cannot fail
against the pre-fix code proves nothing, which is this repo's own standard
(`flow-change-acceptance`).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


PUB = _load("landing_status_publish", HERE / "landing_status_publish.py")
PROT = _load("main_ref_protection_check", HERE / "main_ref_protection_check.py")


# --------------------------------------------------------------------------
# THE PUBLISHER: a green may only be published for a green landing.
# --------------------------------------------------------------------------
def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True,
                                    capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.invalid")
    run("config", "user.name", "t")
    (r / "f").write_text("1\n")
    run("add", "f")
    run("commit", "-q", "-m", "c1")
    return r


def _stamp(repo: Path, sha: str) -> None:
    gd = subprocess.run(["git", "-C", str(repo), "rev-parse",
                         "--absolute-git-dir"], capture_output=True, text=True,
                        check=True).stdout.strip()
    (Path(gd) / "gatekeeper-stamp").write_text(sha + "\ncadence=FULL\n")


def _head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def test_a_green_landing_publishes_success(tmp_path):
    repo = _repo(tmp_path)
    sha = _head(repo)
    _stamp(repo, sha)
    assert PUB.decide(repo, "0", sha) == "success"


def test_a_red_landing_publishes_failure_never_success(tmp_path):
    """The ONE variable is `--failed`; everything else is the passing fixture."""
    repo = _repo(tmp_path)
    sha = _head(repo)
    _stamp(repo, sha)
    assert PUB.decide(repo, "1", sha) == "failure"


@pytest.mark.parametrize("failed", ["", "  ", "NORECORD", "yes", "0x0"])
def test_a_verdict_that_was_lost_refuses_rather_than_guessing(tmp_path, failed):
    repo = _repo(tmp_path)
    sha = _head(repo)
    _stamp(repo, sha)
    with pytest.raises(PUB.Refusal):
        PUB.decide(repo, failed, sha)


def test_no_stamp_cannot_produce_a_green(tmp_path):
    repo = _repo(tmp_path)
    sha = _head(repo)
    # NEGATIVE CONTROL FIRST: with the stamp it passes.
    _stamp(repo, sha)
    assert PUB.decide(repo, "0", sha) == "success"
    gd = subprocess.run(["git", "-C", str(repo), "rev-parse",
                         "--absolute-git-dir"], capture_output=True, text=True,
                        check=True).stdout.strip()
    (Path(gd) / "gatekeeper-stamp").unlink()
    with pytest.raises(PUB.Refusal):
        PUB.decide(repo, "0", sha)


def test_a_stamp_for_another_commit_cannot_vouch_for_this_one(tmp_path):
    repo = _repo(tmp_path)
    sha = _head(repo)
    _stamp(repo, "0" * 40)
    with pytest.raises(PUB.Refusal):
        PUB.decide(repo, "0", sha)


def test_a_dirty_tree_cannot_produce_a_green(tmp_path):
    repo = _repo(tmp_path)
    sha = _head(repo)
    _stamp(repo, sha)
    assert PUB.decide(repo, "0", sha) == "success"      # negative control
    (repo / "f").write_text("2\n")
    with pytest.raises(PUB.Refusal):
        PUB.decide(repo, "0", sha)


# --------------------------------------------------------------------------
# THE TRIPWIRE: the server-side rule has a reader.
# --------------------------------------------------------------------------
def _good_ruleset() -> dict:
    return {
        "name": "main-requires-the-landing-lane",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"],
                                    "exclude": []}},
        "rules": [
            {"type": "non_fast_forward"},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": False,
                "required_status_checks": [{"context": PROT.CONTEXT}]}},
        ],
    }


def test_the_correct_ruleset_passes():
    assert PROT.findings([_good_ruleset()]) == []


def test_an_empty_ruleset_list_is_the_measured_state_of_main_today():
    """`GET /repos/vibeic/vibe-ic/rulesets` returned `[]` on 2026-08-29."""
    found = PROT.findings([])
    assert len(found) == 1
    assert "NO RULESET TARGETS `main`" in found[0]


@pytest.mark.parametrize("mutate,expect", [
    (lambda r: r.__setitem__("enforcement", "evaluate"), "not 'active'"),
    (lambda r: r.__setitem__("bypass_actors", [{"actor_id": 5}]),
     "bypass actor"),
    (lambda r: r.__setitem__(
        "rules", [x for x in r["rules"] if x["type"] != "non_fast_forward"]),
     "no `non_fast_forward` rule"),
    (lambda r: r["rules"][1]["parameters"]["required_status_checks"]
     .__setitem__(0, {"context": "something/else"}), "and not"),
    (lambda r: r["conditions"]["ref_name"].__setitem__(
        "include", ["refs/heads/release/*"]), "NO RULESET TARGETS"),
    (lambda r: r["conditions"]["ref_name"].__setitem__(
        "exclude", ["refs/heads/main"]), "NO RULESET TARGETS"),
])
def test_each_way_the_rule_can_be_hollowed_out_is_a_finding(mutate, expect):
    """ONE mutation at a time, from the fixture proven green above."""
    rs = _good_ruleset()
    assert PROT.findings([rs]) == []            # the negative control
    mutate(rs)
    found = PROT.findings([rs])
    assert found, f"hollowing the rule with {expect!r} produced no finding"
    assert any(expect in f for f in found), found


def test_could_not_check_is_not_a_pass(tmp_path):
    rc = PROT.main(["--snapshot", str(tmp_path / "absent.json")])
    assert rc == 2


def test_a_snapshot_of_the_good_ruleset_exits_zero(tmp_path):
    p = tmp_path / "rs.json"
    p.write_text(json.dumps([_good_ruleset()]))
    assert PROT.main(["--snapshot", str(p)]) == 0
    p.write_text(json.dumps([]))
    assert PROT.main(["--snapshot", str(p)]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# THE WIRING ITSELF WAS UNGUARDED, AND FALSIFICATION IS HOW THAT WAS FOUND.
#
# Everything above tests the two new READERS. Reverting the 23-line hunk in
# `tools/gatekeeper-land.sh` — the part that actually publishes the verdict
# during a landing — left this file at 38 passed, 0 failed. A guard that covers
# the easy half and leaves the load-bearing wiring unobserved is the shape this
# whole finding is about, so it does not get to ship that way.
#
# The assertion is MEMBERSHIP, not a count. `grep -c landing_status_publish`
# returning 2 is satisfied by two calls sitting in the SAME branch, which would
# leave one of the two outcomes silently unreported. Each call is therefore
# anchored to the stamp operation it must follow.
# ─────────────────────────────────────────────────────────────────────────────

_LAND_SH = HERE.parent / "gatekeeper-land.sh"
_PUBLISHER = "tools/ci/landing_status_publish.py"


def _publish_sites(text):
    """(after_stamp_write, after_stamp_remove) — does a publish call follow each?

    Returns a dict so a failure names WHICH side is unwired rather than only
    that something is.
    """
    lines = text.splitlines()
    write_i = remove_i = None
    for i, ln in enumerate(lines):
        if write_i is None and "git rev-parse HEAD >" in ln and "gatekeeper-stamp" in ln:
            write_i = i
        if "rm -f" in ln and "gatekeeper-stamp" in ln and "GATEKEEPER_NO_STAMP" not in ln:
            # the failure branch's removal is the LAST one in the file
            remove_i = i
    out = {}
    for name, idx in (("after_stamp_write", write_i), ("after_stamp_remove", remove_i)):
        if idx is None:
            out[name] = None          # the anchor itself moved — NOT_FOUND, never False
            continue
        # look ahead only as far as the next anchor, so one call cannot satisfy both
        stop = len(lines)
        for other in (write_i, remove_i):
            if other is not None and other > idx:
                stop = min(stop, other)
        window = "\n".join(lines[idx:stop])
        out[name] = _PUBLISHER in window
    return out


def test_the_landing_script_publishes_its_verdict_on_both_outcomes():
    sites = _publish_sites(_LAND_SH.read_text())
    missing = [k for k, v in sites.items() if v is None]
    assert not missing, (
        "the stamp anchor(s) %s are no longer in gatekeeper-land.sh, so this test "
        "cannot say whether the publisher is wired. That is NOT_MEASURED, and it "
        "fails rather than passing quietly." % missing)
    unwired = [k for k, v in sites.items() if v is False]
    assert not unwired, (
        "gatekeeper-land.sh does not publish its verdict %s. The stamp lives in "
        ".git/, which the server cannot see, so an unpublished outcome is a lane "
        "that refuses locally and stops nothing — the exact hole this change "
        "closes." % unwired)


def test_publishing_can_only_ever_make_a_push_harder():
    """Both calls pass the real verdict and neither can abort the landing.

    `|| true` is not a swallowed error here: a status that could not be
    published leaves the server-side rule UNSATISFIED, so the push is refused
    with a sentence naming the missing context. Failing to publish is therefore
    safe in exactly one direction, and the script must keep it that way.
    """
    text = _LAND_SH.read_text()
    calls = [ln for ln in text.splitlines() if _PUBLISHER in ln and "python3" in ln]
    assert len(calls) == 2, (
        "expected exactly 2 publisher invocations, found %d: %r" % (len(calls), calls))
    # The verdict is passed through, never re-derived at the call site.
    #
    # This is scoped to the PUBLISHER's own invocations rather than counted
    # file-wide: `--failed "$FAILED"` also appears at the landing-completion
    # recorder around :1994, and a file-wide count of 2 was RED against a
    # correct script purely because a different program spells its flag the
    # same way. A population defined by one spelling is not the population.
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if _PUBLISHER not in ln or "python3" not in ln:
            continue
        tail = "\n".join(lines[i:i + 3])
        assert '--failed "$FAILED"' in tail, (
            "publisher call near line %d does not forward the run's own FAILED "
            "count; a call that recomputes or hardcodes it can report a verdict "
            "the run never reached" % (i + 1))
        assert "|| true" in tail, (
            "publisher call near line %d is fatal to the landing; a failure to "
            "publish must not abort a run whose gates passed" % (i + 1))


@pytest.mark.parametrize("mutation,why", [
    (lambda t: t.replace('python3 "$ROOT/tools/ci/landing_status_publish.py" --repo "$ROOT" \\\n      --failed "$FAILED" || true', "", 1),
     "the success-side publish deleted"),
    (lambda t: t.replace(_PUBLISHER, "tools/ci/nothing_here.py"),
     "the publisher renamed out from under the caller"),
])
def test_a_landing_script_that_stopped_publishing_is_caught(mutation, why, tmp_path):
    """The guard must go RED when the wiring is removed — proven, not assumed."""
    mutated = mutation(_LAND_SH.read_text())
    sites = _publish_sites(mutated)
    assert False in sites.values() or None in sites.values(), (
        "mutation %r left the guard green; it is not observing the wiring" % why)
