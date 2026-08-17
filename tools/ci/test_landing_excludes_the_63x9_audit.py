#!/usr/bin/env python3
"""The landing gate and the 63x9 audit are two different questions. This pins that.

WHY THIS FILE EXISTS
====================
A landing asks "did this change break something that used to work". The 63x9 audit
asks "is the published audit of our 63 flow steps x 9 dimensions still honest" — it
grades a PUBLISHED ARTEFACT against a corpus. They were entangled, and it cost both:

  * the landing was REFUSED by it. A landing tree carries no corpus (benchmark-data
    left this repo in v1.10.56), so the corpus-reading assertions could not audit
    anything there. Not slow — VOID. Their permanent red refused landings that broke
    nothing. MEASURED in a corpus-less tree on the three files that carry them:
        -m audit_63x9        -> 12 failed, 35 deselected
        -m "not audit_63x9"  -> 35 passed,  12 deselected, rc=0
    12 + 35 = 47 = every test in those files, so the partition is exact and
    exhaustive: nothing was left unclassified and nothing was double-counted.

  * the audit paid too, in the direction that is easy to miss: it inherited the
    landing harness's 180 s item bound, which is why a matrix test carries
    `@pytest.mark.timeout(0)` to escape a budget that was never about it.

WHY A MARKER AND NOT A PATH, A GLOB, OR A DIRECTORY
===================================================
Three of the carrying files are MIXED. `tools/test_d9_flow_gate_reality.py` holds 6
pure unit tests of `verdict_moved()` AND 9 assertions that open the published corpus;
`test_matrix_63x8_coverage.py` holds 24 regressions and 2 audit assertions;
`test_matrix_63x8_census_freshness.py` holds 5 and 1. Any file-level split moves the
wrong tests — and moving a real regression OUT of the landing gate is the same defect
as leaving the audit IN, just pointed the other way.

The `63x8`/`d9` in a filename is the campaign that authored it, not its subject.
Measured, corpus-less: `test_matrix_63x8_ledger.py` is 51 passed in 4 s — it never
opens the corpus; it asserts that every `blocks_on` target resolves and every gate's
named program is a real file. That is a landing regression wearing a 63x8 name, and
it STAYS.

WHY THIS GUARD MUST EXIST AT ALL
=================================
A silent exclusion is how a gate goes missing for months — this repo has paid for that
more than once. So the exclusion is asserted here, in both directions:
the landing gate must really carry it, and the marked set must be exactly the set that
cannot answer without a corpus.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LAND = REPO / "tools" / "gatekeeper-land.sh"
AUDIT = REPO / "tools" / "ci" / "audit_63x9.sh"
MARKER = "audit_63x9"

#: The files that carry at least one marked assertion, and therefore the files whose
#: partition this guard is about. Named rather than globbed: a glob would grow
#: silently, and this list is exactly what was MEASURED.
CARRIERS = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_63x8_census_freshness.py",
    "tools/test_d9_flow_gate_reality.py",
)

#: MEASURED, corpus-less, on the three files above. Pinned so that a test which
#: quietly gains or loses the marker is a FAILURE here rather than a silent shift in
#: what a landing runs.
EXPECTED_MARKED = 12
EXPECTED_UNMARKED = 35


def _pytest_arms():
    """Every `python3 -m pytest` the landing gate launches, as source lines.

    Read from the script rather than assumed: the count has changed before, and a new
    arm added without the exclusion is exactly the regression this guard exists for.
    """
    body = LAND.read_text()
    arms = []
    for i, line in enumerate(body.splitlines(), 1):
        if "python3 -m pytest" in line and not line.lstrip().startswith("#"):
            arms.append((i, line))
    return body, arms


def test_the_landing_gate_launches_the_arms_we_think_it_does():
    """A guard over a set must not depend on the set having a particular size — but it
    must notice when the size changes, because a NEW arm is where the exclusion gets
    forgotten."""
    _, arms = _pytest_arms()
    # FOUR, not three: the fourth is the differential's BASE arm, added when the
    # landing gate stopped judging absolute greenness and started judging what the
    # change breaks. This assertion caught its arrival immediately and that is what
    # it is for -- a new arm is exactly where the exclusion gets forgotten, and the
    # base arm carries it too (asserted below), so the two arms compare the same
    # population. Comparing a base that ran the audit against a candidate that did
    # not would report every audit test as FIXED.
    assert len(arms) == 4, (
        "the landing gate no longer launches exactly 3 pytest arms; a new arm needs "
        f"the audit_63x9 exclusion too. Found:\n" +
        "\n".join(f"  :{n} {l.strip()[:90]}" for n, l in arms))


def test_every_landing_pytest_arm_excludes_the_audit():
    """The load-bearing assertion. Every arm must carry `-m "not audit_63x9"`."""
    body, arms = _pytest_arms()
    lines = body.splitlines()
    missing = []
    for n, line in arms:
        # the flag may sit on a continuation line; look at the whole invocation
        window = "\n".join(lines[n - 1:n + 6])
        if f'not {MARKER}' not in window:
            missing.append(f":{n} {line.strip()[:90]}")
    assert not missing, (
        "a landing pytest arm does NOT exclude the 63x9 audit, so a landing can "
        "again be refused by a question a landing tree cannot answer:\n" +
        "\n".join("  " + m for m in missing))


def test_the_audit_has_its_own_entry_point_and_it_is_executable():
    assert AUDIT.is_file(), (
        f"{AUDIT} is missing. Excluding the audit from the landing gate without "
        "leaving a way to RUN it is not a separation, it is a deletion.")
    import os
    assert os.access(AUDIT, os.X_OK), f"{AUDIT} is not executable"


def test_the_audit_entry_point_selects_by_marker_not_by_path():
    """If the runner selected by filename it would drag the 35 regressions along, and
    the two halves would be entangled again from the other side."""
    src = AUDIT.read_text()
    assert f"-m {MARKER}" in src or f'-m "{MARKER}"' in src, (
        "audit_63x9.sh does not select by marker")


def test_a_corpusless_run_of_the_audit_refuses_rather_than_failing():
    """'I could not look' and 'I looked and it is wrong' are different sentences.

    rc=2 is the first, rc=1 the second. Collapsing them is how an unscanned tree comes
    to read as a verdict.
    """
    import os
    env = dict(os.environ)
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    if (REPO / "benchmark-data").is_dir():
        pytest.skip("this checkout carries a corpus, so the refusal path is not the "
                    "one under test here")
    cp = subprocess.run(["bash", str(AUDIT)], capture_output=True, text=True,
                        # 45, not 120: the whole file is 6 passed in 2.23 s, and this call is a
        # corpus-less audit that refuses immediately. The item bound here is the
        # harness's 180 s, so ci_harness_timeout_ceiling_check holds an inner
        # bound to 180 // 3 = 60. My first draft wrote 120 and the gate caught it
        # -- which is the gate working, on the very change that separates it.
                        timeout=45, env=env, cwd=str(REPO))
    assert cp.returncode == 2, (
        f"a corpus-less audit returned {cp.returncode}, not the refusal 2\n"
        f"{cp.stdout[-600:]}{cp.stderr[-600:]}")
    assert "NOT DETERMINED" in (cp.stdout + cp.stderr)


# NO MARKER. A raised item bound has to be earned and this file has not
# earned one: MEASURED, 6 passed in 2.14 s. So it runs under the harness's
# own 180 s, and ci_harness_timeout_ceiling_check holds its inner bounds to
# 180 // 3 = 60. My drafts wrote 900 / 600 / 120 and the gate refused each --
# on the very change that separates that gate from the landing it guards.
def test_the_partition_is_exact_and_both_halves_are_what_we_measured():
    """BOTH DIRECTIONS, on the real files.

    One direction alone proves nothing: marking every test satisfies "the audit arm
    collects the audit tests", and marking none satisfies "the landing arm is green".
    Only the pair pins the split.
    """
    import os
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    files = [str(REPO / c) for c in CARRIERS]
    for c in CARRIERS:
        assert (REPO / c).is_file(), f"carrier file moved or was deleted: {c}"

    def collected(expr):
        cp = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "--collect-only", "-m", expr, *files],
            # 55, not 600. MEASURED: a --collect-only over the three carrier files
            # is part of a file that finishes in 2.23 s total. 600 was a number I
            # picked for comfort against a ceiling of 60.
            capture_output=True, text=True, timeout=55, env=env, cwd=str(REPO))
        # `<selected>/<total> tests collected (<n> deselected)` when -m filters,
        # and a bare `<total> tests collected` when it does not. TAKE THE SELECTED
        # ONE. Reading the total is measuring the proxy: this guard's own first run
        # reported "47 tests carry the marker" because 47 was the collection size,
        # not the selection — the number was real and answered a question nobody
        # asked.
        m = re.search(r"(\d+)\s*/\s*(\d+)\s+tests? collected", cp.stdout)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d+)\s+tests? collected", cp.stdout)
        assert m, (
            "could not read a collection count — a parse failure must not be read "
            f"as a count:\n{cp.stdout[-800:]}")
        return int(m.group(1))

    marked = collected(MARKER)
    unmarked = collected(f"not {MARKER}")
    assert marked == EXPECTED_MARKED, (
        f"{marked} tests carry the {MARKER} marker, expected {EXPECTED_MARKED}. "
        "A test gained or lost it, which silently changes what a landing runs.")
    assert unmarked == EXPECTED_UNMARKED, (
        f"{unmarked} tests are unmarked, expected {EXPECTED_UNMARKED}.")
    assert marked + unmarked == EXPECTED_MARKED + EXPECTED_UNMARKED, (
        "the two halves do not sum to the whole — a test is being double-counted or "
        "dropped by the marker expression")
