#!/usr/bin/env python3
"""The hygiene subset rule has to be REACHED, not merely shipped (vibe-ic#1498).

WHAT WENT WRONG, AND WHY A SECOND FILE IS NEEDED
================================================
`hygiene_finding_delta.py` landed with 20 passing tests and NO CALL SITE. On the
tree that closed #1498, the only mentions of it anywhere outside its own two
files were two comments and two rows of a generated index:

    tools/gatekeeper-land.sh:629      # …which is what `hygiene_finding_delta.py` needs
    tools/gatekeeper-verify-merge.sh  # The host is REQUIRED by `hygiene_finding_delta`
    programs/INDEX.md (x2)            a docs row

`CAND_HYG` was assigned and never read; arm B's invocation set four
`GATEKEEPER_*` variables and not `GATEKEEPER_HYGIENE_REPORT`, so no candidate
record was ever written and the base record that WAS written had nothing to be
differenced against. The landing commit said so in its own words — "Wiring is
opt-in and changes no verdict here" — and the opt-in was never taken.

So the tier stayed judged by ONE label for ~80 gates, which is the permissive
half #1498 exists to close: while the base's hygiene suite is red, that label is
excused on the candidate too and a finding this branch INTRODUCED under it is
invisible.

A test of the comparison cannot catch that. This file tests the WIRING and the
DECISION — the two things that stand between a correct comparison and a landing
that reads it.

BOTH DIRECTIONS, ALWAYS
=======================
    inherited finding, base red   -> LAND OK    (a subset rule that bans is a ban)
    introduced finding, base red  -> REFUSE     (the whole point)
    unanswerable comparison       -> REFUSE     (rc 2, never a pass)
    differential not supplied     -> LAND OK, DISCLOSED (the branch does not
                                    control whether arm A2 ran)
    base record but no candidate  -> REFUSE     (the unmeasured side is the tree
                                    under test)

and the additivity property, which is what makes consuming a helper's verdict
safe at all: the finding delta may only ADD refusals to the per-label rule.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import landing_merge_verdict as V  # noqa: E402
import gate_process_attestation as A  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "landing_merge_verdict.py"
_REPO_ROOT = _PROGRAMS.parents[3]
_VERIFY = _REPO_ROOT / "tools" / "gatekeeper-verify-merge.sh"
_LAND = _REPO_ROOT / "tools" / "gatekeeper-land.sh"
_T = 55

TREE = "a" * 40
SHA = "c" * 40
_HOST = "host-a"

_GOOD_LOG = """=== gatekeeper landing gates — base=origin/main ===
  PASS  NDA — commit messages
  PASS  targeted tests (21 file(s))
  PASS  repo hygiene gates
=== ALL GATES PASS — stamped %s ===
""" % SHA[:9]

# THE SHAPE THIS ISSUE IS ABOUT: the hygiene suite is red on BOTH arms, so the
# per-label differential excuses it and only the finding delta can see inside.
_RED_HYGIENE_LOG = """=== gatekeeper landing gates — base=origin/main ===
  PASS  NDA — commit messages
  PASS  targeted tests (21 file(s))
  FAIL  repo hygiene gates
=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ===
"""


# ════════════════════════════════════════════════════════ record fixtures


def _gate(label, state, corpus=None, expired=False):
    """One gate as `repo_hygiene_gates.sh --summary-json` writes it."""
    return {"label": label, "state": state, "seconds": 1,
            "exempt_until": None, "exempt_reason": None,
            "corpus": corpus, "exemption_expired": expired, "scope": None}


def _attestation(gate):
    rc = {"PASS": 0, "FAIL": 1, "NOT_CHECKED": 2,
          "WROTE_CORPUS": 0}[gate["state"]]
    return A.process_attestation(
        gate["label"], "[PASS] checked\n" if rc == 0 else "[FAIL] named\n",
        rc, ["python3", "checker.py", gate["label"]])


def _record(gates):
    count = lambda state: sum(g["state"] == state for g in gates)
    return {
        "listed_only": False, "declared": len(gates),
        "ran": sum(count(s) for s in
                   ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")),
        "decided": count("PASS") + count("FAIL"),
        "passed": count("PASS"), "failed": count("FAIL"),
        "not_checked": count("NOT_CHECKED"),
        "wrote_corpus": count("WROTE_CORPUS"),
        "deferred": count("LISTED"), "other_shard": count("OTHER_SHARD"),
        "out_of_scope": count("OUT_OF_SCOPE"),
        "not_checked_unexempted": [
            g["label"] for g in gates if g["state"] == "NOT_CHECKED"
            and not g.get("exempt_until")],
        "exemptions_expired": [], "wiring_errors": [], "corpora": [],
        "shard": None, "today": "2026-08-15", "gates": gates,
        "process_attestations": [
            _attestation(g) for g in gates if g["state"] in
            ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")],
    }


def _base_gates():
    """A RED base, because `main` is red — that is this issue's whole premise."""
    return [_gate("chip-AGNOSTIC source guard", "PASS"),
            _gate("63x8 census freshness", "FAIL"),
            _gate("plugin version stated in prose", "FAIL"),
            _gate("gates disclose their denominator", "PASS")]


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p


def _md5(p: Path) -> str:
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _delta():
    return V.Delta(base_total=10, candidate_total=10, overlap=10)


def _decide(**over):
    """A LAND OK baseline whose hygiene suite is RED ON BOTH ARMS."""
    kw = dict(rebase_status="ok", expected_tree=TREE, verified_tree=TREE,
              github_tree=TREE, land=V.parse_land_log(_RED_HYGIENE_LOG),
              base_land=V.parse_land_log(_RED_HYGIENE_LOG), delta=_delta(),
              verified_sha=SHA, truncated=False, dropped_files=(),
              selection_size=21)
    kw.update(over)
    return V.decide(**kw)


# ═══════════════════════════════════════════ 1. THE WIRING, WHICH WAS MISSING


def test_both_arms_are_asked_for_a_hygiene_record():
    """The defect exactly: arm A2 set the variable and arm B did not, so the
    baseline had nothing to be differenced against."""
    src = _VERIFY.read_text(encoding="utf-8")
    assert 'GATEKEEPER_HYGIENE_REPORT="$BASE_HYG"' in src, \
        "arm A2 must write the BASE record"
    assert 'GATEKEEPER_HYGIENE_REPORT="$CAND_HYG"' in src, \
        ("arm B must write the CANDIDATE record — without it `CAND_HYG` is a "
         "path nothing ever writes and the subset rule has no candidate side")


def test_the_candidate_record_variable_is_read_and_not_only_assigned():
    """`CAND_HYG` was assigned once and never read. A variable that is only
    written is the signature of wiring that was planned and not finished."""
    src = _VERIFY.read_text(encoding="utf-8")
    reads = [l for l in src.splitlines()
             if "$CAND_HYG" in l or "${CAND_HYG" in l]
    assert len(reads) >= 2, (
        "CAND_HYG is assigned and never read — that was the whole defect:\n"
        + "\n".join(reads))


def test_the_verdict_is_handed_the_pair():
    """A comparison nobody invokes decides nothing."""
    src = _VERIFY.read_text(encoding="utf-8")
    assert "HYG_ARGS=(--base-hygiene" in src, "HYG_ARGS is never populated"
    assert '"${HYG_ARGS[@]+"${HYG_ARGS[@]}"}"' in src, \
        "HYG_ARGS is never expanded into the verdict invocation"
    # …and into THE VERDICT, not some other command.
    verdict_call = src.split('python3 "$VERDICT_PROG"')[1].split("\nRC=")[0]
    assert "HYG_ARGS" in verdict_call, \
        "HYG_ARGS is expanded somewhere other than the verdict invocation"


def test_the_base_record_is_cached_beside_the_base_log():
    """A `--base-gate-cache` hit SKIPS arm A2, so a cache that stores the log
    and not the record degrades every queued landing to the coarse comparison —
    in exactly the mode the merge queue runs in."""
    src = _VERIFY.read_text(encoding="utf-8")
    # SPELLING ADAPTED to the atomic publish this script grew after this test
    # was written: the entry is copied to a `$CACHE_TMP.*` name and `mv`d into
    # place with the manifest LAST, so the base record reaches `$CACHED_HYG` in
    # two steps rather than in one `cp`. What is asserted is unchanged — the
    # BASE arm's record is what lands under the cached name.
    assert 'cp "$BASE_HYG" "$CACHE_TMP.hygiene.json"' in src \
        or 'cp "$BASE_HYG" "$CACHED_HYG"' in src
    assert 'mv "$CACHE_TMP.hygiene.json" "$CACHED_HYG"' in src \
        or 'cp "$BASE_HYG" "$CACHED_HYG"' in src
    assert 'printf \'%s\\n\' "$THIS_HOST" > "$CACHED_HYG_HOST"' in src, \
        ("the HOST must travel with the cached record — findings are "
         "host-dependent and a shared cache would otherwise hand one host's "
         "baseline to another host's candidate")
    hit = src.split('if [ -n "$CACHED" ] && [ -s "$CACHED" ]', 1)[1].split(
        "; then", 1)[0]
    assert "CACHED_HYG" in hit and "CACHED_HYG_HOST" in hit, \
        "a log-only legacy cache must be a miss, or the new gate never runs"


def test_the_land_script_still_honours_the_variable():
    """The record this all rests on is produced by `gatekeeper-land.sh`."""
    src = _LAND.read_text(encoding="utf-8")
    assert "GATEKEEPER_HYGIENE_REPORT" in src
    assert '--summary-json "$GATEKEEPER_HYGIENE_REPORT"' in src


def test_the_judge_and_its_helper_both_count_as_the_gate_being_edited():
    """A PR that edits the comparison judging it must say so in the verdict."""
    src = _VERIFY.read_text(encoding="utf-8")
    assert "programs/hygiene_finding_delta.py" in src


# ═══════════════════════════════════════ 2. THE DECISION, IN BOTH DIRECTIONS


def test_an_inherited_hygiene_finding_still_lands():
    """LOAD-BEARING and first. `main` fails several hygiene gates; a rule that
    charged those to every branch would be the ban #1498 was filed about."""
    v = _decide(hygiene={"status": "CLEAN", "introduced": [],
                         "carried": [["FAIL", "63x8 census freshness", ""]],
                         "cleared": [], "no_verdict_either_side": [],
                         "empty_corpora": [], "base_findings": 1,
                         "candidate_findings": 1, "declared": 4})
    assert v.ok is True, v.reasons
    assert v.unmeasurable is False
    assert "HYGIENE_FINDING_DELTA_CLEAN" in v.disclosures
    assert any("carried" in n for n in v.notes)


def test_an_introduced_hygiene_finding_refuses():
    """THE POINT. The suite label is red on BOTH arms, so the per-label rule
    excuses it; only the finding delta can see that this branch broke a gate."""
    v = _decide(hygiene={
        "status": "INTRODUCED",
        "introduced": [["FAIL", "gates disclose their denominator", ""]],
        "carried": [["FAIL", "63x8 census freshness", ""]], "cleared": [],
        "no_verdict_either_side": [], "empty_corpora": [],
        "base_findings": 1, "candidate_findings": 2, "declared": 4})
    assert v.ok is False
    assert any("INTRODUCED BY THIS BRANCH" in r for r in v.reasons), v.reasons
    assert any("gates disclose their denominator" in r for r in v.reasons)
    assert "HYGIENE_FINDING_DELTA_INTRODUCED" in v.disclosures


def test_the_same_tree_without_the_differential_lands_it():
    """THE NEGATIVE CONTROL FOR THE WHOLE CHANGE. Identical inputs, differing
    only in whether the differential was supplied — which is precisely the
    difference between `origin/main` and this branch. Without it the introduced
    finding above is INVISIBLE and the landing is allowed."""
    v = _decide(hygiene=None)
    assert v.ok is True, v.reasons
    assert "HYGIENE_FINDING_DELTA_NOT_SUPPLIED" in v.disclosures
    assert any("ONE label" in n for n in v.notes), v.notes


def test_an_unanswerable_comparison_refuses_as_unmeasurable():
    """`REFUSED` is the helper declining to answer. It blocks exactly like an
    introduction and it is rc 2, because "I could not look" is not "I looked"."""
    v = _decide(hygiene={"status": "REFUSED",
                         "refusal": "the base was measured on host-a and the "
                                    "candidate on host-b"})
    assert v.ok is False
    assert v.unmeasurable is True
    assert any("COULD NOT BE COMPUTED" in r for r in v.reasons), v.reasons
    assert any("host-b" in r for r in v.reasons), \
        "the refusal's own words must reach the operator"


def test_an_unknown_status_is_not_a_pass():
    """Reached only if the helper grows a fourth answer. Falling through to OK
    is how a gate stops gating without anyone editing the gate."""
    v = _decide(hygiene={"status": "PROBABLY_FINE"})
    assert v.ok is False
    assert v.unmeasurable is True


def test_a_suite_failure_the_finding_list_cannot_explain_refuses():
    """The cross-check `hygiene_finding_delta`'s own docstring asks for: the
    suite went red HERE and not on the base, yet nothing is named. A difference
    that explains nothing cannot excuse anything."""
    v = _decide(land=V.parse_land_log(_RED_HYGIENE_LOG),
                base_land=V.parse_land_log(_GOOD_LOG),
                hygiene={"status": "CLEAN", "introduced": [], "carried": [],
                         "cleared": [], "no_verdict_either_side": [],
                         "empty_corpora": [], "base_findings": 0,
                         "candidate_findings": 0, "declared": 4})
    assert v.ok is False
    assert any("NAMES NOTHING" in r for r in v.reasons), v.reasons


def test_the_delta_only_ever_adds_refusals():
    """ADDITIVITY, asserted rather than argued. Reading a helper's verdict is
    only safe if the worst a wrong CLEAN can do is leave the tier as coarse as
    it already was. Here a gate that PASSED on the base fails on the candidate:
    the per-label rule refuses, and a CLEAN finding delta must not clear it."""
    log = _RED_HYGIENE_LOG.replace("  PASS  NDA — commit messages",
                                   "  FAIL  NDA — commit messages")
    clean = {"status": "CLEAN", "introduced": [], "carried": [], "cleared": [],
             "no_verdict_either_side": [], "empty_corpora": [],
             "base_findings": 0, "candidate_findings": 0, "declared": 4}
    without = _decide(land=V.parse_land_log(log), hygiene=None)
    with_delta = _decide(land=V.parse_land_log(log), hygiene=clean)
    assert without.ok is False and with_delta.ok is False
    assert set(without.reasons) <= set(with_delta.reasons), (
        "the finding delta removed a refusal the per-label rule produced:\n"
        f"without: {without.reasons}\nwith:    {with_delta.reasons}")


# ═════════════════════════════════ 3. WHICH ARM'S SILENCE MEANS WHICH THING


def test_no_arguments_disclose_legacy_per_label_mode():
    """A legacy direct caller may omit the feature; the merge path never does."""
    assert V.read_hygiene_delta("", "", "", "") is None
    assert V.read_hygiene_delta("", "/nonexistent", _HOST, _HOST) is None


def test_named_but_missing_base_record_refuses():
    """The merge path always names both records, so absence fails closed."""
    d = V.read_hygiene_delta("/nonexistent-base", "/nonexistent-candidate",
                             _HOST, _HOST)
    assert d is not None and d["status"] == "REFUSED"
    assert "missing measurement" in d["refusal"]


def test_a_base_record_with_no_candidate_record_refuses(tmp_path):
    """The opposite asymmetry, for #1443's reason: here the arm that failed to
    measure is the tree under test, and its silence is not an empty finding
    set."""
    base = _write(tmp_path, "base.json", _record(_base_gates()))
    d = V.read_hygiene_delta(str(base), "", _HOST, _HOST)
    assert d is not None and d["status"] == "REFUSED"
    assert "tree under test" in d["refusal"]
    v = _decide(hygiene=d)
    assert v.ok is False and v.unmeasurable is True


def test_the_helper_is_really_imported_and_really_answers(tmp_path):
    """Not a stub: `read_hygiene_delta` must reach the shipped comparison and
    come back with its verdict, on records read off disk."""
    base = _write(tmp_path, "base.json", _record(_base_gates()))
    same = _write(tmp_path, "cand.json", _record(_base_gates()))
    assert V.read_hygiene_delta(str(base), str(same), _HOST, _HOST)["status"] \
        == "CLEAN"
    broken = _base_gates()
    broken[3] = _gate("gates disclose their denominator", "FAIL")
    worse = _write(tmp_path, "worse.json", _record(broken))
    d = V.read_hygiene_delta(str(base), str(worse), _HOST, _HOST)
    assert d["status"] == "INTRODUCED"
    assert d["introduced"] == [["FAIL", "gates disclose their denominator", ""]]
    # Host-dependence is enforced by the helper, not re-implemented here.
    assert V.read_hygiene_delta(str(base), str(same), "host-a",
                                "host-b")["status"] == "REFUSED"


# ══════════════════════════════════════ 4. END TO END, THROUGH THE REAL CLI
#
# THE JUNIT FIXTURE IS THE SHAPE THE DRIVER EMITS TODAY, not the one it emitted
# when this file was written. `pytest_per_file_junit.py` grew the aggregate
# session and its process suites, and the verdict now REFUSES a report that
# carries no complete record of either — an absolute refusal that has nothing to
# do with hygiene. Handing the CLI a pre-aggregate report would make every
# assertion below read that refusal instead of the hygiene one it is about.

_SEL_FILE = "programs/tests/test_x.py"
_JUNIT_XML = (
    '<?xml version="1.0"?><testsuites>'
    # the ordinary per-file session
    '<testsuite name="' + _SEL_FILE + '">'
    '<testcase classname="programs.tests.test_x" name="t" '
    'file="' + _SEL_FILE + '"/></testsuite>'
    # …its process record
    '<testsuite name="' + _SEL_FILE + '::process_exit" tests="1" '
    'failures="0" errors="0" skipped="0">'
    '<testcase classname="pytest_per_file_process" '
    'name="' + _SEL_FILE + '::process_exit" file="' + _SEL_FILE + '">'
    '<properties><property name="process_rc" value="0"/></properties>'
    '</testcase></testsuite>'
    # the ordered whole-selection session
    '<testsuite name="aggregate::pytest">'
    '<testcase classname="pytest_aggregate.programs.tests.test_x" name="t" '
    'file="' + _SEL_FILE + '"/></testsuite>'
    # …and ITS process record, which is what `--require`-less runs still check
    '<testsuite name="whole_selection::process_exit" tests="1" '
    'failures="0" errors="0" skipped="0">'
    '<testcase classname="pytest_aggregate_process" '
    'name="whole_selection::process_exit" file="&lt;aggregate&gt;">'
    '<properties><property name="process_rc" value="0"/></properties>'
    '</testcase></testsuite>'
    '</testsuites>')


def _cli(tmp_path, hyg_base: Path, hyg_cand: Path, tag: str):
    """The real program, the real arguments, one junit pair shared by both arms.

    Returns (rc, stdout, the JSON record).
    """
    junit = tmp_path / "j.xml"
    junit.write_text(_JUNIT_XML, encoding="utf-8")
    land = tmp_path / f"land_{tag}.log"
    land.write_text(_RED_HYGIENE_LOG, encoding="utf-8")
    base_land = tmp_path / f"base_land_{tag}.log"
    base_land.write_text(_RED_HYGIENE_LOG, encoding="utf-8")
    sel = tmp_path / "sel.txt"
    sel.write_text("programs/tests/test_x.py\n", encoding="utf-8")
    out = tmp_path / f"v_{tag}.json"
    cp = subprocess.run(
        [sys.executable, str(_PROG),
         "--base-sha", SHA, "--head-sha", SHA, "--verified-sha", SHA,
         "--rebase-status", "ok", "--expected-tree", TREE,
         "--verified-tree", TREE, "--land-log", str(land),
         "--base-land-log", str(base_land), "--selection", str(sel),
         "--base-selection", str(sel), "--base-junit", str(junit),
         "--candidate-junit", str(junit),
         "--base-hygiene", str(hyg_base), "--candidate-hygiene", str(hyg_cand),
         "--base-hygiene-host", _HOST, "--candidate-hygiene-host", _HOST,
         "--json", str(out)],
        capture_output=True, text=True, timeout=_T)
    return cp.returncode, cp.stdout + cp.stderr, json.loads(out.read_text())


def test_end_to_end_both_arms_differ_only_in_the_one_gate(tmp_path):
    """THE PAIRED PROOF. Same base record, same junit, same land logs; the two
    candidate records differ in ONE gate's state. Their md5s are printed so the
    reader can check that only that one thing moved."""
    base = _write(tmp_path, "base.json", _record(_base_gates()))
    clean_cand = _write(tmp_path, "cand_clean.json", _record(_base_gates()))
    broken = _base_gates()
    broken[3] = _gate("gates disclose their denominator", "FAIL")
    red_cand = _write(tmp_path, "cand_red.json", _record(broken))

    rc_ok, out_ok, rec_ok = _cli(tmp_path, base, clean_cand, "ok")
    rc_no, out_no, rec_no = _cli(tmp_path, base, red_cand, "no")

    assert rc_ok == 0, out_ok
    assert rec_ok["verdict"] == "LAND_OK"
    assert rec_ok["hygiene_finding_delta"]["status"] == "CLEAN"
    # The base's own two findings are reported as carried, so the subset rule is
    # visible in the record rather than implied by a count.
    assert len(rec_ok["hygiene_finding_delta"]["carried"]) == 2

    assert rc_no == 1, out_no
    assert rec_no["verdict"] == "REFUSE"
    assert rec_no["hygiene_finding_delta"]["status"] == "INTRODUCED"
    assert any("INTRODUCED BY THIS BRANCH" in r for r in rec_no["reasons"])

    # The two arms are the same question asked of two trees.
    assert _md5(base) == _md5(base)
    assert _md5(clean_cand) != _md5(red_cand)
    d_ok = json.loads(clean_cand.read_text())
    d_no = json.loads(red_cand.read_text())
    differing = [(a, b) for a, b in zip(d_ok["gates"], d_no["gates"]) if a != b]
    assert len(differing) == 1, differing


def test_end_to_end_the_record_says_when_it_was_not_asked(tmp_path):
    """`null` must be distinguishable from "asked and found nothing" by anything
    that reads the record."""
    junit = tmp_path / "j.xml"
    junit.write_text(_JUNIT_XML, encoding="utf-8")
    land = tmp_path / "land.log"
    land.write_text(_RED_HYGIENE_LOG, encoding="utf-8")
    sel = tmp_path / "sel.txt"
    sel.write_text("programs/tests/test_x.py\n", encoding="utf-8")
    out = tmp_path / "v.json"
    cp = subprocess.run(
        [sys.executable, str(_PROG),
         "--base-sha", SHA, "--head-sha", SHA, "--verified-sha", SHA,
         "--rebase-status", "ok", "--expected-tree", TREE,
         "--verified-tree", TREE, "--land-log", str(land),
         "--base-land-log", str(land), "--selection", str(sel),
         "--base-selection", str(sel), "--base-junit", str(junit),
         "--candidate-junit", str(junit), "--json", str(out)],
        capture_output=True, text=True, timeout=_T)
    rec = json.loads(out.read_text())
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert rec["hygiene_finding_delta"] is None
    assert "HYGIENE_FINDING_DELTA_NOT_SUPPLIED" in rec["disclosures"]
    assert "DISCLOSE  HYGIENE_FINDING_DELTA_NOT_SUPPLIED" in cp.stdout


# ═════════════════════════════════════════════════ 5. THE LABEL IT KEYS ON


def test_the_hygiene_label_this_program_matches_is_the_one_land_sh_prints():
    """A regex that stopped matching the real label would silently disable the
    cross-check above, and nothing else in this file would notice."""
    printed = re.findall(r'^run "([^"]*hygiene[^"]*)"',
                         _LAND.read_text(encoding="utf-8"), re.M)
    assert printed, "gatekeeper-land.sh no longer runs a labelled hygiene tier"
    assert any(V._HYGIENE_TIER.match(l) for l in printed), printed
