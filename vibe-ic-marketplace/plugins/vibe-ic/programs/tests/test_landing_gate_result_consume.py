#!/usr/bin/env python3
"""Tests for landing_gate_result_consume (the `plugin full audit` collapse).

Bidirectional by construction, because the whole risk of a consumer is that it
looks like a gate while being unable to fail. Every case that must PASS is
paired with the same record made red, and every way of NOT KNOWING is asserted
to be rc 2 rather than rc 0 — a consumer that answered "clean" to "the record
is missing" would delete a gate from the landing path while leaving its label
in the log, which is worse than deleting the line.

The wiring half matters as much as the logic half: this program is only honest
while the label it re-states is a label some suite actually produces. Those
tests read `tools/ci/repo_hygiene_gates.sh` and `tools/gatekeeper-land.sh`, so
a rename on either side is red HERE, not silently green in a landing.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent
        / "landing_gate_result_consume.py")
_REPO = PROG.parents[4]
_LAND = _REPO / "tools" / "gatekeeper-land.sh"
_HYGIENE = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

#: The one label this collapse rests on. Spelled ONCE here and asserted against
#: both scripts, so the three copies cannot drift apart in silence.
LABEL = "plugin full audit"

RC_PASS = 0
RC_FAIL = 1
RC_CANNOT = 2


def _record(tmp_path: Path, *gates, listed_only=False) -> Path:
    """A `--summary-json` record carrying exactly the gates given."""
    doc = {
        "listed_only": listed_only,
        "declared": len(gates),
        "gates": [{"label": lbl, "state": st, "seconds": 7} for lbl, st in gates],
    }
    p = tmp_path / "hygiene.json"
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p


def _run(record, label=LABEL, subject=None):
    argv = [sys.executable, str(PROG), "--record", str(record), "--gate", label]
    if subject:
        argv += ["--subject", subject]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


# ── the verdict, in both directions ─────────────────────────────────────────

def test_a_recorded_PASS_is_restated_as_a_pass(tmp_path):
    got = _run(_record(tmp_path, (LABEL, "PASS")))
    assert got.returncode == RC_PASS, got.stdout + got.stderr
    assert LABEL in got.stdout


def test_a_recorded_FAIL_is_restated_as_a_FAIL(tmp_path):
    """THE LOAD-BEARING HALF. If this ever returned 0 the landing script would
    print PASS for a gate that failed where it ran."""
    got = _run(_record(tmp_path, (LABEL, "FAIL")))
    assert got.returncode == RC_FAIL, got.stdout + got.stderr
    assert "[FAIL]" in got.stdout


def test_the_subject_is_named_in_the_log(tmp_path):
    """A reader of the gate log must be able to see WHOSE verdict this is."""
    got = _run(_record(tmp_path, (LABEL, "PASS")),
               subject="programs/plugin_full_audit.py")
    assert "programs/plugin_full_audit.py" in got.stdout, got.stdout


# ── every way of not knowing is rc 2, never rc 0 ────────────────────────────

def test_a_missing_record_is_not_a_pass(tmp_path):
    got = _run(tmp_path / "never-written.json")
    assert got.returncode == RC_CANNOT, got.stdout + got.stderr
    assert "CANNOT CONSUME" in got.stdout


def test_a_refusal_is_MARKED_so_the_landing_log_names_it(tmp_path):
    """`gatekeeper-land.sh`'s `run` prints the FAILING lines first by matching
    `^\\s*(FAIL|ERROR)` / `[FAIL]`, then a bare `tail -5`. A refusal that
    matched neither would reach the reader as tail with the reason scrolled
    off — the "the failure was real, it was named nowhere" defect that comment
    in the landing script was written about.
    """
    got = _run(tmp_path / "never-written.json")
    assert got.stdout.startswith("[FAIL]"), got.stdout


def test_an_empty_record_is_not_a_pass(tmp_path):
    p = tmp_path / "hygiene.json"
    p.write_text("", encoding="utf-8")
    assert _run(p).returncode == RC_CANNOT


def test_an_unparseable_record_is_not_a_pass(tmp_path):
    p = tmp_path / "hygiene.json"
    p.write_text("{ this is not json", encoding="utf-8")
    assert _run(p).returncode == RC_CANNOT


def test_a_record_that_is_a_json_LIST_is_not_a_pass(tmp_path):
    p = tmp_path / "hygiene.json"
    p.write_text("[]\n", encoding="utf-8")
    assert _run(p).returncode == RC_CANNOT


def test_a_LIST_ONLY_record_is_not_a_pass(tmp_path):
    """`--list` declares the gates and runs none of them. A record from such a
    run describes what WOULD have been checked."""
    got = _run(_record(tmp_path, (LABEL, "PASS"), listed_only=True))
    assert got.returncode == RC_CANNOT, got.stdout
    assert "--list" in got.stdout


def test_a_renamed_gate_is_not_a_pass(tmp_path):
    """The failure this consumer is most likely to meet: somebody renames the
    hygiene gate and this line is left standing in for nothing."""
    got = _run(_record(tmp_path, ("plugin full audit (D1+D2)", "PASS")))
    assert got.returncode == RC_CANNOT, got.stdout
    assert "renamed or deleted" in got.stdout


def test_an_ambiguous_label_is_not_a_pass(tmp_path):
    got = _run(_record(tmp_path, (LABEL, "PASS"), (LABEL, "FAIL")))
    assert got.returncode == RC_CANNOT, got.stdout


@pytest.mark.parametrize("state", ["NOT_CHECKED", "LISTED", "OTHER_SHARD",
                                   "OUT_OF_SCOPE", "WROTE_CORPUS"])
def test_a_state_that_is_not_a_verdict_is_not_a_pass(tmp_path, state):
    """`_gate_dispatch.sh` records five states that say something about the RUN
    and nothing about the subject. None of them may be re-stated as an answer.

    OTHER_SHARD is the one with teeth: under sharding the gate is another
    host's responsibility, so consuming it as PASS would let a landing inherit
    a verdict nobody on this host produced.
    """
    got = _run(_record(tmp_path, (LABEL, state)))
    assert got.returncode == RC_CANNOT, got.stdout
    assert state in got.stdout


def test_a_substring_of_the_label_does_not_match(tmp_path):
    """Matching must be EXACT: a loose match would re-state a neighbouring
    gate's verdict while looking like it worked."""
    got = _run(_record(tmp_path, ("plugin full audit and then some", "PASS")))
    assert got.returncode == RC_CANNOT, got.stdout


# ── the wiring, which is where the safety of the collapse actually lives ────

def _skip_unless(p: Path):
    if not p.is_file():
        pytest.skip(f"{p} absent")
    return p.read_text(encoding="utf-8")


def test_the_owning_suite_STILL_EXECUTES_the_audit():
    """THE COLLAPSE'S PRECONDITION, asserted rather than assumed.

    Consuming a verdict is only legitimate while somebody still PRODUCES it.
    If this assertion ever fails, `plugin_full_audit.py` is run by nothing on a
    landing and the consumer below is re-stating a verdict that no longer
    exists — the check would be gone and the log would still say PASS.
    """
    src = _skip_unless(_HYGIENE)
    line = re.search(
        r'^\s*run\s+"' + re.escape(LABEL) + r'"\s+.*plugin_full_audit\.py.*$',
        src, re.M)
    assert line, (
        f'tools/ci/repo_hygiene_gates.sh no longer runs plugin_full_audit.py '
        f'under the label "{LABEL}" — the landing script consumes that record '
        f'instead of re-running the program, so nothing would execute it')


def test_the_landing_script_consumes_that_exact_label():
    src = _skip_unless(_LAND)
    assert "landing_gate_result_consume.py" in src
    assert f'--gate "{LABEL}"' in src, (
        "the landing script must consume the label the hygiene suite declares; "
        "any other spelling makes the consumer refuse on every landing")


def test_the_landing_script_no_longer_runs_the_audit_a_second_time():
    """The duplicate itself. `plugin_full_audit.py` may be NAMED by the landing
    script — the consumer names it as its subject — but it must not be the
    program the landing script executes, or the round pays for it twice.
    """
    src = _skip_unless(_LAND)
    executed = re.findall(
        r'^\s*run\s+"[^"]*"\s+python3\s+"\$PROGRAMS/plugin_full_audit\.py"',
        src, re.M)
    assert executed == [], (
        "gatekeeper-land.sh runs plugin_full_audit.py directly again — that is "
        "the ~20 s duplicate of repo_hygiene_gates.sh's own gate")


def test_the_hygiene_record_is_produced_even_when_nobody_asked():
    """Without this the consumer can only answer on the merge-verification
    path, and every ordinary push would get rc 2."""
    src = _skip_unless(_LAND)
    assert 'GK_HYG_RECORD' in src
    assert 'mktemp -t gk_hygrec' in src, (
        "with GATEKEEPER_HYGIENE_REPORT unset the suite must still write its "
        "record somewhere, or the consumed gate refuses on the push path")
    assert '--summary-json "$GATEKEEPER_HYGIENE_REPORT"' in src, (
        "the caller-supplied path must still be honoured verbatim — "
        "gatekeeper-verify-merge.sh reads that record")


def test_the_consumer_is_part_of_the_cached_base_gate_contract():
    """`gatekeeper-verify-merge.sh` keys its reusable BASE record on the files
    that decide what the gates mean. This program now decides one of them, so a
    change to it must invalidate a cached base — otherwise the base arm's
    verdict was produced by one contract and the candidate's by another.
    """
    verify = _REPO / "tools" / "gatekeeper-verify-merge.sh"
    src = _skip_unless(verify)
    assert "programs/landing_gate_result_consume.py" in src, (
        "the consumer is not in the base-gate-cache fingerprint, so a change "
        "to it would be differenced against a stale base record")


def test_the_temporary_record_is_cleaned_up():
    src = _skip_unless(_LAND)
    assert 'rm -f "$FP" "$WG_BASE" "$GK_HYG_TMP"' in src, (
        "a per-run temporary the script creates must be removed on exit")
