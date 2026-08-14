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

WHAT TRIGGERS IT IN PRACTICE: AN ANCHOR BUMP
============================================
This is not background flakiness. Two of the sites pin the CURRENT anchor
literal, so the day `tools/vibeic-eda/VERSION` moves, every host that has not
yet pulled the new tag silently stops running them — measured in vibe-ic#1088 as
2 SKIPPED before the pull and 12 passed / 0 skipped after, on one unchanged
tree. v1.10.33 has just moved that anchor to 0.2.89, and six machines land in
parallel, so the window in which a false green is cheapest to produce and most
expensive to trust is open right now.
"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

#: Prefix stamped onto a declared "I could not verify" skip reason. Read back
#: out of pytest's own report object rather than re-derived, so the tier cannot
#: disagree with what the reader was shown.
SENTINEL = "NOT_VERIFIED:"

#: Env var that turns the disclosure into a refusal. Named for what it asserts
#: about the HOST, not for what it does to the run.
REQUIRE_ENV = "VIBEIC_REQUIRE_EDA_VERIFICATION"


def blocking() -> bool:
    """True when this run refuses to be green over an unanswered question."""
    return os.environ.get(REQUIRE_ENV, "").strip() == "1"


def skip_not_verified(reason: str, remedy: str = "") -> None:
    """Skip, declaring that a VERIFICATION did not happen — not that it passed.

    Use instead of ``pytest.skip`` whenever the reason the test cannot run is
    that the thing it verifies WITH is out of reach: the EDA image, a running
    container, a PDK file inside one. *remedy* is the command that would make
    the run answerable, and it is part of the contract rather than a nicety —
    the failure mode this tier exists for is an anchor bump nobody noticed, and
    "pull this tag" is the whole fix.
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
