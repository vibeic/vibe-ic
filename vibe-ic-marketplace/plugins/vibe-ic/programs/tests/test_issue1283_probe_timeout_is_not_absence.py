"""A probe that could not look must not report that it looked. vibe-ic#1283.

WHAT WAS MEASURED, AND WHY A SKIP COUNT IS NOT THE SUBJECT
==========================================================
Four test files gated on a docker probe shaped like this::

    try:
        r = subprocess.run(["docker", "image", "inspect", IMAGE],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False

`TimeoutExpired` is an `Exception`, so a probe that never finished returned the
same `False` as a probe that finished and found nothing — and the reason string
then told the reader "container not available", which is a claim about the host
the probe never established.

Measured 2026-08-15 on clean detached `origin/main` @ `1adbf3444`, this host,
`programs/tests/test_v1_4_observable_capability_probes.py`, same tree, same
command, `--timeout=180 --timeout-method=thread`; the only difference is
whether `docker` on PATH answers::

    ground truth:  docker exec vibeic-eda true  ->  rc 0   (the container IS up)

    real docker                       37 passed                rc 0
    shim that never answers           32 passed, 5 skipped     rc 0
        SKIPPED ... vibeic-eda container not available

Five assertions evaporated, the reason given for it was FALSE, and rc 0 is
identical either way. That is the defect: not the skip, but the claim.

WHAT THIS FILE PINS
===================
1. `probe` is TRI-STATE and each arm routes where it belongs — in particular a
   `TimeoutExpired` is `UNANSWERED`, never `ABSENT`. This is the whole fix in
   one assertion; if it inverts, everything downstream is a lie again.
2. `probe_skip_reason` refuses to repeat the site's sentence about the host
   when nothing about the host was established.
3. END TO END, in a real child pytest session driven by a `docker` shim that
   never answers: the skip says PROBE UNANSWERED, the roll-up names it in its
   own block, and `VIBEIC_REQUIRE_EDA_VERIFICATION=1` REDDENS the session
   instead of letting it be green. A tier that cannot make this red is wired
   where it can never block.
4. THE ROT GUARD, and the reason it is here rather than in a review checklist:
   the shape above is four keystrokes to write and reads as ordinary defensive
   code. The corpus is walked with the AST; the four converted files carry
   ZERO sites and a relapse in any of them FAILS. It is a shrink-only ratchet
   rather than a ban because the detector found the class is FOUR TIMES what
   the issue counted — 16 sites, 12 of them a different (container-discovery)
   shape whose remedies are per-site — and the reasoning for recording rather
   than guessing is on `RESIDUAL_SWALLOWING`. Its paired control plants the
   pre-fix shape and proves the detector sees it: an inventory that cannot
   fire is the same vacuous pass this issue is about, one level up.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROGRAMS = TESTS_DIR.parent
sys.path.insert(0, str(PROGRAMS))
import not_verified_tier as NV  # noqa: E402
import _watchdog  # noqa: E402


# ---------------------------------------------------------------------------
# 1. the three states, and which input earns which
# ---------------------------------------------------------------------------
class _FakeChild:
    """The narrowest object `probe` uses: a context manager whose
    `communicate(timeout=)` either answers or raises, plus the `pid`/`kill`
    the reap path touches.

    `pid = 0` IS DELIBERATE. `_reap_group` refuses a non-positive pid before it
    asks the OS anything, so a stubbed timeout exercises the real reap call
    without any signal reaching any process on the host.
    """

    pid = 0

    def __init__(self, argv, kw, outcome):
        self._argv, self._kw, self._outcome = argv, kw, outcome
        self.returncode = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def communicate(self, timeout=None):
        if timeout is not None:
            self.returncode = self._outcome(self._argv, timeout=timeout,
                                            **self._kw)
        return (b"", b"")

    def kill(self):
        pass


def _probe_with(monkeypatch, outcome):
    """Drive `probe` with a stubbed child process, caching disabled.

    THE INJECTION POINT MOVED FROM `subprocess.run` TO `subprocess.Popen`, and
    only the injection point moved: every assertion below is unchanged, because
    what they pin is the ROUTING of an outcome to a state, not which stdlib
    call produced the outcome. `probe` had to stop using `subprocess.run`
    because `TimeoutExpired` carries no pid and so the `run` form cannot reap
    the group a timed-out probe leaves behind — see `not_verified_tier.probe`.
    """
    def fake_popen(argv, **kw):
        return _FakeChild(argv, {}, outcome)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("shutil.which", lambda exe: "/usr/bin/" + exe)
    return NV.probe(["docker", "image", "inspect", "some/image:1"],
                    timeout=7, use_cache=False)


def test_a_probe_that_timed_out_is_UNANSWERED_not_ABSENT(monkeypatch):
    """The one assertion the whole issue reduces to."""
    def timeout(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    state, detail = _probe_with(monkeypatch, timeout)
    assert state == NV.PROBE_UNANSWERED, (
        "a probe that never answered was filed as a finding about the host — "
        "this is exactly the conflation vibe-ic#1283 measured, restored")
    assert state != NV.PROBE_ABSENT
    assert "7s" in detail, detail


def test_a_probe_that_answered_nonzero_IS_ABSENT(monkeypatch):
    """The paired half. If a real absence also became UNANSWERED the fix would
    have bought its honesty by refusing to answer anything, which is worse."""
    state, _detail = _probe_with(monkeypatch, lambda argv, **kw: 1)
    assert state == NV.PROBE_ABSENT


def test_a_probe_that_answered_zero_is_PRESENT(monkeypatch):
    state, detail = _probe_with(monkeypatch, lambda argv, **kw: 0)
    assert (state, detail) == (NV.PROBE_PRESENT, "")


def test_no_docker_on_the_host_is_an_established_ABSENCE(monkeypatch):
    """"there is no docker here" IS a fact about the host, so it is a finding,
    not a failure to look — the distinction has to cut both ways to mean
    anything."""
    monkeypatch.setattr("shutil.which", lambda exe: None)
    state, detail = NV.probe(["docker", "ps"], use_cache=False)
    assert state == NV.PROBE_ABSENT
    assert "not on PATH" in detail


def test_a_probe_that_could_not_be_spawned_is_UNANSWERED(monkeypatch):
    """The same saturated host one layer down: fork/exec refused. Nothing was
    learned about the image, so nothing may be reported about it."""
    def oserror(argv, **kw):
        raise OSError(11, "Resource temporarily unavailable")

    state, _detail = _probe_with(monkeypatch, oserror)
    assert state == NV.PROBE_UNANSWERED


def test_the_probe_budget_respects_the_harness_ceiling():
    """`--timeout=180 --timeout-method=thread` / 3. A bound above this cannot
    be reported by the session that owns it."""
    assert NV.PROBE_TIMEOUT_S <= 60, NV.PROBE_TIMEOUT_S


def test_one_session_gets_one_answer_per_probe(monkeypatch):
    """Memoised per argv: a saturated host costs the session ONE worst case,
    and two collection sites cannot be told different things about one
    container in the same run."""
    calls = []

    def counting(argv, **kw):
        calls.append(tuple(argv))
        return 0

    monkeypatch.setattr(
        subprocess, "Popen",
        lambda argv, **kw: _FakeChild(argv, {}, counting))
    monkeypatch.setattr("shutil.which", lambda exe: "/usr/bin/" + exe)
    argv = ["docker", "exec", "cache-probe-fixture", "true"]
    first = NV.probe(argv)
    second = NV.probe(argv)
    assert first == second == (NV.PROBE_PRESENT, "")
    assert len(calls) == 1, calls


# ---------------------------------------------------------------------------
# 2. the reason a probe outcome earns
# ---------------------------------------------------------------------------
ABSENT_CLAIM = "vibeic-eda container not available"


def test_an_UNANSWERED_probe_does_not_publish_the_sites_claim():
    reason = NV.probe_skip_reason(NV.PROBE_UNANSWERED,
                                  "`docker image inspect x` did not answer "
                                  "within 60s",
                                  ABSENT_CLAIM, "pull it")
    assert NV.SENTINEL in reason, reason
    assert NV.UNANSWERED_MARK in reason, reason
    assert "did not answer within 60s" in reason, reason
    assert "NOT a finding" in reason, reason
    # The claim itself must not appear — not even to be denied. The cost of
    # #1283 was a true-looking string in the output, and a reader who greps
    # for it cannot tell an assertion from a denial.
    assert ABSENT_CLAIM not in reason, reason
    # The remedy must not be "pull the image": the image may already be there.
    assert "pull it" not in reason, (
        "an unanswered probe sent the reader to the ABSENT remedy, which is "
        f"advice derived from a fact that was never established\n{reason}")


def test_an_ABSENT_probe_publishes_exactly_the_sites_claim():
    reason = NV.probe_skip_reason(NV.PROBE_ABSENT, "exited 1",
                                  ABSENT_CLAIM, "pull it")
    assert reason == NV.not_verified_reason(ABSENT_CLAIM, "pull it"), reason
    assert NV.UNANSWERED_MARK not in reason, reason


def test_a_PRESENT_probe_earns_no_reason_at_all():
    assert NV.probe_skip_reason(NV.PROBE_PRESENT, "", ABSENT_CLAIM, "x") == ""


# ---------------------------------------------------------------------------
# 3. END TO END — a real child session, a shim that never answers
# ---------------------------------------------------------------------------
_CHILD = textwrap.dedent(
    """\
    import sys
    sys.path.insert(0, {programs!r})
    import pytest
    from not_verified_tier import PROBE_PRESENT, probe, probe_skip_reason

    STATE, DETAIL = probe(["docker", "image", "inspect", "some/image:1"],
                          timeout=1, use_cache=False)

    @pytest.mark.skipif(STATE != PROBE_PRESENT,
                        reason=probe_skip_reason(
                            STATE, DETAIL, {claim!r},
                            "bash tools/vibeic-eda/restart-eda.sh"))
    def test_image_gated():
        assert True
    """)


def _child_session(tmp_path, docker_script: str, env_extra=None):
    """Run a one-file pytest session with `docker` on PATH replaced."""
    bind = tmp_path / "bin"
    bind.mkdir(exist_ok=True)
    shim = bind / "docker"
    shim.write_text(docker_script)
    shim.chmod(0o755)

    test = tmp_path / "test_child_probe.py"
    test.write_text(_CHILD.format(programs=str(PROGRAMS), claim=ABSENT_CLAIM))

    env = dict(os.environ)
    env["PATH"] = f"{bind}{os.pathsep}{env['PATH']}"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PROGRAMS)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.pop(NV.REQUIRE_ENV, None)
    env.update(env_extra or {})
    cmd = [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:randomly",
           "-p", "not_verified_tier", str(test)]
    # No wall-clock bound on the child. The child's OWN 1 s probe budget is the
    # subject here (the fixtures are named `_SLOW`/`_ABSENT` for it), and a 60 s
    # bound on the pytest session that carries it decides nothing about that —
    # it only decides whether THIS host got the session finished, and reports a
    # slow host as the probe tier being broken.
    return _watchdog.completed_process(
        cmd, _watchdog.run_host_supervised(cmd, cwd=str(tmp_path), env=env))


#: never answers within the child's 1s budget -> the probe is UNANSWERED
_SLOW = "#!/bin/sh\nsleep 30\n"
#: answers immediately, non-zero -> the image is genuinely ABSENT
_ABSENT = "#!/bin/sh\nexit 1\n"


def test_a_timed_out_probe_reports_UNANSWERED_and_not_absence(tmp_path):
    res = _child_session(tmp_path, _SLOW)
    out = res.stdout + res.stderr
    assert NV.UNANSWERED_MARK in out, out
    assert "[PROBE UNANSWERED]" in out, (
        "the roll-up folded an unestablished cause in with the established "
        f"ones, so the reader cannot tell them apart\n{out}")
    assert ABSENT_CLAIM not in out, (
        "the run still asserted that the container is not available, having "
        f"never managed to look at it\n{out}")


def test_a_genuine_absence_still_reports_the_absence(tmp_path):
    """The direction that keeps the fix from being a mute button: when the
    probe DOES answer and the thing is missing, the site's own sentence must
    still be published, unchanged."""
    res = _child_session(tmp_path, _ABSENT)
    out = res.stdout + res.stderr
    assert ABSENT_CLAIM in out, out
    assert NV.UNANSWERED_MARK not in out, out
    assert "[PROBE UNANSWERED]" not in out, out


def test_the_unanswered_skip_can_redden_a_landing_run(tmp_path):
    """`VIBEIC_REQUIRE_EDA_VERIFICATION=1` is how a landing host refuses an
    unanswered question. If the new class did not reach the tier, this run
    would be green — which is the pre-#1283 behaviour exactly."""
    res = _child_session(tmp_path, _SLOW, {NV.REQUIRE_ENV: "1"})
    out = res.stdout + res.stderr
    assert res.returncode != 0, (
        "a probe that never answered left a landing run GREEN\n" + out)
    assert "REFUSES to be green" in out, out


def test_the_same_run_is_green_when_the_probe_answers(tmp_path):
    """Paired control for the one above: blocking must cost nothing on a host
    where the probe works, or the refusal is just noise."""
    res = _child_session(tmp_path, "#!/bin/sh\nexit 0\n",
                         {NV.REQUIRE_ENV: "1"})
    assert res.returncode == 0, res.stdout + res.stderr


# ---------------------------------------------------------------------------
# 4. THE ROT GUARD — no probe may swallow its own timeout again
# ---------------------------------------------------------------------------
def _swallowing_probe_sites(directory: Path):
    """`[(file, lineno)]` for every function that runs a bounded `docker`
    subprocess and catches the bound with a blanket handler.

    Deliberately narrow, and the narrowness is stated rather than assumed: it
    fires only when all three are present in ONE TRY statement — a
    `subprocess.run` (or `.run`) call, a `timeout=` on it, a literal naming
    `docker`, and that try's own `except Exception:`/bare `except:` that does
    not re-raise. Merely putting an unrelated broad handler later in the same
    function must not splice two exception domains together. A blanket
    handler around something that is not a bounded docker probe is out of
    scope here; this is #1283's shape, not a general lint.
    """
    hits = []
    for path in sorted(directory.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:                                # pragma: no cover
            continue
        for try_node in ast.walk(tree):
            if not isinstance(try_node, (ast.Try, ast.TryStar)):
                continue

            # Only calls inside THIS try's protected body can be caught by its
            # handlers.  Walking the whole function used to pair a bounded
            # docker probe in one try with a broad handler around a different
            # operation in a later try (vibe-ic#1962), inventing a swallowing
            # site that did not exist.
            bounded_docker = False
            for statement in try_node.body:
                for call in ast.walk(statement):
                    if not isinstance(call, ast.Call):
                        continue
                    name = (call.func.attr
                            if isinstance(call.func, ast.Attribute)
                            else getattr(call.func, "id", ""))
                    if name != "run":
                        continue
                    if not any(k.arg == "timeout" for k in call.keywords):
                        continue
                    if any(isinstance(c, ast.Constant)
                           and isinstance(c.value, str) and "docker" in c.value
                           for c in ast.walk(call)):
                        bounded_docker = True
            if not bounded_docker:
                continue
            for h in try_node.handlers:
                caught = (getattr(h.type, "id", "") if h.type is not None
                          else "<bare>")
                if caught not in ("Exception", "BaseException", "<bare>"):
                    continue
                if any(isinstance(n, ast.Raise) for n in ast.walk(h)):
                    continue
                hits.append((path.name, h.lineno))
    return hits


#: The residual this repair did NOT convert, per file, MEASURED 2026-08-15 with
#: the detector above on `origin/main` @ `1adbf3444` after converting the four
#: PRESENCE probes vibe-ic#1283 names: **12 sites across 8 files**.
#:
#: WHY A RESIDUAL. #1283 counted 2 sites; main had 4 by the time it was fixed;
#: the detector says 16. The four converted are all the same shape — a yes/no
#: probe whose bool becomes a `skipif` — and `probe`/`probe_skip_reason` is
#: exactly that shape. The twelve below are NOT: they are container DISCOVERY
#: helpers that read `docker ps` STDOUT, pick a container by name or by mount
#: table, and return a name-or-None. Threading UNANSWERED through them needs an
#: output-returning probe and a per-site decision about what None meant, and
#: several point at a DIFFERENT image with a different remedy. A wrong remedy
#: is worse than none — it sends a reader to a command that does not fix their
#: run — so they are recorded, not guessed at.
#:
#: THIS IS A RATCHET, NOT AN ALLOWLIST, same as `RESIDUAL_UNDECLARED` in
#: `test_not_verified_tier.py`. A NEW site FAILS — the frontier cannot grow. An
#: entry may only be DELETED or LOWERED as it is converted, never raised, and a
#: file that drops below its number must have the number lowered in the same
#: change, so it keeps meaning something.
RESIDUAL_SWALLOWING: dict = {
    "test_hspice_lib_ngspice_normalize.py": 2,
    "test_issue193_custom_pdk_primary_selection_ngspice.py": 2,
    "test_staged_macro_aware_synth_define.py": 1,
    "test_v1_0_52_gap1_via_analyzer_sky130_unnumbered_cut.py": 1,
}


def test_no_new_probe_swallows_its_own_timeout():
    """The frontier may only shrink.

    The four files vibe-ic#1283 names carry ZERO sites after this change and
    are absent from the inventory below, so a relapse in any of them is a NEW
    file and fails here. The shape is four keystrokes and reads as ordinary
    defensive code, which is why this is a guard rather than four edits.
    """
    seen: dict = {}
    for fname, _ln in _swallowing_probe_sites(TESTS_DIR):
        seen[fname] = seen.get(fname, 0) + 1

    new_files = sorted(set(seen) - set(RESIDUAL_SWALLOWING))
    assert not new_files, (
        "NEW file(s) run a bounded `docker` probe and catch its timeout with a "
        "blanket handler, so 'I could not look' will again be reported as 'it "
        "is not there' (vibe-ic#1283):\n"
        + "\n".join(f"    {f} ({seen[f]} site(s))" for f in new_files)
        + "\nUse `not_verified_tier.probe(...)` + `probe_skip_reason(...)`, "
          "which route a lost race to PROBE UNANSWERED instead of to a claim.")

    grew = sorted(f for f in seen
                  if f in RESIDUAL_SWALLOWING and seen[f] > RESIDUAL_SWALLOWING[f])
    assert not grew, (
        "the swallowing residual GREW in:\n"
        + "\n".join(f"    {f}: {RESIDUAL_SWALLOWING[f]} -> {seen[f]}" for f in grew)
        + "\nThis inventory is a ratchet: entries are deleted as they are "
          "converted, never raised.")

    shrunk = sorted(f for f in RESIDUAL_SWALLOWING
                    if seen.get(f, 0) < RESIDUAL_SWALLOWING[f])
    assert not shrunk, (
        "these files now carry FEWER swallowing probes than the inventory "
        "records, which is good — delete/lower their entries so the number "
        "keeps meaning something:\n"
        + "\n".join(f"    {f}: {RESIDUAL_SWALLOWING[f]} -> {seen.get(f, 0)}"
                    for f in shrunk))


def test_the_rot_guard_can_actually_fire(tmp_path):
    """An inventory that matched nothing would pass forever while the corpus
    refilled. Plant the exact pre-fix shape and prove the detector sees it —
    in a tmp dir, so the guard's own control never writes into the tree."""
    (tmp_path / "test_planted_probe.py").write_text(textwrap.dedent(
        """\
        import subprocess

        def _docker_image_available():
            try:
                r = subprocess.run(["docker", "image", "inspect", "x:1"],
                                   capture_output=True, timeout=30)
                return r.returncode == 0
            except Exception:
                return False
        """))
    hits = _swallowing_probe_sites(tmp_path)
    assert [f for f, _ln in hits] == ["test_planted_probe.py"], (
        f"the rot guard did not see the planted pre-#1283 shape: {hits}")


def test_a_bounded_probe_and_an_unrelated_broad_handler_do_not_form_one_site(
        tmp_path):
    """Exception scope, not function scope, decides what a handler catches.

    Current main's `test_issue1962_measured_pdk_analog_constants.py` has this
    exact shape: the bounded docker call catches only explicit subprocess
    failures, while a later broad handler protects per-container discovery.
    Combining them would fail the corpus ratchet on code that cannot swallow
    the probe's timeout.
    """
    (tmp_path / "test_separate_tries.py").write_text(textwrap.dedent(
        """\
        import subprocess

        def _discover():
            try:
                names = subprocess.run(
                    ["docker", "ps"], timeout=30).stdout.split()
            except (OSError, subprocess.SubprocessError):
                return []
            for name in names:
                try:
                    inspect_container(name)
                except Exception:
                    continue
            return names
        """))
    assert _swallowing_probe_sites(tmp_path) == []


def test_the_converted_sites_are_not_seen_by_the_guard():
    """The reverse: converting a site must actually silence the detector, or
    the two halves disagree and one of them is wrong."""
    converted = [
        "test_v1_4_21_dft_atpg_liberty_resolver.py",
        "test_v1_4_observable_capability_probes.py",
        "test_analog_a3_netlist_emit.py",
        "test_v1_3_52_r6_sparse_die_welltie.py",
    ]
    hit_files = {f for f, _ln in _swallowing_probe_sites(TESTS_DIR)}
    for name in converted:
        src = (TESTS_DIR / name).read_text()
        assert "probe_skip_reason(" in src, (
            f"{name} no longer routes its probe through the tier; the four "
            "sites of vibe-ic#1283 have drifted back")
        assert name not in hit_files
