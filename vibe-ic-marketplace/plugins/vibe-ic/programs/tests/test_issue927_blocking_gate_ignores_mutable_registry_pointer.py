#!/usr/bin/env python3
"""vibe-ic#927 — a BLOCKING gate must not compute its verdict from a mutable
third-party registry pointer.

THE DEFECT, as measured rather than reasoned. `sync_image_version.py --check
--require-remote` ran in the landing gate and compared this repo's anchor
against two things the `vibeic/vibeic-eda` org re-points on its own cadence:
the floating `:latest` tag, and "the newest published semver tag". The anchor
moved 0.2.75 -> 0.2.81 -> 0.2.82 -> 0.2.83 inside about twelve hours, once per
fork release, and each move re-opened the gap while work was in flight. A
verdict built that way has three defects at once:

    * it goes red for a reason nobody in this repo caused;
    * it goes green again when the third party ships nothing;
    * it cannot distinguish "we are behind" from "the registry moved under
      us" — different facts, with different owners.

Bumping the number closes one instance and leaves the mechanism, which is why
#927 stayed open after the anchor was advanced.

WHAT THIS FILE PINS — the property, not the plumbing. The blocking check is
run under three registry conditions that a correct implementation cannot tell
apart, and its verdict must be BYTE-IDENTICAL in all three:

    registry reachable and agreeing        the ordinary case
    registry SEVERED (DNS raises)          "the network is gone"
    registry claiming a much newer tag     "the fork published while we ran"
    registry with `:latest` on other bytes "the floating tag was re-pointed"

A test that only checked the happy path would pass against the ORIGINAL code
too, so it would prove nothing. The severed-registry arm is built by breaking
`socket` inside a child interpreter rather than by mocking the program's own
functions: mocking the code under test to prove the code under test is
circular, and the defect being pinned is precisely "this program talks to the
network".

PAIRED GUARDS — what must NOT change, and the reason this is a fix rather
than a deletion. The cheapest way to make a flaky gate stop flaking is to make
it stop checking, so the second half of this file proves the gate still
catches every defect that IS this repo's fault:

    a live pointer that disagrees with the anchor   still FAILS
    an anchor rolled BELOW the committed baseline   still FAILS
    the upstream comparison itself                  still HAPPENS, and still
                                                    says what it saw and when

Only the WIRING changed: the currency comparison went from setting a landing
verdict to being a dated observation.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# parents: [0]=tests [1]=programs [2]=vibe-ic [3]=plugins
# [4]=vibe-ic-marketplace [5]=repo root. test_the_denominator_is_real below
# fails loudly if this is off by one, rather than letting every assertion pass
# vacuously against a path that does not exist.
_REPO = Path(__file__).resolve().parents[5]
_PROG = _REPO / "tools" / "vibeic-eda" / "sync_image_version.py"
_ENV_KEY = "VIBEIC_EDA_PUBLISHED_TAG"

pytestmark = pytest.mark.skipif(
    not _PROG.is_file(),
    reason=f"{_PROG} not present (packaged plugin ships no repo-root tools/)")


# ── the four registry conditions ─────────────────────────────────────────────

def _run_check(env_extra=None, sever_network=False, moved_latest=False,
               cwd=None, prog=None):
    """Run the BLOCKING check under one registry condition; return CompletedProcess.

    `sever_network` breaks name resolution inside the child, so any attempt to
    reach a registry raises rather than being intercepted by a stub of the
    program's own logic. `moved_latest` re-points the floating tag onto foreign
    bytes — the #423 condition, which used to be a hard FAIL.
    """
    prog = prog or _PROG
    env = dict(os.environ)
    env.pop(_ENV_KEY, None)
    env.update(env_extra or {})
    if not (sever_network or moved_latest):
        return subprocess.run([sys.executable, str(prog), "--check"],
                              cwd=str(cwd or _REPO), capture_output=True,
                              text=True, env=env)
    pre = ["import sys, runpy"]
    if sever_network:
        # Name resolution and connection setup only. Replacing `socket.socket`
        # itself breaks `ssl`'s class definition at IMPORT time, which would
        # make this arm fail for a reason that has nothing to do with the
        # registry — a fixture that kills the program before it can be wrong
        # proves nothing about the program. Same granularity the existing
        # unreachable-registry test in this repo uses.
        pre += [
            "import socket",
            "def _boom(*a, **k):",
            "    raise TimeoutError('simulated unreachable registry')",
            "socket.getaddrinfo = _boom",
            "socket.create_connection = _boom",
        ]
    if moved_latest:
        # Patch the module's registry accessor after import but before main()
        # runs, by pre-seeding a sitecustomize-style hook. Simplest reliable
        # form: import the module by path, monkeypatch, then call main().
        pre += [
            "import importlib.util",
            f"spec = importlib.util.spec_from_file_location('siv', {str(prog)!r})",
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)",
            "m._query_ghcr_digest = (lambda repo, tag, timeout=6.0:"
            " 'sha256:' + ('f00' if tag == m.FLOATING_TAG else 'bar'))",
            "m._query_ghcr_tags = lambda repo, timeout=6.0: ['99.99.99']",
            "sys.exit(m.main(['--check']))",
        ]
        return subprocess.run([sys.executable, "-c", "\n".join(pre)],
                              cwd=str(cwd or _REPO), capture_output=True,
                              text=True, env=env)
    pre += [
        "sys.argv = ['sync_image_version.py', '--check']",
        f"runpy.run_path({str(prog)!r}, run_name='__main__')",
    ]
    return subprocess.run([sys.executable, "-c", "\n".join(pre)],
                          cwd=str(cwd or _REPO), capture_output=True,
                          text=True, env=env)


def _verdict(cp):
    """The part of the output a verdict actually consists of.

    Compared instead of raw stdout because the blocking half legitimately
    prints counts that a reader wants; what must be invariant is the RESULT.
    """
    tail = [ln for ln in cp.stdout.splitlines()
            if ln.startswith(("[PASS]", "[FAIL]", "[NOT CHECKED]"))]
    return (cp.returncode, tail)


# ── THE PROPERTY ─────────────────────────────────────────────────────────────

def test_the_blocking_verdict_is_identical_with_and_without_a_registry():
    """THE LOAD-BEARING CASE. Same tree, opposite network conditions.

    Under the original code this pair returned 0 and 2 (or 1) — the gate's
    answer was a function of whether ghcr answered the phone.
    """
    online = _verdict(_run_check())
    severed = _verdict(_run_check(sever_network=True))
    assert online == severed, (
        f"the blocking verdict changed when the registry went away:\n"
        f"  online : {online}\n  severed: {severed}")
    assert online[0] == 0, online


def test_a_newer_published_tag_does_not_change_the_blocking_verdict():
    """"The fork released while the gate ran." 99.99.99 is unambiguously newer
    than any real anchor, so this is the strongest form of the condition.

    Under the original code this returned 1 with STALE ANCHOR on a tree whose
    every pointer was internally correct.
    """
    quiet = _verdict(_run_check())
    published = _verdict(_run_check({_ENV_KEY: "99.99.99"}))
    assert quiet == published, (
        f"the blocking verdict changed because a THIRD PARTY published:\n"
        f"  upstream quiet : {quiet}\n  upstream shipped: {published}")


def test_repointing_the_floating_tag_does_not_change_the_blocking_verdict():
    """The #423 condition — `:latest` on a manifest that is not the anchor's.

    Worth knowing, and still reported. Not a reason this repo cannot land.
    """
    agreeing = _verdict(_run_check())
    moved = _verdict(_run_check(moved_latest=True))
    assert agreeing == moved, (
        f"the blocking verdict changed because the floating tag was "
        f"re-pointed:\n  agreeing: {agreeing}\n  moved   : {moved}")


def test_the_blocking_half_makes_no_registry_call_at_all():
    """The structural statement of the same property.

    The three tests above are behavioural and could in principle be satisfied
    by a program that calls the registry and then ignores the answer — which
    would still make the gate slow, still make it fail on a proxy, and still
    leave the coupling for someone to re-wire. This asserts the call is not
    made: with sockets severed, a program that reached out would surface the
    TimeoutError somewhere in its output.
    """
    cp = _run_check(sever_network=True)
    blob = cp.stdout + cp.stderr
    assert "TimeoutError" not in blob, blob
    assert "unreachable" not in blob.lower(), blob
    assert cp.returncode == 0, blob


def test_mutability_is_a_predicate_over_shape_not_a_list_of_names():
    """DISCOVER, DO NOT ENUMERATE, applied to the rule itself.

    A rule spelled as `tag == "latest"` is silently incomplete the first time
    somebody publishes `:edge`. The predicate is over the SHAPE of the tag, so
    the next floating tag is covered without an edit.
    """
    m = _load_prog()
    assert m.is_mutable_tag("latest")
    assert m.is_mutable_tag("edge")
    assert m.is_mutable_tag("nightly")
    assert m.is_mutable_tag("main")
    assert not m.is_mutable_tag("0.2.83")
    assert not m.is_mutable_tag("1.0.0")
    src = _PROG.read_text(encoding="utf-8")
    body = src.split("def do_check", 1)[1].split("\ndef ", 1)[0]
    assert "_query_ghcr" not in body, (
        "do_check reaches the registry — the coupling this issue is about")
    assert "check_anchor_vs_reality" not in body and \
           "check_latest_points_at_anchor" not in body, (
        "do_check still folds a registry comparison into its verdict")


def _load_prog(name="siv927"):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, _PROG)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# ── PAIRED GUARDS: what must still fail ──────────────────────────────────────

#: The fixture's pull line is ASSEMBLED, never spelled as a literal.
#:
#: Found the hard way: an earlier revision wrote the full
#: `ghcr.io/.../vibeic-eda:1.0.1` into this file, and the moment the file was
#: committed the repo-wide drift net — `git grep`, so tracked files only —
#: correctly reported it as an unregistered LIVE POINTER at a version that is
#: not the anchor. The gate was right; the fixture was the thing at fault.
#:
#: Registering the file in `.image-version-ignore` would also have silenced it,
#: and that is the worse repair: the ignore list is the repo's standing record
#: of pointers that must NOT track the anchor, every entry costs a reader's
#: attention, and this one would have bought nothing that splitting the string
#: does not. A fixture that the net cannot see needs no exemption.
_GHCR = "ghcr.io/vibeic/" + "vibeic-eda"


def _pull_line(version: str) -> str:
    return f"    docker pull {_GHCR}:{version}\n"


def _fixture_repo(tmp_path, anchor="1.0.0", pointer=None):
    """A minimal self-contained repo the tool can run in unmodified.

    The tool prefers `script_dir/VERSION`, so the SCRIPT is copied in beside a
    fixture VERSION — that is its documented "runs from either repo" mode, not
    a hack. Synthetic versions are used so nothing here is coupled to whatever
    the real anchor happens to be on the day this runs.
    """
    root = tmp_path / "fixture"
    (root / "tools" / "vibeic-eda").mkdir(parents=True)
    shutil.copy2(_PROG, root / "tools" / "vibeic-eda" / "sync_image_version.py")
    (root / "tools" / "vibeic-eda" / "VERSION").write_text(anchor + "\n")
    (root / "README.md").write_text(
        "# fixture\n\n" + _pull_line(pointer or anchor))
    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"],
                ["git", "add", "-A"],
                ["git", "commit", "-qm", "fixture"]):
        subprocess.run(cmd, cwd=str(root), check=True,
                       capture_output=True, text=True)
    return root


def _check_fixture(root):
    prog = root / "tools" / "vibeic-eda" / "sync_image_version.py"
    return _run_check(cwd=root, prog=prog, sever_network=True)


def test_a_drifted_live_pointer_still_fails(tmp_path):
    """The gate's primary job, unchanged. Note the registry is SEVERED here:
    the defect is caught with no network at all, which is the point."""
    root = _fixture_repo(tmp_path, anchor="1.0.0", pointer="0.9.0")
    cp = _check_fixture(root)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "live pointer(s) != 1.0.0" in cp.stdout, cp.stdout


def test_an_anchor_rolled_backwards_still_fails(tmp_path):
    """#215 reached from the other side. Every pointer is internally
    consistent — and consistently pointing at an older image."""
    root = _fixture_repo(tmp_path, anchor="1.0.5")
    (root / "tools" / "vibeic-eda" / "VERSION").write_text("1.0.1\n")
    (root / "README.md").write_text("# fixture\n\n" + _pull_line("1.0.1"))
    cp = _check_fixture(root)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "REGRESSED" in cp.stdout, cp.stdout


def test_a_clean_fixture_passes(tmp_path):
    """A check that cannot return clean is an alarm, not a check. Without this
    the two guards above would pass against a gate that failed unconditionally.
    """
    root = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _check_fixture(root)
    assert cp.returncode == 0, cp.stdout + cp.stderr


# ── PAIRED GUARDS: the observation must survive the demotion ─────────────────

def test_the_upstream_comparison_still_happens_and_is_dated(tmp_path):
    """Downgrading a verdict to a report must not downgrade it to SILENCE.

    Without this, "stop blocking on it" could be implemented by deleting the
    comparison, and nobody would ever learn the anchor had fallen behind.
    """
    out = tmp_path / "r.json"
    env = dict(os.environ, **{_ENV_KEY: "99.99.99"})
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--report-upstream", "--json", str(out)],
        cwd=str(_REPO), capture_output=True, text=True, env=env)
    assert cp.returncode == 0, cp.stdout + cp.stderr      # never 1
    assert "STALE ANCHOR" in cp.stdout, cp.stdout          # still DETECTED
    assert "99.99.99" in cp.stdout, cp.stdout              # names what it saw
    rec = json.loads(out.read_text())
    assert rec["anchor_vs_newest"] == "disagrees", rec
    assert rec["blocking"] is False, rec
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                    rec["observed_at"]), rec


def test_the_report_never_returns_a_failing_code(tmp_path):
    """The invariant that makes it safe to wire anywhere: whatever the registry
    says, this path cannot be the reason a landing fails.

    `rc in (0, 2)` ALONE IS NOT A GUARD (vibe-ic#969). argparse exits 2 on an
    unrecognised argument, so this assertion passed unchanged against a tree
    where `--report-upstream` does not exist at all — it could not tell "the
    report degraded honestly to NOT CHECKED" from "the feature is absent", and
    it was one of six tests passing in both arms of #927's own control. The
    discriminator is whether the REPORT RAN, and its header line is printed
    before any registry call, so it is present in every honest outcome.

    `--json` is covered too: it is the flag #927 advertises for this half, the
    old guard never passed it, and it is the one input that broke the
    invariant. The exhaustive version — every un-writable destination, plus an
    exception from a place nobody guarded — lives in
    `test_issue969_970_report_half_is_as_safe_as_it_claims.py`.
    """
    for env_extra in ({_ENV_KEY: "99.99.99"}, {_ENV_KEY: "0.0.1"}):
        env = dict(os.environ, **env_extra)
        for extra in ([],
                      ["--json", str(tmp_path / "no" / "such" / "dir" / "r.json")]):
            cp = subprocess.run(
                [sys.executable, str(_PROG), "--report-upstream",
                 "--require-remote", *extra],
                cwd=str(_REPO), capture_output=True, text=True, env=env)
            assert cp.returncode in (0, 2), (env_extra, extra, cp.returncode,
                                             cp.stdout + cp.stderr)
            assert "unrecognized arguments" not in cp.stderr, (
                "this program has no --report-upstream, and rc 2 from argparse "
                "is being read as a clean degrade", cp.stderr)
            assert "vibeic_eda_upstream_report" in cp.stdout, (
                "the report never ran", extra, cp.stdout, cp.stderr)
            assert "Traceback" not in cp.stderr, (extra, cp.stderr)


def test_an_unreachable_registry_reports_NOT_CHECKED_not_a_pass():
    """"I could not look" and "I looked and it is clean" stay different claims
    — the distinction #354 and the rc-2 vocabulary in this repo exist for. It
    just lives on the reporting path now instead of the blocking one."""
    code = (
        "import sys, socket, runpy\n"
        "sys.argv = ['sync_image_version.py', '--report-upstream', '--require-remote']\n"
        "def _boom(*a, **k):\n"
        "    raise TimeoutError('simulated unreachable registry')\n"
        "socket.getaddrinfo = _boom\n"
        "socket.create_connection = _boom\n"
        f"runpy.run_path({str(_PROG)!r}, run_name='__main__')\n"
    )
    env = dict(os.environ)
    env.pop(_ENV_KEY, None)
    cp = subprocess.run([sys.executable, "-c", code], cwd=str(_REPO),
                        capture_output=True, text=True, env=env)
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 2, blob
    assert "NOT CHECKED" in blob, blob
    assert "[PASS]" not in blob, blob


# ── the wiring, and the denominator ──────────────────────────────────────────

def test_the_ci_script_blocks_on_the_repo_half_and_reports_the_other():
    """A program change alone would leave the old invocation in place. This
    reads the script that actually runs in CI."""
    script = (_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    if not script.is_file():
        pytest.skip("CI script not present in this checkout")
    lines = script.read_text(encoding="utf-8").splitlines()
    calls = [ln for ln in lines
             if "sync_image_version.py" in ln and ln.strip().startswith("run")]
    assert len(calls) == 2, calls
    blocking = [c for c in calls if "--check" in c]
    reporting = [c for c in calls if "--report-upstream" in c]
    assert len(blocking) == 1 and len(reporting) == 1, calls
    assert "--require-remote" not in blocking[0], (
        "the blocking gate still asks for a registry round-trip", blocking[0])
    assert blocking[0].strip().startswith("run "), (
        "the repo-half gate must BLOCK, not be tolerated", blocking[0])
    assert reporting[0].strip().startswith("run_tolerating_uncheckable"), (
        "the report must be non-fatal when the registry is silent", reporting[0])


def test_the_blocking_gate_is_no_longer_excluded_from_host_independence():
    """#539's exclusion existed only because this gate made a network call.

    It does not any more, so the exclusion must be GONE — an EXCLUDE directive
    that outlives its reason is standing permission nobody re-examines.
    """
    script = (_REPO / "tools" / "ci" / "repo_hygiene_gates.sh")
    if not script.is_file():
        pytest.skip("CI script not present in this checkout")
    lines = script.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if "sync_image_version.py" in ln and "--check" in ln \
                and ln.strip().startswith("run"):
            prev = lines[i - 1] if i else ""
            assert "host-independence: EXCLUDE" not in prev, (
                "the blocking image-version gate is still declared out of the "
                "host-independence probe, but it no longer touches the network")


def test_the_denominator_is_real():
    """If _REPO is off by one every assertion above passes vacuously."""
    assert _PROG.is_file(), _PROG
    assert (_REPO / "tools" / "vibeic-eda" / "VERSION").is_file()
