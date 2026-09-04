"""NOT_VERIFIED — the test tier's equivalent of the gate tier's NOT_CHECKED.

    "13 tests stopped verifying and the run still said green." (vibe-ic#1128)

WHAT THIS IS ABOUT, IN ONE SENTENCE
===================================
A test that cannot reach the tool it verifies with has NOT answered its
question, and `pytest.skip` files that non-answer under the same heading as a
pass: the summary line says ``1401 passed`` and nothing in the aggregate says
that thirteen verifications did not happen.

THE MESSAGES WERE ALREADY HONEST — THE DEFECT IS ONE LEVEL UP
=============================================================
Every one of the eleven skip sites this module was written for already says the
true thing at the point it happens::

    image ghcr.io/vibeic/vibeic-eda:0.2.96 not present; this half was NOT checked
    /foss/pdks/asap7/libs.tech/klayout/lvs/asap7.lyt not reachable — this half was NOT checked

Nobody has to be told those are honest; they are. What is missing is a tier
that stops the ROLL-UP from reading them as passes. ``_gate_dispatch.sh``
already made exactly this repair for gates: ``NOT_CHECKED`` is a state of its
own, is never folded into the passed count, and is named in the run's own
summary. The test tier had no equivalent, so this is that equivalent and
nothing more — it invents no new judgement, it only refuses to let an
unanswered question be counted as an answered one.

MEASURED (2026-08-12, clean detached `origin/main` @ `94754771`, the six files
vibe-ic#1128 names), same tree, two arms; arm 2 puts an ``exit 127`` shim ahead
of ``docker`` on ``PATH``::

    image reachable      69 passed,  3 skipped     rc 0
    image unreachable    56 passed, 16 skipped     rc 0

Thirteen verifications moved from `passed` into `skipped` and the run stayed
green in both arms. That is the whole defect: **rc 0 is identical either way.**

WHY A SKIP COUNT ALONE CANNOT BE THE CHECK
==========================================
The obvious cheap fix — "assert the landing run has zero skips" — is wrong, and
measurably so. The reachable arm above already has THREE skips, and repo-wide
the figure vibe-ic#1128 measured is 44. A skip is not one thing:

  * "there is nothing here to verify" — a genuine N/A, and green is correct;
  * "I could not reach what I verify WITH" — an unanswered question wearing
    green.

Only the second is this module's subject. Distinguishing them by matching the
reason text would be the same defect one layer down — a guard that believes a
string it did not author — so the second class is DECLARED, at the skip site,
by calling :func:`skip_not_verified` instead of ``pytest.skip``. That is the
same shape as ``run_tolerating_uncheckable`` / ``run_mutating_the_tree`` in the
gate tier: the honest state is available, and reaching it is a visible act.

A declaration that can be forgotten rots, so it is not left to memory:
``test_not_verified_tier.py`` walks the test corpus with the AST and fails on
any `pytest.skip` whose reason names the EDA image, a container, docker or a
`/foss` path and which did NOT come through this module.

BLOCKING IS OPT-IN, AND NOT BLOCKING IS ANNOUNCED
=================================================
``VIBEIC_REQUIRE_EDA_VERIFICATION=1`` makes a non-zero NOT_VERIFIED count fail
the session. It is off by default and that is a deliberate, stated choice
rather than timidity:

  * on a host with the image PULLED AND A CONTAINER RUNNING the count is 0, so
    blocking costs nothing;
  * on this host with the image pulled but no container running it is 3
    (``test_synth_frontend_shared.py``), because "present" and "running" are
    different requirements — so defaulting to blocking would redden a developer
    machine for a reason that is about provisioning, not about the commit.

What is NOT optional is the disclosure. The summary block prints on every run
with a non-zero count, and when the run is not enforcing it says so in the same
breath — a guard that can be off and does not say it is off is the vacuous pass
this repository keeps removing.

WHAT TRIGGERS IT IN PRACTICE: THE IMAGE THIS HOST HAS
=====================================================
This is not background flakiness. It is decided by whether the host holds a
vibeic-eda image at all — measured in vibe-ic#1088 as 2 SKIPPED before the pull
and 12 passed / 0 skipped after, on one unchanged tree.

It used to be worse in a way worth recording, because the shape recurs. Two of
the sites pinned the CURRENT ANCHOR LITERAL, read from `tools/vibeic-eda/VERSION`
— vibeic-eda's version number kept in this repo — so the day that file moved,
every host that had not yet pulled the new TAG silently stopped running them. A
version number nobody had pulled turned a passing test into a skip with no
change to the test. The anchor is gone; the image is now identified by the DIGEST
of what the host actually has (`_eda_image.judged_image`), which cannot go stale
against itself. The skip that remains means the host has no image, which is a
true fact about the host and is what this tier is for.

THE THIRD STATE: A PROBE THAT NEVER ANSWERED (vibe-ic#1283)
===========================================================
Everything above is about a skip whose CAUSE was established: the probe ran,
the image was not there. #1283 measured the case where the probe itself does
not finish — `docker image inspect` reads local metadata and normally answers
in milliseconds, but under fleet load (37+ concurrent heavy processes measured)
it blows a 30s budget. Every site caught that with a bare ``except Exception``
and returned ``False``, so a probe that COULD NOT LOOK was filed as a probe
that LOOKED AND FOUND NOTHING, under the reason "container not available" —
a statement about the container the probe never established.

Measured 2026-08-15, clean detached ``origin/main`` @ ``1adbf3444``, on a host
where ``docker exec vibeic-eda true`` returns 0 (the container IS running),
``programs/tests/test_v1_4_observable_capability_probes.py``, same tree, same
command, only ``docker`` on PATH replaced by a shim that never answers::

    real docker      37 passed              rc 0
    slow shim        32 passed, 5 skipped   rc 0
                     SKIPPED ... vibeic-eda container not available

The skip reason is FALSE in the second arm — the container was up the whole
time — and rc 0 is identical either way, so the run reports green having made
five fewer assertions. That is the same conflation the gate tier already
rejects (``NOT_CHECKED`` is not ``PASS`` and is not ``FAIL``), so the repair is
routing, not new machinery: :func:`probe` returns three states instead of a
bool, and :func:`probe_skip_reason` refuses to say "not available" about
something it did not manage to look at.

WHY NOT JUST RAISE THE BUDGET
=============================
The budget IS raised — to :data:`PROBE_TIMEOUT_S`, the harness ceiling of
``180 // 3`` — but a bound is not the fix. #1283's own comments record a 60s
bound with a 9x margin flipping under contention, so any budget can lose the
race; what must not happen is that losing it is recorded as a finding. And the
answer is memoised per argv, so a session pays a saturated host's worst case
ONCE rather than once per probe site, and cannot report two different answers
about one container to two collection sites in the same run.
"""
from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple

#: Prefix stamped onto a declared "I could not verify" skip reason. Read back
#: out of pytest's own report object rather than re-derived, so the tier cannot
#: disagree with what the reader was shown.
SENTINEL = "NOT_VERIFIED:"

#: Env var that turns the disclosure into a refusal. Named for what it asserts
#: about the HOST, not for what it does to the run.
REQUIRE_ENV = "VIBEIC_REQUIRE_EDA_VERIFICATION"

#: The three outcomes of an infrastructure probe (vibe-ic#1283). The middle one
#: is the whole point: ABSENT is a FINDING about the host, UNANSWERED is the
#: absence of a finding, and collapsing them into one bool is what let a
#: timed-out probe publish "container not available" about a running container.
PROBE_PRESENT = "PRESENT"
PROBE_ABSENT = "ABSENT"
PROBE_UNANSWERED = "UNANSWERED"

#: Stamped into the reason of a skip caused by a probe that never answered, so
#: the roll-up can separate the two classes without parsing prose.
UNANSWERED_MARK = "PROBE UNANSWERED"

#: Budget for one probe subprocess. 60 == 180 // 3, the ceiling this repo's
#: harness (``--timeout=180 --timeout-method=thread``) allows an inner bound;
#: it is a ceiling, NOT a guarantee, which is why exceeding it routes to
#: :data:`PROBE_UNANSWERED` instead of to a verdict.
PROBE_TIMEOUT_S = 60

#: argv -> (state, detail), for the session. See "WHY NOT JUST RAISE THE BUDGET".
_PROBE_CACHE: Dict[Tuple[str, ...], Tuple[str, str]] = {}


def blocking() -> bool:
    """True when this run refuses to be green over an unanswered question."""
    return os.environ.get(REQUIRE_ENV, "").strip() == "1"


def skip_not_verified(reason: str, remedy: str = "") -> None:
    """Skip, declaring that a VERIFICATION did not happen — not that it passed.

    Use instead of ``pytest.skip`` whenever the reason the test cannot run is
    that the thing it verifies WITH is out of reach: the EDA image, a running
    container, a PDK file inside one. *remedy* is the command that would make
    the run answerable, and it is part of the contract rather than a nicety —
    the failure mode this tier exists for is a host that quietly has no image,
    and "pull this image" is the whole fix.
    """
    import pytest  # local: the substrate stays importable without pytest

    text = f"{SENTINEL} {reason}"
    if remedy:
        text = f"{text} — remedy: {remedy}"
    pytest.skip(text)


def not_verified_reason(reason: str, remedy: str = "") -> str:
    """The same declaration, for ``@pytest.mark.skipif(..., reason=...)``.

    Two of the eleven sites are decorators, not calls — a decorator is
    evaluated at COLLECTION time and cannot raise `Skipped` from inside a test
    body, so it needs the stamp on the reason STRING instead. Same sentinel,
    same reader, so the tier does not care which spelling a site used.
    """
    text = f"{SENTINEL} {reason}"
    return f"{text} — remedy: {remedy}" if remedy else text


def _reap_group(pid) -> None:
    """SIGKILL the process group *pid* leads, when it leads one.

    THE `pgid == pid` GUARD IS THE WHOLE SAFETY ARGUMENT. `os.getpgid(pid)` of
    a child that is NOT its own session leader returns THIS process's group,
    and signalling that group kills the caller. It is asked, not assumed: the
    signal goes out only when the child leads its own group, which is exactly
    what `start_new_session=True` made it and what a stubbed or foreign object
    will not be.

    Everything the OS refuses -- an already-reaped pid, a platform without
    `killpg` -- is silently nothing. This is best-effort cleanup AFTER a bound
    that has already fired and decided the answer; it must never turn an
    UNANSWERED probe into an exception.
    """
    import os
    import signal
    if not isinstance(pid, int) or pid <= 0:
        return
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGKILL)
    except (OSError, AttributeError, ValueError):  # nosec
        pass


def probe(argv: Sequence[str], timeout: int = PROBE_TIMEOUT_S,
          use_cache: bool = True) -> Tuple[str, str]:
    """Ask the host a yes/no question and allow it to answer "I did not answer".

    Returns ``(state, detail)`` where *state* is one of :data:`PROBE_PRESENT`,
    :data:`PROBE_ABSENT`, :data:`PROBE_UNANSWERED` and *detail* is the text a
    reader needs to act on the non-present cases.

    The routing, and the reason for each arm:

    * executable not on PATH -> **ABSENT**. "there is no docker on this host"
      is an established fact about the host, not a failure to look.
    * the command exits 0 -> **PRESENT**.
    * the command exits non-zero -> **ABSENT**. The probe RAN and reported.
    * :class:`subprocess.TimeoutExpired` -> **UNANSWERED**. The image may well
      be there; nothing was learned. This is the arm vibe-ic#1283 is about.
    * :class:`OSError` (fork/exec refused — the same saturated host, one layer
      down) -> **UNANSWERED**, for the same reason.

    No other exception is caught. A bare ``except Exception`` here would put
    back exactly the swallow this function exists to remove.
    """
    import shutil
    import subprocess

    key = tuple(argv)
    if use_cache and key in _PROBE_CACHE:
        return _PROBE_CACHE[key]

    printed = " ".join(argv)
    if shutil.which(argv[0]) is None:
        out = (PROBE_ABSENT, f"`{argv[0]}` is not on PATH")
    else:
        try:
            # POPEN + `start_new_session=True`, AND THE GROUP REAP BELOW.
            #
            # `subprocess.run(argv, timeout=N)` kills the DIRECT child when the
            # bound fires and nothing below it. A probed command that is itself
            # a wrapper therefore leaves its work running: `sh -c 'sleep 30'`
            # loses the `sh` and keeps the `sleep`, reparented to init.
            #
            # MEASURED at b309595f06, in the pinned image, this file's own
            # end-to-end arms driving a `docker` shim of exactly that shape --
            # after `1 failed, 16 passed in 20.81s`, `ps -eo pid,ppid,args`:
            #
            #     PID  PPID  ELAPSED  COMMAND
            #      32     1       19  sleep 30
            #      37     1       18  sleep 30
            #
            # Two orphans outliving the session that made them. Under the
            # per-file landing driver, which owns the complete descendant tree,
            # that is "pytest exited with unfinished live descendants" and the
            # WHOLE file's result is UNKNOWN however its assertions went.
            #
            # `run` cannot be repaired in place: `TimeoutExpired` carries
            # `cmd`/`timeout`/`output`/`stderr` and NO pid, so the form that
            # raises it cannot name the group it has to reap. Popen is used for
            # that one reason; the bound, the capture and the three-way routing
            # below are what they were.
            with subprocess.Popen(list(argv), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE,
                                  start_new_session=True) as child:
                try:
                    child.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _reap_group(child.pid)
                    child.kill()
                    child.communicate()
                    raise
                returncode = child.returncode
        except subprocess.TimeoutExpired:
            out = (PROBE_UNANSWERED,
                   f"`{printed}` did not answer within {timeout}s")
        except OSError as exc:                             # pragma: no cover
            out = (PROBE_UNANSWERED, f"`{printed}` could not be run: {exc}")
        else:
            out = ((PROBE_PRESENT, "") if returncode == 0
                   else (PROBE_ABSENT, f"`{printed}` exited {returncode}"))

    if use_cache:
        _PROBE_CACHE[key] = out
    return out


def probe_skip_reason(state: str, detail: str, absent_reason: str,
                      remedy: str = "") -> str:
    """The skip reason a :func:`probe` outcome earns — ``""`` when PRESENT.

    *absent_reason* is the site's own sentence about the host, and it is used
    ONLY for :data:`PROBE_ABSENT`, because that is the only state in which the
    site is entitled to make a claim about the host. An UNANSWERED probe gets a
    reason that says what actually happened and a remedy that does not send the
    reader to pull an image they may already have.
    """
    if state == PROBE_PRESENT:
        return ""
    if state == PROBE_UNANSWERED:
        # *absent_reason* is deliberately NOT quoted here. Repeating the claim
        # even to deny it puts the sentence back into the run's output, where
        # the next reader greps it — the whole cost of #1283 was a true-looking
        # string, not a wrong boolean.
        return not_verified_reason(
            f"{UNANSWERED_MARK} — {detail}. The probe lost a race (typically "
            f"host load); NOTHING was established about what this test "
            f"verifies WITH, so this is NOT a finding that it is missing",
            "re-run this file on a host that is not saturated")
    return not_verified_reason(absent_reason, remedy)


def _collect(terminalreporter) -> List[Tuple[str, str]]:
    """``[(nodeid, reason)]`` for every skip this module declared."""
    out: List[Tuple[str, str]] = []
    for rep in terminalreporter.stats.get("skipped", []):
        reason = ""
        longrepr = getattr(rep, "longrepr", None)
        if isinstance(longrepr, tuple) and len(longrepr) == 3:
            reason = str(longrepr[2])
        elif longrepr is not None:
            reason = str(longrepr)
        if SENTINEL in reason:
            out.append((getattr(rep, "nodeid", "<unknown>"), reason))
    return out


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: D401
    """Name every unanswered question, and say whether this run refuses them."""
    found = _collect(terminalreporter)
    if not found:
        return
    w = terminalreporter.write_line
    by_reason: Dict[str, int] = {}
    for _nodeid, reason in found:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    w("")
    w(f"[NOT VERIFIED] {len(found)} test(s) did NOT run their verification "
      f"because what they verify WITH was out of reach. These are NOT passes; "
      f"pytest's own summary counts them under `skipped`, which is why this "
      f"block exists (vibe-ic#1128).")
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        w(f"    {n:>3} x {reason}")
    # vibe-ic#1283 — the two classes above are NOT the same evidence, and a
    # reader who is told only "N not verified" cannot act on the difference:
    # an ABSENT image is fixed by pulling it, an UNANSWERED probe is fixed by
    # re-running somewhere quieter and may be hiding a host that was fine.
    unanswered = [n for n, r in found if UNANSWERED_MARK in r]
    if unanswered:
        w(f"[PROBE UNANSWERED] {len(unanswered)} of those {len(found)} did not "
          f"even establish that anything was out of reach — the probe itself "
          f"never answered, so 'not available' is NOT what was measured "
          f"(vibe-ic#1283). Re-run these on a quiet host before believing "
          f"either the skip or the green:")
        for nodeid in unanswered:
            w(f"    {nodeid}")
    if blocking():
        w(f"[NOT VERIFIED] {REQUIRE_ENV}=1 — this run REFUSES to be green over "
          f"an unanswered question, so the session fails.")
    else:
        w(f"[NOT VERIFIED] {REQUIRE_ENV} is not set, so this run is REPORTING "
          f"and NOT blocking. The count above is real either way — a landing "
          f"host sets {REQUIRE_ENV}=1 to refuse it.")


def pytest_sessionfinish(session, exitstatus):
    """Turn the disclosure into a refusal when the run asked for one.

    Set on ``session`` rather than returned: pytest reads the attribute back
    after every plugin has had its say, so this composes with other hooks
    instead of racing them. Only ever makes a green run red — an already-failing
    session keeps its own status, because "the tests failed" is the more
    specific statement and this must not overwrite it.
    """
    if exitstatus != 0 or not blocking():
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:                                  # pragma: no cover
        return
    if _collect(reporter):
        session.exitstatus = 1
