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
import shutil
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


# ─────────────────────────────────────────────────────────────────────────────
# THE ANNOUNCEMENT MUST NOT BE ABLE TO LOSE THE VERDICT (2026-09-05).
#
# MEASURED, on the v1.17.64 exact-tree landing stamp
# (`final-stamp-v11722-b495/run.log`, repo b495bbc9d, tree cd2d7767f, image
# ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d01ff): after the tier printed its
# verdict, the publisher died with
#
#     File ".../tools/ci/landing_status_publish.py", line 160, in publish
#       proc = subprocess.run(argv, capture_output=True, text=True)
#     FileNotFoundError: [Errno 2] No such file or directory: 'gh'
#
# `gh` is not in the pinned image — verified directly: `command -v gh` exits 1
# there while `/usr/bin/git` and python3.12 are present. The crash did not cause
# that run's FAIL, and `gatekeeper-land.sh` calls the publisher with `|| true`
# so the landing's own rc was never at risk. What WAS lost is the publisher's
# own record: `publish()` already owns an honest degradation path for a `gh`
# that ran and failed (rc != 0 -> say so, return 2), and an exec that never
# happened walked straight past it as an uncaught exception. A GREEN stamp
# would have been announced the same way — i.e. not at all, and not said so.
#
# THE INVARIANT: the VERDICT and its PUBLICATION are two separately recorded
# facts. `publish()` may fail; it may never crash, never claim `published`, and
# must always name the state it was carrying so the verdict survives the
# failure of its own announcement.
#
# BIDIRECTIONAL, per this file's own standard: every "gh is gone" assertion
# below is paired with the same call against a `gh` that IS on PATH.
# ─────────────────────────────────────────────────────────────────────────────

_SHA = "1" * 40


def _bin_dir(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    return d


def _fake_gh(tmp_path: Path, rc: int, err: str = "") -> Path:
    """A PATH holding one executable named `gh` that exits `rc`.

    The negative control for every absence test below: same call, same
    arguments, one variable changed — whether `gh` can be executed at all.
    """
    d = _bin_dir(tmp_path, f"bin_gh_{rc}")
    gh = d / "gh"
    gh.write_text("#!/bin/sh\n" + (f'printf %s {err!r} >&2\n' if err else "")
                  + f"exit {rc}\n")
    gh.chmod(0o755)
    return d


def test_a_gh_that_is_absent_is_recorded_not_raised(tmp_path, monkeypatch,
                                                    capsys):
    """The exact recorded crash. `publish()` must return, not propagate."""
    monkeypatch.setenv("PATH", str(_bin_dir(tmp_path, "empty")))
    rc = PUB.publish("vibeic/vibe-ic", _SHA, "success", "", False)
    out, err = capsys.readouterr()
    assert rc == 2, "a status that was not published must exit non-zero"
    assert "NOT_PUBLISHED" in err, err
    assert "gh" in err, "the reason must name what was missing: %r" % err
    assert "published " not in out, (
        "nothing may be announced as published when nothing was: %r" % out)


def test_a_gh_that_is_present_still_publishes(tmp_path, monkeypatch, capsys):
    """NEGATIVE CONTROL for the test above — the one variable is `gh` on PATH.

    Without this, a `publish()` that returned 2 unconditionally would satisfy
    every absence assertion in this section.
    """
    monkeypatch.setenv("PATH", str(_fake_gh(tmp_path, 0)))
    rc = PUB.publish("vibeic/vibe-ic", _SHA, "success", "", False)
    out, _ = capsys.readouterr()
    assert rc == 0
    assert "published success" in out, out
    assert "NOT_PUBLISHED" not in out


def test_a_gh_that_ran_and_failed_is_recorded_the_same_way(tmp_path,
                                                           monkeypatch,
                                                           capsys):
    """The pre-existing rc!=0 path keeps its meaning and gains the same token.

    An API call that was refused and an exec that never happened are the same
    fact for a reader of the status page — no status is standing — so they are
    recorded under one name, each with its own reason.
    """
    monkeypatch.setenv("PATH", str(_fake_gh(tmp_path, 1, "HTTP 403")))
    rc = PUB.publish("vibeic/vibe-ic", _SHA, "success", "", False)
    out, err = capsys.readouterr()
    assert rc == 2
    assert "NOT_PUBLISHED" in err, err
    assert "HTTP 403" in err, "the transport's own reason must survive: %r" % err
    assert "published " not in out


def test_the_state_survives_a_failed_announcement(tmp_path, monkeypatch,
                                                  capsys):
    """The verdict is the fact; publication is a separate one that may fail.

    Both states are checked, because a message that named only one of them
    would leave the other outcome's reader with a verdict and no name for it.
    """
    monkeypatch.setenv("PATH", str(_bin_dir(tmp_path, "empty2")))
    for state in ("success", "failure"):
        assert PUB.publish("vibeic/vibe-ic", _SHA, state, "", False) == 2
        _, err = capsys.readouterr()
        assert state in err, (
            "the %r verdict was carried into publish() and its own record does "
            "not name it: %r" % (state, err))


def test_a_dry_run_needs_no_gh_at_all(tmp_path, monkeypatch, capsys):
    """`--dry-run` prints the call and posts nothing, so absence is irrelevant.

    It must not start reporting NOT_PUBLISHED: nothing was attempted.
    """
    monkeypatch.setenv("PATH", str(_bin_dir(tmp_path, "empty3")))
    rc = PUB.publish("vibeic/vibe-ic", _SHA, "success", "", True)
    out, err = capsys.readouterr()
    assert rc == 0
    assert out.startswith("DRY-RUN ")
    assert "NOT_PUBLISHED" not in err


def test_main_reaches_a_verdict_and_then_reports_it_unpublished(
        tmp_path, monkeypatch, capsys):
    """END TO END, in the shape the landing runs it: green stamp, no `gh`.

    `decide()` must still reach `success` — the verdict is not conditional on
    the announcement — and the process must exit non-zero having said so.
    """
    repo = _repo(tmp_path)
    sha = _head(repo)
    _stamp(repo, sha)
    git = shutil.which("git")
    assert git, "NOT_MEASURED: no git on PATH to build the fixture with"
    bin_dir = _bin_dir(tmp_path, "bin_git_only")
    (bin_dir / "git").symlink_to(git)
    monkeypatch.setenv("PATH", str(bin_dir))
    rc = PUB.main(["--repo", str(repo), "--sha", sha, "--failed", "0"])
    out, err = capsys.readouterr()
    assert rc == 2, "an unpublished status must not exit 0"
    assert "NOT_PUBLISHED" in err, err
    assert "success" in err, (
        "the run reached a green verdict and the record must say which verdict "
        "went unpublished: %r" % err)
    assert "REFUSED" not in err, (
        "a `gh` that is absent is not a refusal to judge — the gates judged, "
        "and only the announcement failed: %r" % err)
    assert "published " not in out


def test_the_publisher_process_survives_a_pinned_image_without_gh(tmp_path):
    """The recorded defect at PROCESS level: no traceback, no exit 1.

    The unit tests above call `publish()` in-process. This one runs the program
    the way `gatekeeper-land.sh` does, under a PATH that carries `git` and not
    `gh` — the pinned image's exact shape (`command -v gh` -> rc 1,
    `/usr/bin/git` present). The pre-fix program answers this with a
    `FileNotFoundError` traceback and rc 1.
    """
    repo = _repo(tmp_path)
    sha = _head(repo)
    _stamp(repo, sha)
    git = shutil.which("git")
    assert git, "NOT_MEASURED: no git on PATH to build the fixture with"
    bin_dir = _bin_dir(tmp_path, "bin_proc")
    (bin_dir / "git").symlink_to(git)
    proc = subprocess.run(
        [sys.executable, str(HERE / "landing_status_publish.py"),
         "--repo", str(repo), "--sha", sha, "--failed", "0"],
        capture_output=True, text=True,
        env={"PATH": str(bin_dir), "PYTHONDONTWRITEBYTECODE": "1"})
    assert "Traceback" not in proc.stderr, (
        "the publisher crashed instead of recording that it could not publish:"
        "\n%s" % proc.stderr)
    assert "FileNotFoundError" not in proc.stderr, proc.stderr
    assert proc.returncode == 2, (
        "expected the documented `2 = nothing was published` exit, got %d\n%s"
        % (proc.returncode, proc.stderr))
    assert "NOT_PUBLISHED" in proc.stderr, proc.stderr
    assert "published " not in proc.stdout, proc.stdout
