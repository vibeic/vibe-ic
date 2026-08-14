#!/usr/bin/env python3
"""A tool diagnostic ID that was not there last time is BLOCKING (vibe-ic#1081).

Every assertion here is paired. The rule "a new ID blocks" is trivially
satisfiable by blocking always, so each red case has a green twin built from
the same fixture with one line changed — and the fixture is synthetic, owned by
this file, so neither arm depends on which cells happen to be published.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
GATE = PLUGIN_ROOT / "programs" / "tool_diagnostic_id_gate.py"

sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
import tool_diagnostic_id_gate as G  # noqa: E402

TODAY = date(2026, 8, 12)


# ---------------------------------------------------------------------------
# fixture: two runs of one synthetic cell. chip-AGNOSTIC — no design, no PDK
# content, only the diagnostic shapes the real tools emit.
# ---------------------------------------------------------------------------
_PREV_LOG = """\
[INFO ODB-0227] LEF file: /pdk/lib.lef
[WARNING RSZ-0104] Removed 3 buffers.
[WARNING PSM-0038] Vsrc file not specified.
Warning 441: constraint.sdc line 3, set_input_delay not allowed.
Warning: Replacing memory \\W with list of registers. See /abs/top.v:281
"""

#: Identical to _PREV_LOG. The unchanged-run control depends on it being byte
#: identical, so it is derived rather than re-typed.
_SAME_LOG = _PREV_LOG

#: One added line, and it is the ONLY difference.
_NEW_ID_LOG = _PREV_LOG + "[WARNING GRT-0043] Antenna violation on net n7.\n"


def _cell(root: Path, name: str, body: str, fname: str = "run.log") -> Path:
    d = root / name / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body)
    return root / name


def _run(cell: Path, acceptance: Path, today: date = TODAY):
    """Drive the SHIPPED CLI in a subprocess, so the exit code measured is the
    one an operator gets — not a return value read out of an import."""
    p = subprocess.run(
        [sys.executable, str(GATE), str(cell), "--acceptance", str(acceptance),
         "--today", today.isoformat()],
        capture_output=True, text=True, timeout=55)
    return p.returncode, p.stdout + p.stderr


def _acc(path: Path, entries) -> Path:
    path.write_text(json.dumps({"accepted": entries}))
    return path


# ===========================================================================
# THE RULE, both directions
# ===========================================================================
def test_a_new_diagnostic_id_BLOCKS(tmp_path):
    """THE DEFECT ORFS leaves as a warning: a brand-new ID must fail the run."""
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _NEW_ID_LOG)
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 1, f"a new diagnostic id did not block; rc={rc}\n{out}"
    assert "GRT-0043" in out, out
    assert "v1.0.0_pdkX" in out, "the report must name what it compared against"


def test_PAIRED_GUARD_an_unchanged_run_PASSES(tmp_path):
    """The twin. Without it, "block on new ids" is satisfied by blocking always
    — a ban, not a check. Same fixture, same everything, no added line."""
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _SAME_LOG)
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 0, f"an unchanged run must PASS; rc={rc}\n{out}"


def test_a_REMOVED_id_does_not_block(tmp_path):
    """Direction 3: fewer warnings than last time is not a regression. A gate
    that blocked on any DIFFERENCE would punish the fix that removed one."""
    _cell(tmp_path, "v1.0.0_pdkX", _NEW_ID_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _PREV_LOG)
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 0, f"a removed id must not block; rc={rc}\n{out}"


def test_the_standalone_OpenSTA_numbered_form_is_compared_too(tmp_path):
    """Family B. ORFS's regex sees only `[WARNING X-0001]`; our corpus carries
    86,449 `Warning 1650:` lines that shape would silently drop."""
    _cell(tmp_path, "v1.0.0_pdkX", "Warning 441: sdc line 3, nope.\n")
    cur = _cell(tmp_path, "v1.1.0_pdkX",
                "Warning 441: sdc line 3, nope.\n"
                "Warning 1650: x.spef line 9, net n1 not found.\n")
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 1, f"a new OpenSTA-numbered id did not block\n{out}"
    assert "STA-1650" in out, out


def test_INFO_ids_are_censused_but_do_not_block(tmp_path):
    """The stated scope decision, pinned so it cannot drift into a surprise.

    Both runs carry a steady WARNING so the comparison has a real gated
    population — without it the pair is VACUOUS and returns 2, and this test
    would have been asserting the vacuity rule while appearing to assert the
    INFO rule. (It did, until the vacuity fix above made it say so.)
    """
    base = "[WARNING RSZ-0104] steady\n[INFO DRT-0036] start\n"
    _cell(tmp_path, "v1.0.0_pdkX", base)
    cur = _cell(tmp_path, "v1.1.0_pdkX", base + "[INFO DRT-0199] progress\n")
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 0, f"a new INFO id must not block; rc={rc}\n{out}"
    # ...and the INFO id really is in the census, so "does not block" is not
    # "was never seen".
    cen = G.census(cur)
    assert "DRT-0199" in cen["steps"]["reports/phase3"]["ids"]["INFO"]


# ===========================================================================
# THE HONEST LIMIT
# ===========================================================================
def test_no_previous_run_exits_2_and_says_so(tmp_path):
    """A first run is not a clean run. Exit 2, never 0."""
    cur = _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 2, f"a cell with no baseline must exit 2, got {rc}\n{out}"
    assert "no previous run" in out and "nothing compared" in out, out


def test_a_run_with_NO_gated_ids_is_VACUOUS_not_a_PASS(tmp_path):
    """Found by this program's own two-arm demo, which printed
    `[PASS] ... no new diagnostic id (0 compared)` over a real cell pair that
    yields no gated ids.

    `len(new) == 0` over a population of zero is vacuously true, and it is far
    likelier to mean the scan found nothing than that the tools emitted
    nothing. It rendered identically to a real clean comparison — the exact
    defect this gate exists to remove, in the gate itself. Tri-state: 2.
    """
    _cell(tmp_path, "v1.0.0_pdkX", "nothing diagnostic here at all\n")
    cur = _cell(tmp_path, "v1.1.0_pdkX", "still nothing\n")
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 2, f"an empty comparison must not be a PASS; rc={rc}\n{out}"
    assert "VACUOUS" in out and "vacuously true" in out, out


def test_PAIRED_an_EMPTY_PREVIOUS_run_still_gates(tmp_path):
    """The control for the rule above, and the half that must NOT be swallowed
    by it. An empty PREVIOUS run is fine — every id in the current run is then
    new, and the gate must say so rather than call the pair vacuous."""
    _cell(tmp_path, "v1.0.0_pdkX", "nothing diagnostic here at all\n")
    cur = _cell(tmp_path, "v1.1.0_pdkX", _PREV_LOG)
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 1, f"ids new against an empty baseline must block; rc={rc}\n{out}"
    assert "RSZ-0104" in out, out


def test_the_previous_run_is_chosen_by_PARSED_version_not_string_order(
        tmp_path):
    """`v1.9.10` precedes `v1.9.9` as a STRING. Sorting by name would compare
    against the wrong run and invert the answer."""
    _cell(tmp_path, "v1.9.9_pdkX", _PREV_LOG)
    _cell(tmp_path, "v1.9.10_pdkX", _NEW_ID_LOG)
    cur = _cell(tmp_path, "v1.9.11_pdkX", _NEW_ID_LOG)
    prev = G.find_previous(cur)
    assert prev is not None and prev.name == "v1.9.10_pdkX", prev
    rc, _ = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 0, "v1.9.11 vs v1.9.10 adds nothing and must pass"


def test_a_different_PDK_is_a_different_cell(tmp_path):
    """Two PDKs are not two runs of one thing; comparing across them would
    report every PDK-specific id as new."""
    _cell(tmp_path, "v1.0.0_pdkY", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _PREV_LOG)
    assert G.find_previous(cur) is None
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 2, out


def test_unkeyed_diagnostics_are_disclosed_not_silently_dropped(tmp_path):
    """Yosys emits `Warning: <free text>` with no id. It cannot be compared,
    and the report must SAY so — otherwise `0 new ids` reads as `0 new
    warnings`."""
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _SAME_LOG)
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 0
    assert "unkeyed" in out and "NOT compared" in out, out


# ===========================================================================
# THE ACCEPTANCE LIST, AND THE CHECKING OF IT
# ===========================================================================
def test_an_accepted_id_does_not_block(tmp_path):
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _NEW_ID_LOG)
    acc = _acc(tmp_path / "a.json", [{
        "id": "GRT-0043", "reason": "known antenna chatter, tracked in #X",
        "accepted_on": "2026-08-01", "expires_on": "2026-12-01",
        "adjudicated_by": "tester"}])
    rc, out = _run(cur, acc)
    assert rc == 0, f"an adjudicated id must not block; rc={rc}\n{out}"
    assert "GRT-0043" in out


def test_an_EXPIRED_acceptance_entry_blocks_loudly(tmp_path):
    """The whole point of the date. Expiry that costs nothing is decoration."""
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _NEW_ID_LOG)
    acc = _acc(tmp_path / "a.json", [{
        "id": "GRT-0043", "reason": "was fine once",
        "accepted_on": "2026-01-01",
        "expires_on": (TODAY - timedelta(days=1)).isoformat(),
        "adjudicated_by": "tester"}])
    rc, out = _run(cur, acc)
    assert rc == 1, f"an expired entry must block; rc={rc}\n{out}"
    assert "EXPIRED" in out, out


def test_a_STALE_acceptance_entry_blocks(tmp_path):
    """An exemption for an id nothing emits any more. It accumulates silently
    and each one widens the hole; it must expire loudly instead."""
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _SAME_LOG)
    acc = _acc(tmp_path / "a.json", [{
        "id": "ZZZ-9999", "reason": "long gone", "accepted_on": "2026-01-01",
        "expires_on": "2026-12-01", "adjudicated_by": "tester"}])
    rc, out = _run(cur, acc)
    assert rc == 1, f"a stale entry must block; rc={rc}\n{out}"
    assert "STALE" in out, out


@pytest.mark.parametrize("missing",
                         ["reason", "accepted_on", "expires_on",
                          "adjudicated_by"])
def test_an_UNSIGNED_or_UNDATED_entry_blocks(tmp_path, missing):
    """An exemption nobody signed or dated is not an adjudication."""
    entry = {"id": "GRT-0043", "reason": "r", "accepted_on": "2026-08-01",
             "expires_on": "2026-12-01", "adjudicated_by": "t"}
    del entry[missing]
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _NEW_ID_LOG)
    rc, out = _run(cur, _acc(tmp_path / "a.json", [entry]))
    assert rc == 1, f"missing {missing} must block; rc={rc}\n{out}"
    assert "missing required field" in out, out


def test_the_SHIPPED_acceptance_list_passes_its_own_audit():
    """The file we ship must satisfy the rules it documents — otherwise the
    first real run blocks on our own list rather than on a tool."""
    shipped = PLUGIN_ROOT / "programs" / "tool_diagnostic_id_acceptance.json"
    entries = G.load_acceptance(shipped)
    # every id present -> nothing can be reported stale; this isolates the
    # malformed/expired rules, which are the ones about the file itself.
    present = {str(e.get("id")): ["x"] for e in entries if isinstance(e, dict)}
    problems = G.audit_acceptance(entries, present, date.today())
    assert problems == [], problems


# ===========================================================================
# the gate must not eat its own output
# ===========================================================================
def test_the_gates_own_report_is_not_read_back_as_tool_output(tmp_path):
    """The report names every new id it found. Written into the cell it
    describes, the next run would read those ids as tool output and complain
    about its own complaint."""
    _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cur = _cell(tmp_path, "v1.1.0_pdkX", _SAME_LOG)
    (cur / "reports" / "phase3" / "prior_report.json").write_text(json.dumps({
        "schema": G.SCHEMA, "new_ids": {"GRT-0043": ["reports/phase3"]},
        "note": "[WARNING GRT-0043] would be read as tool output"}))
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 0, (
        f"the gate read its own previous report as tool output; rc={rc}\n{out}")


# ===========================================================================
# the #1080 fold — the shape is asserted, not just described in prose
# ===========================================================================
def test_the_census_shape_folds_into_per_step_metrics(tmp_path):
    """#1080 is the per-step metrics schema and is unimplemented. This pins the
    shape it can absorb: two levels under `steps.<step>.ids.<LEVEL>.<ID>`,
    flattenable to `<step>__tool__warnings__count:<ID>` with no second scan and
    no second definition of what an id is."""
    cell = _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cen = G.census(cell)
    assert cen["schema"] == G.SCHEMA
    step = "reports/phase3"
    assert step in cen["steps"], cen["steps"].keys()
    ids = cen["steps"][step]["ids"]
    assert ids["WARNING"]["RSZ-0104"] == 1
    assert ids["INFO"]["ODB-0227"] == 1
    flat = {f"{s}__tool__warnings__count:{i}": n
            for s, slot in cen["steps"].items()
            for i, n in slot["ids"].get("WARNING", {}).items()}
    assert flat["reports/phase3__tool__warnings__count:RSZ-0104"] == 1


# ===========================================================================
# ANTI-ROT: the three claims this gate makes ABOUT THE REPOSITORY
#
# Everything above is decided on a fixture this file owns, which is why it is
# host-independent. These three are different in kind: they are the statements
# the docstring and the acceptance list make about the TREE, and the first draft
# of both got every one of them wrong — 1068 `*.log` (57), 86,449 `Warning 1650`
# (0, and the only four in the repository were inside this feature's own two
# files), thirteen prefixes (16), 1,183 `DRT-0036` (692), and a worked example
# naming two cells that do not exist. Prose cannot be trusted to stay true, so
# each claim is re-derived here and a drift is a RED, not a stale sentence.
# ===========================================================================
REPO_ROOT = PLUGIN_ROOT.parents[2]
BD_IC = REPO_ROOT / "benchmark-data" / "ic"


def _published_cells():
    """Every `benchmark-data/ic/<IC>/v<ver>_<PDK>/` this commit carries."""
    if not BD_IC.is_dir():
        return []
    return sorted(c for d in BD_IC.iterdir() if d.is_dir()
                  for c in d.iterdir()
                  if c.is_dir() and G._cell_ordinal(c.name) is not None)


@pytest.mark.skipif(not BD_IC.is_dir(), reason="no benchmark-data/ic in tree")
def test_the_prefix_coverage_claim_is_re_derived():
    """The COVERAGE claim, recomputed from the tree.

    WHY THIS ONE AND NOT THE FILE COUNTS. The docstring also states 57 `*.log`
    and 2719 scanned-suffix files. Those are pinned NOWHERE on purpose: every
    publish or prune moves them, so asserting them would make this file go red
    for reasons that have nothing to do with diagnostics — a test measuring the
    publication schedule, which is the #527 defect. They are labelled in the
    docstring as observations AT a named commit, and that label is checked
    below instead.

    The prefix SET is different in kind: it changes only when a tool that was
    not emitting diagnostics starts to, and that IS an event this gate's
    coverage claim depends on. The regex deliberately does not restrict the
    prefix, so behaviour is already safe; what this protects is the SENTENCE,
    which is what a reader uses to decide whether the gate covers their tool.
    """
    # Whitespace-normalised: the docstring wraps at 79 columns, so the list
    # spans two lines. Comparing against the raw text would fail on a reflow,
    # which is a formatting event and not a coverage event.
    doc = " ".join(G.__doc__.split())
    prefixes = {m.group("id").split("-")[0]
                for p in BD_IC.rglob("*")
                if p.is_file() and p.suffix in G._SCANNED_SUFFIXES
                for m in G._RE_BRACKETED.finditer(p.read_text(errors="replace"))}
    assert prefixes, "no bracketed ids found at all — the probe is broken"
    assert " ".join(sorted(prefixes)) in doc, (
        f"the prefix coverage sentence drifted. Tree says {sorted(prefixes)}; "
        f"put exactly '{' '.join(sorted(prefixes))}' in the docstring. A new "
        f"prefix means a tool started emitting diagnostics and the coverage "
        f"claim a reader relies on is now understated.")
    assert "94754771" in doc or "4b22e36ea" in doc, (
        "the docstring states raw file counts; they must stay attributed to the "
        "commit they were measured at, or they read as standing facts about a "
        "tree that has since moved")


@pytest.mark.skipif(not BD_IC.is_dir(), reason="no benchmark-data/ic in tree")
def test_the_corpus_pair_resolves_and_the_gate_fires():
    """THE REPLACEMENT for a test that was meant to die, and did.

    Its predecessor asserted "5 of 5 cells exit NO_BASELINE" and said it would
    fail the day a pair became comparable. That day came from a CODE fix rather
    than from a publish: the resolver was reading the PDK out of the directory
    name, so the repository's `clean_run_*` naming family was invisible and the
    one genuinely like-for-like pair was skipped. The premise died exactly as
    designed; this asserts what replaced it.

    Backed by a COMMITTED artefact, not a fixture: `DRT-0120` is absent from
    v1422's `reports/phase3/drc_router.rpt` and present in v1427's, and that is
    re-derived here rather than trusted.
    """
    prev = BD_IC / "sha256" / "clean_run_v1422_20260715"
    cur = BD_IC / "sha256" / "clean_run_v1427_20260715"
    for p in (prev, cur):
        if not p.is_dir():
            pytest.skip(f"published run absent from this checkout: {p}")

    # 1. the resolver finds it, with no flag and no caller knowledge
    found = G.find_previous(cur)
    assert found is not None and found.name == prev.name, (
        f"the like-for-like predecessor was not resolved: got {found}. Both runs "
        f"record the same PDK ({G.measured_pdk(cur)} / {G.measured_pdk(prev)}) "
        f"and both are the same naming family, so a NO_BASELINE here means the "
        f"resolver has regressed to parsing names again.")

    # 2. the difference it must find is real, checked against the bytes
    rpt = "reports/phase3/drc_router.rpt"
    assert "DRT-0120" not in (prev / rpt).read_text(errors="replace")
    assert "DRT-0120" in (cur / rpt).read_text(errors="replace")

    # 3. and the gate BLOCKS on it
    shipped = PLUGIN_ROOT / "programs" / "tool_diagnostic_id_acceptance.json"
    rc, report = G.compare(cur, prev, shipped, date(2026, 8, 12))
    assert rc == 1, f"the gate did not block on a real new id: rc={rc} {report}"
    assert "DRT-0120" in report["new_ids_blocking"], report["new_ids_blocking"]


#: Two sibling runs of ONE design, same naming FAMILY (`run_seq`), neither
#: recording a `"pdk"` field anywhere — the shape `_cell` produces writes only
#: `reports/phase3/run.log`, so `measured_pdk` finds nothing and `_RE_CELL`
#: does not match the name either. This is the only shape in which the refusal
#: rule is REACHABLE: `_cell_ordinal` must already agree (same family, lower
#: ordinal) before `pdk_key` is ever consulted.
_UNSTATED_PREV = "clean_run_v1400_20260101"
_UNSTATED_CUR = "clean_run_v1401_20260102"


def test_a_run_that_states_no_pdk_is_refused_not_assumed_to_match(tmp_path):
    """"I could not tell" must never resolve to "same".

    SYNTHETIC, and that is the repair. This test used to build its own subjects
    by calling the function under test::

        unstated = [c for c in _published_cells() if G.pdk_key(c) is None]
        if not unstated:
            pytest.skip("every run dir now records a PDK — the hazard is gone")

    A regression that stops `pdk_key` returning None — THE EXACT DEFECT THIS
    TEST NAMES — empties that list, and the skip then states as a fact the
    thing the regression destroyed. MEASURED on this tree: with `pdk_key`
    falling back to a constant `"UNKNOWN"` instead of None, the module reports
    `30 passed, 1 skipped`, exit 0, while `find_previous` pairs two runs whose
    process is unknown. That is the 18-false-positive mistake the PDK guard
    exists to prevent, arriving through the guard's own population.

    The corpus arm was vacuous for a second, independent reason and is kept
    below only as an observation: the one published cell that yields no key,
    `u_hawaii_adc/clean_run_v1422_20260715`, has no same-FAMILY sibling beneath
    it, so `_cell_ordinal` refuses it before the PDK rule is consulted. It
    could not have exercised this path even when the list was non-empty.
    """
    _cell(tmp_path, _UNSTATED_PREV, _PREV_LOG)
    cur = _cell(tmp_path, _UNSTATED_CUR, _NEW_ID_LOG)

    # the precondition: neither run states a PDK, by either channel
    assert G.pdk_key(cur) is None, G.pdk_key(cur)
    assert G.pdk_key(tmp_path / _UNSTATED_PREV) is None

    # and so the pair is REFUSED, though everything else about it matches
    assert G.find_previous(cur) is None, (
        f"{_UNSTATED_CUR} states no PDK and a predecessor was resolved for it "
        f"anyway ({G.find_previous(cur)}). An unmeasurable PDK must refuse, "
        f"not match.")

    # end to end, through the shipped CLI: NO_BASELINE (rc 2), not a comparison
    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 2, f"expected NO_BASELINE, got rc={rc}: {out}"


def test_PAIRED_GUARD_the_same_pair_STATING_a_pdk_does_compare(tmp_path):
    """The refusal must be about the silence, not about the naming family.

    Byte-identical fixture to the test above with ONE addition — each run
    records `"pdk": "sky130A"` in its own reports — and it must now resolve,
    compare, and BLOCK on the added `GRT-0043`. Without this twin, the refusal
    rule above is satisfiable by never matching a `clean_run_*` pair at all,
    which is the very defect #1092's resolver was fixed for.
    """
    prev = _cell(tmp_path, _UNSTATED_PREV, _PREV_LOG)
    cur = _cell(tmp_path, _UNSTATED_CUR, _NEW_ID_LOG)
    for c in (prev, cur):
        (c / "reports" / "run_meta.json").write_text('{"pdk": "sky130A"}\n')

    assert G.pdk_key(cur) == "sky130A"
    assert G.find_previous(cur) == prev, G.find_previous(cur)

    rc, out = _run(cur, _acc(tmp_path / "a.json", []))
    assert rc == 1, f"expected BLOCKING, got rc={rc}: {out}"
    assert "GRT-0043" in out


@pytest.mark.skipif(not BD_IC.is_dir(), reason="no benchmark-data/ic in tree")
def test_the_published_cells_that_state_no_pdk_are_refused_too():
    """The corpus arm, no longer load-bearing and no longer self-selecting.

    It carries NO skip: an empty list is simply a corpus that states a PDK
    everywhere, and the obligation is already discharged synthetically above.
    An empty result is recorded as an empty result — never as "the hazard is
    gone".
    """
    unstated = [c for c in _published_cells() if G.pdk_key(c) is None]
    for c in unstated:
        assert G.find_previous(c) is None, (
            f"{c.name} states no PDK and a predecessor was resolved for it "
            f"anyway ({G.find_previous(c)}). An unmeasurable PDK must refuse, "
            f"not match.")


def test_the_unwired_state_is_disclosed_or_gone():
    """Wiring is MEASURED, and the disclosure dies with it.

    Both directions, which is the whole point: while nothing invokes this
    program the docstring must carry the NOT WIRED section, and the moment
    somebody wires it this test fails and forces the section out. Neither state
    can be reached by editing prose alone.
    """
    name = "tool_diagnostic_id_gate"
    own = {GATE.name, "test_tool_diagnostic_id_gate.py",
           "tool_diagnostic_id_acceptance.json", "INDEX.md"}
    callers = []
    for d in (PLUGIN_ROOT / "flow", PLUGIN_ROOT / "benchmark",
              PLUGIN_ROOT / "programs"):
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.name in own:
                continue
            if p.suffix not in (".py", ".yaml", ".yml", ".json", ".md"):
                continue
            try:
                if name in p.read_text(errors="replace"):
                    callers.append(p.relative_to(PLUGIN_ROOT).as_posix())
            except OSError:
                continue
    disclosed = "NOT WIRED YET" in G.__doc__
    if callers:
        assert not disclosed, (
            f"{name} is now referenced by {sorted(callers)} — it is wired. "
            f"Delete the 'NOT WIRED YET' section from the docstring; a stale "
            f"disclosure is worse than none because a reader trusts it.")
    else:
        assert disclosed, (
            f"nothing in flow/, benchmark/ or programs/ invokes {name}, so it "
            f"cannot block anything, and the docstring does not say so. An "
            f"unwired checker presented as BLOCKING is the D9 defect this "
            f"campaign removes.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- vibe-ic#1241: polarity, and that it discriminates ---------------------
def test_a_DENIED_id_is_not_counted_as_an_emission():
    """`prose_polarity_consulted_check` only asks whether the module is
    CONSULTED. A call whose result is discarded satisfies it and changes
    nothing, so the behaviour is pinned here instead."""
    out = G.scan_log("no [WARNING RSZ-0104] were emitted this run\n")
    assert out["ids"] == {}, out
    assert out["denied_count"] == 1, out


def _pdk_cell(tmp_path, **files):
    """A run directory holding *files*, for `measured_pdk` to read."""
    d = tmp_path / "cell"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text)
    return d


def test_a_DENIED_pdk_is_not_counted_as_a_declaration(tmp_path):
    """BATCH IDX (c). `measured_pdk` scans RAW TEXT and takes the modal value,
    so records that deny a value used to outvote the one real declaration and
    the gate compared two runs on a PDK neither of them used.

    Two things in the consult are load-bearing and were measured:
    `ignore_bracketed=False`, because the prose default blanks `{...}` and a
    JSON document is entirely inside braces — with the default this check is a
    no-op that reads like a check; and `extra_breaks=("\n",)`, because these
    are machine-generated records, not prose.
    """
    cell = _pdk_cell(
        tmp_path,
        **{"audit.json": '{"pdk": "sky130A", "staged": false, '
                         '"note": "libraries were not staged"}\n'
                         '{"pdk": "sky130A", "status": "superseded by the '
                         'gf180 rerun"}\n',
           "run.json": '{"pdk": "gf180mcuD"}\n'})
    # Both sky130A records match the regex — without that this proves nothing.
    text = (cell / "audit.json").read_text()
    assert len(list(G._RE_PDK_FIELD.finditer(text))) == 2
    assert G.measured_pdk(cell) == "gf180mcuD"


def test_a_DENIAL_ON_ANOTHER_RECORD_does_not_retract_this_one(tmp_path):
    """THE PAIRED HALF. A report full of ordinary negations must still yield
    its PDK, or the consult trades a loud wrong answer for a silent missing
    one — which this module's own docstring calls the worse failure, because
    nothing goes red to say the extractor published less than it read."""
    cell = _pdk_cell(
        tmp_path,
        **{"a.json": '{"pdk": "sky130A"}\n'
                     '{"note": "no clock found for register bank"}\n'
                     '{"drc": "no errors found"}\n'})
    assert G.measured_pdk(cell) == "sky130A"


def test_a_plain_declaration_is_untouched(tmp_path):
    """The consult must not cost the ordinary case anything."""
    cell = _pdk_cell(tmp_path, **{"a.json": '{"pdk": "sky130A"}\n'})
    assert G.measured_pdk(cell) == "sky130A"


def test_the_known_limit_is_pinned_rather_than_hidden(tmp_path):
    """A denial in a SIBLING FIELD of the same record drops the value, even
    when it denies something else entirely.

    This is a FALSE NEGATIVE and it is pinned deliberately, because the two
    shapes are structurally identical —

        {"pdk": "sky130A", "status": "superseded by the gf180 rerun"}   deny
        {"pdk": "sky130A", "drc": "no errors found"}                    keep

    — and separating them needs to know what the denial is ABOUT, which no
    scoping rule can. The direction chosen is the one `pdk_key` already argues
    for: a dropped measurement falls back to the NAME, so this degrades to the
    pre-existing comparison rather than to nothing, while the opposite error
    would make the gate compare on a PDK neither run used.

    MEASURED COST: 0 of the 9 `"pdk"` declarations in the tracked corpus sit in
    a record carrying a denial, so this costs nothing today. If that number
    moves, this test is where to come back to — change it by NARROWING the
    scope, never by dropping the consult.
    """
    cell = _pdk_cell(
        tmp_path,
        **{"a.json": '{"pdk": "sky130A", "drc": "no errors found"}\n'})
    assert G.measured_pdk(cell) is None


def test_a_NEGATION_INSIDE_THE_MESSAGE_still_counts_as_an_emission():
    """THE PAIRED HALF, and the one that matters. A diagnostic line IS the
    emission; its message is ordinary English that routinely negates something
    about the design. Scanning the whole sentence dropped every id in this
    file's fixtures and turned eight tests rc 2 VACUOUS — measured, which is
    why the span is what PRECEDES the match."""
    out = G.scan_log("[WARNING RSZ-0104] no clock found for register bank\n")
    assert out["ids"] == {"WARNING": {"RSZ-0104": 1}}, out
    assert out["denied_count"] == 0, out


# ===========================================================================
# THE SHIPPED ACCEPTANCE RECORD'S CLAIM ABOUT THE CORPUS
#
# `tool_diagnostic_id_acceptance.json` carries prose about whether the gate can
# compare anything at all. That claim went stale silently once, and the way it
# went stale is the interesting part: the file honestly recorded "5 of 5
# NO_BASELINE ... the comparison path is unreachable from today's corpus", and
# that was a correct measurement OF A BROKEN RESOLVER read as a fact about the
# POPULATION. It also promised the situation could only change when a second
# same-PDK cell was PUBLISHED — and a code fix reached it instead.
#
# An unreachable-comparison disclosure reads identically whether the corpus
# really has no pair or the resolver merely cannot see one. So the claim is
# recomputed here rather than trusted.
# ===========================================================================
_ACCEPTANCE = PLUGIN_ROOT / "programs" / "tool_diagnostic_id_acceptance.json"

#: The sentinel each state must carry. Kept as literals so the assertion is
#: about the SHIPPED WORDS a reader will actually see, not about a paraphrase.
_SAYS_UNREACHABLE = "comparison path is unreachable"
_SAYS_REACHABLE = "THE COMPARISON PATH IS REACHABLE"


def _acceptance_prose() -> str:
    """The record's text as a reader reads it, with line wrapping removed.

    WHITESPACE-NORMALISED ON PURPOSE. `_comment` is a JSON array of hard-wrapped
    lines, so every sentinel below would otherwise be hostage to where the wrap
    happens to fall — re-flowing a paragraph would silently turn an assertion
    about the claim into an assertion about the column width. Measured while
    writing this: `must not adjudicate his own finding` straddles a wrap and a
    naive join missed it.
    """
    return " ".join(" ".join(
        json.loads(_ACCEPTANCE.read_text())["_comment"]).split())


def _comparable_pairs():
    """Every (cell, predecessor) the resolver actually finds in this tree."""
    return [(c, G.find_previous(c)) for c in _published_cells()
            if G.find_previous(c) is not None]


@pytest.mark.skipif(not BD_IC.is_dir(), reason="no benchmark-data/ic in tree")
def test_the_acceptance_records_REACHABILITY_claim_is_measured():
    """BOTH DIRECTIONS, so neither state is reachable by editing prose.

    While a comparable pair exists the shipped record must NOT claim the
    comparison path is unreachable, and must say it IS reachable. If the corpus
    ever loses its last pair — a prune, a retention sweep — the disclosure has
    to come back, because at that moment "no new diagnostic id" would again be
    a statement about a comparison nobody performed.
    """
    prose = _acceptance_prose()
    pairs = _comparable_pairs()
    withdrawn = "That was an honest measurement of" in prose

    if pairs:
        shown = [f"{c.name} <- {p.name}" for c, p in pairs]
        assert _SAYS_UNREACHABLE not in prose or withdrawn, (
            f"{len(pairs)} comparable pair(s) exist ({shown}) and the shipped "
            f"acceptance record still claims the comparison path is "
            f"unreachable. A record that outlived its premise reads exactly "
            f"like a true one.")
        assert _SAYS_REACHABLE in prose, (
            f"{len(pairs)} comparable pair(s) exist ({shown}) and the record "
            f"does not say so. A reader deciding whether this empty list means "
            f"'nothing to adjudicate' or 'nothing was compared' cannot tell.")
    else:
        assert _SAYS_UNREACHABLE in prose, (
            "no comparable pair resolves in this tree, so the gate cannot "
            "compare anything — and the acceptance record does not disclose "
            "it. An empty list then reads as 'clean' when it means 'never "
            "ran'.")
        assert _SAYS_REACHABLE not in prose, (
            "the record claims the comparison path is reachable and no pair "
            "resolves.")


@pytest.mark.skipif(not BD_IC.is_dir(), reason="no benchmark-data/ic in tree")
def test_PAIRED_the_live_finding_is_NOT_adjudicated_by_its_own_author():
    """The empty list is a POSITION, and it has to stay checkable.

    The corpus pair blocks on a real id. The cheapest way to make every run
    green is to add that id to `accepted` — which is why this asserts the
    opposite: the shipped list stays empty while a live un-adjudicated finding
    exists, and the record says so.

    Without this half the test above is satisfiable by adjudicating the finding
    away and then truthfully reporting a reachable-and-clean corpus.
    """
    pairs = _comparable_pairs()
    if not pairs:
        pytest.skip("no comparable pair in this tree")
    doc = json.loads(_ACCEPTANCE.read_text())
    blocking = set()
    for cur, prev in pairs:
        rc, report = G.compare(cur, prev, _ACCEPTANCE, date.today())
        blocking |= set(report.get("new_ids_blocking") or {})
    assert blocking, (
        "the corpus pair resolves and nothing blocks — either the finding was "
        "adjudicated into `accepted` or the comparison stopped finding it; "
        "both need saying out loud rather than reading as a clean run.")
    accepted_ids = {e.get("id") for e in doc["accepted"] if isinstance(e, dict)}
    assert not (blocking & accepted_ids), (
        f"{sorted(blocking & accepted_ids)} is both the live finding and its "
        f"own exemption. The point of shipping this list empty is that the "
        f"author must not adjudicate his own finding.")
    assert "must not adjudicate his own finding" in _acceptance_prose()
