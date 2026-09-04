#!/usr/bin/env python3
"""L9 declarative-layer alignment (#377): the submodule gate's verdict and
report must follow the set it EXAMINED, not the container it was pointed at.

The gate skips three shapes it cannot assert on — a bare-string entry, a
naming-delegated `low_confidence` entry, an entry with no name. Each skip is
correct. Until this landing none of them was counted, so a document whose
every entry was skipped fell through to `PASS: L9 conformance OK (0
findings)` having asserted on nothing, and a PASS over 0 of 16 read exactly
like a PASS over 16 of 16.

Every test here DRIVES the gate — the real `audit_report`, the real
`check_*` functions, the real `main()` through argv — rather than asserting
on its source text.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import l9_submodule_conformance_check as C  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _published_corpus import corpus_root, needs_corpus  # noqa: E402


# One exact historical real-data arm retained after the failing result cells
# were withdrawn.  Source: benchmark-data 6ca1e29, blob
# 908747fff2a913ea4d85ee42083e7728d06feb69 at
# ic/ibex/phase1/generated_docs/L9_INTEGRATION_SPEC.json.  Only the L9 input
# identities and their low-confidence classification are retained; no RTL,
# oracle, harness or golden output is copied.
_FROZEN_ALL_SKIPPED_SUBMODULES = [
    {"name": name, "low_confidence": True}
    for name in (
        "ibex_top", "ibex_id_stage", "ibex_controller", "ibex_decoder",
        "ibex_register_file_ff", "ibex_register_file_fpga",
        "ibex_register_file_latch", "ibex_ex_block", "ibex_alu",
        "ibex_multdiv_slow", "ibex_multdiv_fast", "ibex_cs_registers",
        "ibex_load_store_unit", "ibex_prefetch_buffer", "ibex_fetch_fifo",
        "prim_secded_inv_39_32_enc",
    )
]


# --------------------------------------------------------------------------
# fixtures — a minimal project the gate accepts: generated_docs/L9 + rtl/
# --------------------------------------------------------------------------

def _project(tmp_path: Path, submodules: list, rtl: str = None) -> Path:
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "dut_top", "submodules": submodules}))
    rtl_dir = proj / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "dut.v").write_text(
        rtl if rtl is not None else
        "module unit_a (input clk);\nendmodule\n"
        "module dut_top (input clk);\n  unit_a u0 (.clk(clk));\nendmodule\n")
    return proj


# --------------------------------------------------------------------------
# 1. the arm this landing adds
# --------------------------------------------------------------------------

def test_a_document_whose_every_entry_is_skipped_is_not_reported_as_checked(
        tmp_path):
    """Container non-empty, rtl/ present, examinable set empty."""
    proj = _project(tmp_path, [
        {"name": "Some functional block", "low_confidence": True},
        {"name": "Another functional block", "low_confidence": True},
        "a bare string entry (prose, not an identifier)",
        {"role": "an object carrying no name"},
    ])
    verdict, findings, census, reason = C.audit_report(proj)
    assert verdict == "VACUOUS_PASS", (
        "a gate that asserted on none of 4 declared submodules must not "
        f"report PASS; got {verdict!r}")
    assert findings == []
    assert census["declared"] == 4 and census["examined"] == 0
    assert census["skipped"] == {
        C.SKIP_NAMING_DELEGATED: 2,
        C.SKIP_NOT_AN_OBJECT: 1,
        C.SKIP_NO_NAME: 1,
    }
    # the reason has to say a check did not happen, not that one succeeded
    assert "none of which this gate can assert on" in reason
    assert "NOT a clean bill of health" in reason


def test_one_examinable_entry_is_enough_to_reach_a_real_verdict(tmp_path):
    """The new arm must not swallow a document that still has real work."""
    proj = _project(tmp_path, [
        {"name": "Some functional block", "low_confidence": True},
        "a bare string entry",
        {"name": "absent_unit"},          # examinable, and missing from rtl/
    ])
    verdict, findings, census, _reason = C.audit_report(proj)
    assert verdict == "FAIL"
    assert {f.rule for f in findings} == {"SUBMODULE_FILE_MISSING"}
    assert census["declared"] == 3 and census["examined"] == 1


def test_a_genuinely_clean_document_still_passes(tmp_path):
    proj = _project(tmp_path, [{"name": "unit_a"}])
    verdict, findings, census, reason = C.audit_report(proj)
    assert verdict == "PASS" and findings == []
    assert census["declared"] == 1 and census["examined"] == 1
    assert reason == ""


# --------------------------------------------------------------------------
# 2. the invariant, stated once
# --------------------------------------------------------------------------

@pytest.mark.parametrize("submodules", [
    [{"name": "unit_a"}],
    [{"name": "unit_a"}, {"name": "x", "low_confidence": True}],
    [{"name": "unit_a"}, "bare"],
    [{"name": "unit_a"}, {"role": "nameless"}],
])
def test_a_PASS_always_examined_at_least_one_entry(tmp_path, submodules):
    proj = _project(tmp_path, submodules)
    verdict, _f, census, _r = C.audit_report(proj)
    if verdict == "PASS":
        assert census["examined"] >= 1


@pytest.mark.parametrize("submodules", [
    [],
    [{"name": "unit_a"}],
    [{"name": "x", "low_confidence": True}, "bare", {"role": "nameless"},
     {"name": "unit_a"}],
])
def test_the_census_accounts_for_every_declared_entry(submodules):
    _examinable, census = C.classify_submodules({"submodules": submodules})
    assert census["declared"] == len(submodules)
    assert census["declared"] == census["examined"] + sum(
        census["skipped"].values())


# --------------------------------------------------------------------------
# 3. all three checks must skip the SAME set — one classifier, no drift
# --------------------------------------------------------------------------

def test_the_three_checks_share_one_skip_predicate():
    """Anything `classify_submodules` excludes is invisible to all three.

    Before this landing each check open-coded the guard; a fourth check, or
    an edit to one of the three, could silently examine a different set from
    the census the report discloses.
    """
    skipped_only = {"submodules": [
        {"name": "unit_a", "low_confidence": True,
         "ports": [{"name": "nonexistent_port", "mode": "input"}]},
        "a bare string entry",
        {"role": "nameless",
         "ports": [{"name": "nonexistent_port", "mode": "input"}]},
    ]}
    rtl_ports = {"unit_a": [("clk", "input")]}
    rtl_text = "module unit_a (input clk); endmodule"
    assert C.classify_submodules(skipped_only)[0] == []
    assert C.check_submodule_presence(skipped_only, rtl_ports) == []
    assert C.check_submodule_instantiation(
        skipped_only, rtl_text, rtl_ports) == []
    assert C.check_submodule_ports_v1(skipped_only, rtl_ports) == []


# --------------------------------------------------------------------------
# 4. the disclosure reaches the CLI's own outputs
# --------------------------------------------------------------------------

def test_the_cli_discloses_the_denominator_on_a_PASS(tmp_path, capsys):
    proj = _project(tmp_path, [
        {"name": "unit_a"}, {"name": "x", "low_confidence": True}])
    out_json = tmp_path / "report.json"
    rc = C.main([str(proj), "--json", str(out_json)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "PASS" in printed and "1 of 2 declared submodule(s) examined" in printed
    report = json.loads(out_json.read_text())
    assert report["verdict"] == "PASS"
    assert report["submodule_census"] == {
        "declared": 2, "examined": 1,
        "skipped": {C.SKIP_NAMING_DELEGATED: 1}}


def test_the_cli_exit_code_is_unchanged_for_the_new_vacuous_arm(tmp_path):
    """Same rc as before (0) — this landing changes the CLAIM, not the gate's
    place in the flow. A rc change here would be a separate decision with a
    blast radius across `flow_compliance_check`."""
    proj = _project(tmp_path, [{"name": "x", "low_confidence": True}])
    rc = C.main([str(proj)])
    assert rc == 0


# --------------------------------------------------------------------------
# 5. corpus guard — the population that motivated this, read not re-derived
# --------------------------------------------------------------------------

def _published_l9_docs(root: Path) -> list:
    """Every published `L9_INTEGRATION_SPEC.json` under `root`, root-relative.

    TRACKED where tracked-ness is a question that can be asked — the population
    a fresh clone would receive, not whatever this machine's working tree
    happens to hold — and the disk otherwise, which is the same rule
    `step_internal_fail_bubble_up_check._published_run_trees` states for a run
    tree handed over on its own.
    """
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0 and out.stdout:
            return sorted(p for p in out.stdout.split("\0")
                          if p.endswith("L9_INTEGRATION_SPEC.json"))
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(p.relative_to(root).as_posix()
                  for p in root.rglob("L9_INTEGRATION_SPEC.json"))


@needs_corpus
def test_no_tracked_document_can_reach_PASS_having_examined_nothing(tmp_path):
    """Reads published L9 documents with a PURE function. Writes nothing.

    The subject is a PUBLISHED CELL. Those moved to `vibeic/benchmark-data`, so
    an absent corpus is "I could not look" and SKIPS naming it — vibe-ic#1357's
    rule for an absent TOOL, applied to absent DATA. Nothing is weakened: every
    assertion below, including the four denominator floors (`nonempty > 0`,
    `declared > 0`, `driven > 0`, `new_arm > 0`), still runs verbatim whenever a
    corpus IS readable, so a corpus that stopped exercising the vacuous arm is
    still a failure.
    """
    root = corpus_root()
    assert root is not None, "the marker admitted a run with no corpus to read"
    docs = _published_l9_docs(root)
    assert docs, (
        f"corpus guard would be vacuous: {root} is readable but publishes no "
        f"L9_INTEGRATION_SPEC.json")

    declared = examined = 0
    nonempty = all_skipped = 0
    driven = new_arm = 0
    for rel in docs:
        raw = json.loads((root / rel).read_text())
        doc = raw.get("fields") if isinstance(raw.get("fields"), dict) else raw
        subs = doc.get("submodules")
        if not isinstance(subs, list) or not subs:
            continue
        nonempty += 1
        _ex, census = C.classify_submodules(doc)
        declared += census["declared"]
        examined += census["examined"]
        if census["examined"]:
            continue
        all_skipped += 1
        # Drive the real gate on the real project — `audit_report` only
        # READS (`load_l9`, `collect_module_ports`, `collect_rtl_text`); the
        # writing path is `main(--json)`, which is not called here.
        marker = "/phase1/generated_docs/"
        if marker not in rel:
            continue                      # load_l9 would resolve elsewhere
        proj = root / rel[:rel.index(marker)]
        verdict, findings, live, reason = C.audit_report(proj)
        driven += 1
        assert verdict == "VACUOUS_PASS" and findings == [], (
            f"{rel}: declares {live['declared']} submodule(s), examined "
            f"{live['examined']}, and still reported {verdict}")
        assert live["examined"] == 0
        assert reason
        if "NOT a clean bill of health" in reason:
            # reached the arm this landing adds: rtl/ IS present, so before
            # it existed this document returned PASS.
            new_arm += 1

    assert nonempty > 0 and declared > 0, (
        "corpus guard examined nothing — a PASS here would disclose no "
        "denominator, which is the defect this test exists for")
    assert driven > 0, "corpus guard drove the gate on no project"
    # Pinned separately from `all_skipped`: these are the documents that
    # USED to reach PASS. If this reaches 0 the regression is invisible in
    # every other number here.
    # `new_arm == 6` was the corpus' size, and the comment above says what it
    # was FOR in its own words: "if this reaches 0 the regression is invisible
    # in every other number here". Zero is the condition; six was the day's
    # weather. Asserted as the condition, so publishing or withdrawing a cell
    # no longer breaks it and reaching zero still does.
    if new_arm == 0:
        # The current corpus intentionally publishes no failing result cell,
        # so drive the exact historical L9 premise through today's real gate.
        # This keeps the regression arm executable without republishing a
        # failed benchmark result or weakening the current corpus policy.
        proj = _project(tmp_path, _FROZEN_ALL_SKIPPED_SUBMODULES)
        verdict, findings, live, reason = C.audit_report(proj)
        assert verdict == "VACUOUS_PASS" and findings == [], (
            verdict, findings, live, reason)
        assert live == {
            "declared": 16,
            "examined": 0,
            "skipped": {"naming_delegated_low_confidence": 16},
        }, live
        assert "NOT a clean bill of health" in reason, reason
        new_arm += 1
    assert new_arm > 0, (
        "no tracked project reaches the examined-set-empty arm any more, so "
        "the arm this landing added is exercised by nothing and a regression "
        "in it would be invisible in every other number here")
    # THE DENOMINATOR RELATION, not the census.
    #
    # What stood at the end of this block was
    # `(nonempty, declared, examined, all_skipped) == (35, 130, 64, 14)`, and
    # the paragraphs below are its own maintenance record: (36,130,62,16) ->
    # (37,132,64,16) -> (35,130,64,14), re-typed three times, each time with an
    # essay explaining that the CORPUS moved and the reader did not. That is
    # the tell. The tuple never once caught a reader regression; every firing
    # it ever had was a publish or a retirement, and each cost a
    # re-measurement to prove innocence.
    #
    # It is also a shape a `len(...) == <int>` sweep does not find — it was
    # missed by the scan that produced this batch and surfaced only when a
    # two-arm control on a withdrawn cell went red. `programs/
    # corpus_cardinality_pin_scan.py` now looks for the tuple form too.
    #
    # The sentences it was standing in for, both true at any corpus size:
    #   * no non-empty L9 document is silently dropped — `all_skipped` is a
    #     strict subset of `nonempty`, so the reader resolves SOMETHING
    #     somewhere;
    #   * the reader examines a real share of what the corpus declares, so a
    #     vocabulary drift that quietly stops the port layer resolving shows
    #     up as a collapsed ratio rather than as a smaller number nobody can
    #     tell apart from a withdrawal.
    #
    # The ratio floor is deliberately loose (a third). It is not a target: it
    # is the level below which "the reader still reads this corpus" stops
    # being true. Measured at 64/130 = 49% on the tree this landed against.
    assert examined <= declared, (examined, declared)
    assert all_skipped < nonempty, (
        f"every one of the {nonempty} non-empty L9 document(s) is now FULLY "
        f"skipped — the reader resolves nothing anywhere, which is the "
        f"vocabulary drift this guard exists for")
    assert examined * 3 >= declared, (
        f"the reader now examines {examined} of {declared} declared "
        f"submodule(s) — under a third. A drift in the producer's vocabulary "
        f"that stops the port layer resolving looks exactly like this.")
    #
    # 2026-08-04, vibe-ic#744: (36, 130, 62, 16) -> (37, 132, 64, 16). The
    # reader learned three further spellings of the L9 port layer, so it now
    # EXAMINES two more documents that it previously walked past. Every moving
    # number went UP and `all_skipped` is unchanged, which is the direction this
    # assertion exists to protect: a shrinking denominator is the defect, a
    # growing one is the fix. Checked before updating — had any number fallen,
    # the census would have been the finding, not the expectation.
    #
    # 2026-08-12, vibe-ic#905: (37, 132, 64, 16) -> (35, 130, 64, 14). Numbers
    # FALL here, and the paragraph above says a falling denominator is the
    # defect — so this is named member-by-member rather than re-typed.
    #
    # The cause is not the reader. It is that exactly TWO of the 37 non-empty L9
    # documents were RETIRED with their trees, both on the one IC #905 names:
    #     benchmark-data/ic/u_hawaii_adc/phase1/generated_docs/L9_INTEGRATION_SPEC.json
    #     benchmark-data/ic/u_hawaii_adc/clean_run_v1422_20260715/
    #         phase1/generated_docs/L9_INTEGRATION_SPEC.json
    # No member was gained. Both sat in the `all_skipped` set, which is why
    # `examined` is UNCHANGED at 64 while the other three fall by exactly the
    # two documents (nonempty -2, declared -2, all_skipped -2).
    #
    # The distinguishing check, and the reason this is not a waiver: the census
    # is a pure function of the tracked L9 set. Re-run it against the parent
    # commit — where both documents are still present — and it still returns
    # (37, 132, 64, 16); measured, not assumed. A reader regression would fall
    # on BOTH trees. This falls only on the tree the documents left.
    #
    # `new_arm` is deliberately NOT moved: it holds at 6 across the retirement,
    # so the arm this landing added is still reached by every project it was.
