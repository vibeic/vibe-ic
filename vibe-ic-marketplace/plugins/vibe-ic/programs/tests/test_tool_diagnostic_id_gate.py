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
    """The census is keyed BY STEP — two levels under
    `steps.<step>.ids.<LEVEL>.<ID>` — which is the shape #1080's per-step
    metrics schema absorbs with no second scan and no second definition of what
    an id is. The fold itself is exercised by the `#1081 ITEM 1` block below;
    this pins the shape it folds FROM.

    (Until 2026-08-14 this docstring asserted that "#1080 is ... unimplemented".
    It landed as `4a8c4bf6b`, and a test premise that has expired is how a
    deferral becomes permanent, so the fold is now measured rather than
    described.)
    """
    cell = _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    cen = G.census(cell)
    assert cen["schema"] == G.SCHEMA
    step = "reports/phase3"
    assert step in cen["steps"], cen["steps"].keys()
    ids = cen["steps"][step]["ids"]
    assert ids["WARNING"]["RSZ-0104"] == 1
    assert ids["INFO"]["ODB-0227"] == 1


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
                  if c.is_dir() and G._parse_cell_name(c.name) is not None)


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
    assert "4b22e36ea" in doc, (
        "the docstring states raw file counts; they must stay attributed to the "
        "commit they were measured at, or they read as standing facts about a "
        "tree that has since moved")


@pytest.mark.skipif(not BD_IC.is_dir(), reason="no benchmark-data/ic in tree")
def test_the_published_corpus_yields_no_comparable_pair():
    """5 of 5 cells exit NO_BASELINE on this commit — and that is DISCLOSED.

    THIS TEST IS MEANT TO DIE. It fails the day a second cell of the same PDK is
    published, which is the day the gate can finally compare something and the
    day the docstring's "today it is every cell" paragraph becomes false. A
    disclosure that outlives its premise is exactly the rot this repo keeps
    finding, so the premise is asserted rather than described.
    """
    cells = _published_cells()
    assert cells, "no published cells found — the probe itself is broken"
    comparable = [(c.name, G.find_previous(c).name)
                  for c in cells if G.find_previous(c) is not None]
    assert not comparable, (
        f"a comparable cell pair now EXISTS: {comparable}. The gate can compare "
        f"for real, so remove the 'today it is every cell' disclosure from the "
        f"docstring, re-run the gate over that pair, and record what it finds — "
        f"including in tool_diagnostic_id_acceptance.json, whose text says the "
        f"comparison path is unreachable.")
    assert "5 of 5" in G.__doc__ or f"{len(cells)} of {len(cells)}" in G.__doc__, (
        f"{len(cells)} published cells carry no comparable pair and the docstring "
        f"does not say so; a reader of 'is BLOCKING' would assume it blocks.")


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
# #1081 ITEM 1 — "count tool diagnostics by message ID per step, AS A METRIC"
#
# The issue's own caveat was "(depends on the per-step metrics schema)". That
# dependency is #1080, landed as `4a8c4bf6b` (`programs/step_metrics.py`), so
# the deferral has expired. Measured before this block existed: the gate
# censused 370 logs of one published cell and `step_metrics collect` over that
# same run answered `0 metric(s) from 0 step(s)`, rc 2 — the count existed only
# inside a report nothing collects.
#
# Every case here is PAIRED, because "emits a metric" is trivially satisfiable
# by emitting a constant.
# ===========================================================================
import step_metrics as SM  # noqa: E402

#: `_PREV_LOG` carries WARNING RSZ-0104, WARNING PSM-0038, `Warning 441:`
#: (-> STA-0441), INFO ODB-0227, and one unkeyed Yosys line. Written out so a
#: change to the fixture moves these numbers RED rather than silently.
_STEP = "reports_phase3"
_EXPECTED_PREV = {
    f"{_STEP}__tool__id__rsz_0104__warning_count": 1,
    f"{_STEP}__tool__id__psm_0038__warning_count": 1,
    f"{_STEP}__tool__id__sta_0441__warning_count": 1,
    f"{_STEP}__tool__id__odb_0227__info_count": 1,
    f"{_STEP}__tool__gated__id_count": 3,
    f"{_STEP}__tool__logs__scanned_count": 1,
    f"{_STEP}__tool__unkeyed__diagnostic_count": 1,
    f"{_STEP}__tool__denied__diagnostic_count": 0,
}


def _emit(tmp_path, name, body, project_name="proj"):
    cell = _cell(tmp_path, name, body)
    project = tmp_path / project_name
    G.emit_metrics(G.census(cell), project)
    return project


def test_the_per_step_census_IS_emitted_as_metrics(tmp_path):
    """Item 1, end to end: every id, per step, as a metric with its count."""
    project = _emit(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    merged, prov = SM.collect(project)
    assert prov["step_count"] == 1, prov
    for key, want in _EXPECTED_PREV.items():
        assert merged.get(key) == want, (key, merged.get(key), merged)


def test_PAIRED_the_emitted_metrics_pass_step_metrics_OWN_schema_check(
        tmp_path):
    """An emit that #1080's own conformance check rejects is not an emit.

    THE ARM THAT MATTERS. ORFS spells this `cts__flow__warnings__count:ORD-0012`
    and copying that spelling would have been the obvious move — it fails
    `key_defect` (a colon and capitals inside one component), so `step_metrics
    check` would go red on every run that emitted one. The id is a component
    instead, and this asserts the result against the schema owner rather than
    against a regex this file wrote.
    """
    project = _emit(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    assert SM.conformance_defects(project) == []
    for key in _EXPECTED_PREV:
        assert SM.key_defect(key) is None, key


def test_PAIRED_nothing_is_emitted_unless_asked(tmp_path):
    """The census must not write metrics as a side effect of being taken.

    Without this the previous test passes for a program that writes metrics on
    every run into whatever directory it happens to be pointed at.
    """
    cell = _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    project = tmp_path / "untouched"
    G.census(cell)
    assert not project.exists()
    rc, out = _run(cell, _acc(tmp_path / "a.json", []))
    assert rc == 2, out          # NO_BASELINE, and still no metrics dir
    assert not (cell / SM.METRICS_REL).exists(), out


# --- the run-to-run direction: a NEW id is an ADDED metric key -------------
def test_a_NEW_id_shows_up_as_an_ADDED_metric_KEY(tmp_path):
    """The metric layer REPORTS the same fact the gate BLOCKS on.

    `step_metrics diff` lists a key present in the new run and absent from the
    old under `added` — which for `<step>__tool__id__<id>__warning_count` is
    exactly "a tool warning id that was not there last time", per step.
    """
    old = _emit(tmp_path, "v1.0.0_pdkX", _PREV_LOG, "old")
    new = _emit(tmp_path, "v1.1.0_pdkX", _NEW_ID_LOG, "new")
    rep = SM.diff(SM.collect(old)[0], SM.collect(new)[0])
    assert f"{_STEP}__tool__id__grt_0043__warning_count" in rep["added"], rep


def test_PAIRED_an_UNCHANGED_run_adds_no_metric_key(tmp_path):
    """Same fixture, one line changed — here, none. `added` must be empty, or
    the test above is satisfied by a differ that calls everything new."""
    old = _emit(tmp_path, "v1.0.0_pdkX", _PREV_LOG, "old")
    new = _emit(tmp_path, "v1.1.0_pdkX", _SAME_LOG, "new")
    rep = SM.diff(SM.collect(old)[0], SM.collect(new)[0])
    assert rep["added"] == [], rep
    assert rep["changed"] == [], rep


def test_a_GROWING_count_is_worse_not_undeclared(tmp_path):
    """The level lives in the metric TAIL so `DIRECTIONS` can read it.

    `warning_count`/`error_count` are two of the tails #1080 declares `lower`.
    Had the id been the tail (`...__warning_count__rsz_0104`, or ORFS's
    `count:RSZ-0104`), every diagnostic delta would have come back
    `undeclared` and the differ could never say a run got worse.
    """
    old = _emit(tmp_path, "v1.0.0_pdkX", _PREV_LOG, "old")
    new = _emit(tmp_path, "v1.1.0_pdkX",
                _PREV_LOG + "[WARNING RSZ-0104] and again.\n", "new")
    rep = SM.diff(SM.collect(old)[0], SM.collect(new)[0])
    worse = [c for c in rep["changed"] if c["verdict"] == "worse"]
    assert [c["key"] for c in worse] == [
        f"{_STEP}__tool__id__rsz_0104__warning_count"], rep
    assert worse[0]["old"] == 1 and worse[0]["new"] == 2, worse


def test_PAIRED_a_SHRINKING_count_is_better(tmp_path):
    """The other half of the same declaration — otherwise `lower` is
    indistinguishable from "always worse"."""
    old = _emit(tmp_path, "v1.0.0_pdkX",
                _PREV_LOG + "[WARNING RSZ-0104] and again.\n", "old")
    new = _emit(tmp_path, "v1.1.0_pdkX", _PREV_LOG, "new")
    rep = SM.diff(SM.collect(old)[0], SM.collect(new)[0])
    assert [c["verdict"] for c in rep["changed"]] == ["better"], rep


def test_a_DISAPPEARED_id_does_not_SURVIVE_a_re_emit(tmp_path):
    """`step_metrics.emit` merges, and a merge is wrong for a re-emit.

    Two runs into ONE project: the second run does not emit `GRT-0043`, so its
    key must be GONE. Merging would leave the old count sitting there and the
    metrics would report a diagnostic that this run did not produce — a lie
    with no symptom, in the file a later `diff` reads.
    """
    project = tmp_path / "proj"
    G.emit_metrics(G.census(_cell(tmp_path, "v1.0.0_pdkX", _NEW_ID_LOG)),
                   project)
    assert f"{_STEP}__tool__id__grt_0043__warning_count" in SM.collect(
        project)[0]
    G.emit_metrics(G.census(_cell(tmp_path, "v1.1.0_pdkX", _PREV_LOG)),
                   project)
    merged = SM.collect(project)[0]
    assert f"{_STEP}__tool__id__grt_0043__warning_count" not in merged, merged
    assert merged[f"{_STEP}__tool__id__rsz_0104__warning_count"] == 1


def test_PAIRED_a_re_emit_leaves_ANOTHER_programs_metrics_alone(tmp_path):
    """Only OUR domain is cleared. The step file is shared — #1080's whole
    point is that several programs contribute to one step — so a re-emit that
    truncated the file would delete measurements this program never made."""
    project = tmp_path / "proj"
    SM.emit(project, _STEP, {"instance_area": 4795.85}, domain="design")
    G.emit_metrics(G.census(_cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)),
                   project)
    G.emit_metrics(G.census(_cell(tmp_path, "v1.1.0_pdkX", _SAME_LOG)),
                   project)
    merged = SM.collect(project)[0]
    assert merged[f"{_STEP}__design__instance_area"] == 4795.85, merged


def test_two_ids_may_NOT_collapse_into_one_metric_key(tmp_path):
    """A collision is REFUSED, never silently summed.

    The id regex makes this unreachable today (one hyphen, no other
    non-alphanumerics, so lowercase-and-collapse is injective). It is asserted
    anyway because the regex is deliberately open-ended — `[A-Z][A-Z0-9]{1,7}`
    exists so a seventeenth tool is captured — and a widening that introduced a
    collision would otherwise understate a count with no visible symptom.
    """
    slot = {"ids": {"WARNING": {"AB-0012": 3, "AB.0012": 4}}, "logs": ["x.log"]}
    with pytest.raises(ValueError, match="refusing to merge"):
        G.metrics_for_step("s", slot)
    ok = G.metrics_for_step("s", {"ids": {"WARNING": {"AB-0012": 3}},
                                  "logs": ["x.log"]})
    assert ok["s__tool__id__ab_0012__warning_count"] == 3, ok


def test_a_failed_emit_is_a_FAILURE_not_a_quiet_zero(tmp_path):
    """Asked to publish, could not, must not exit 0.

    An "empty result is not a zero" case at the metric layer: a run that was
    told to emit, failed, and still returned success leaves the next comparison
    reading a file that silently is not there.
    """
    cell = _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("i am a file")
    p = subprocess.run(
        [sys.executable, str(GATE), str(cell), "--census-only",
         "--emit-metrics", str(blocked)],
        capture_output=True, text=True, timeout=55)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "could not emit per-step metrics" in p.stdout + p.stderr
    ok = subprocess.run(
        [sys.executable, str(GATE), str(cell), "--census-only",
         "--emit-metrics", str(tmp_path / "fine")],
        capture_output=True, text=True, timeout=55)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "emitted 8 per-step metric(s)" in ok.stdout, ok.stdout


def test_NO_BASELINE_still_emits_the_metric_and_still_exits_2(tmp_path):
    """The two verdicts are independent, and conflating them costs both ways.

    NO_BASELINE means the COMPARISON could not run — it does not mean nothing
    was measured, and publishing this run's counts is precisely what gives the
    next run a baseline. So the metric IS written. And the rc stays 2: a
    recorded baseline is still not a clean run.
    """
    cell = _cell(tmp_path, "v1.0.0_pdkX", _PREV_LOG)
    project = tmp_path / "proj"
    p = subprocess.run(
        [sys.executable, str(GATE), str(cell), "--acceptance",
         str(_acc(tmp_path / "a.json", [])), "--today", TODAY.isoformat(),
         "--emit-metrics", str(project)],
        capture_output=True, text=True, timeout=55)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "NO_BASELINE" in p.stdout
    merged, prov = SM.collect(project)
    assert prov["step_count"] == 1, prov
    assert merged[f"{_STEP}__tool__id__rsz_0104__warning_count"] == 1


# --- the denial count: computed since #1241, DROPPED until #1081 -----------
def test_a_DENIED_id_reaches_the_census_the_report_AND_the_metric(tmp_path):
    """`scan_log` counted denials and `census` threw the number away.

    The comment above `scan_log` promises "DENIALS ARE COUNTED, NEVER SILENTLY
    DROPPED", and that was true of the extractor and false of everything
    downstream: no report and no metric carried it, so "this run emitted
    nothing" and "this extractor discarded what it read" read identically —
    the exact confusion the unkeyed disclosure exists to prevent.
    """
    body = "no [WARNING RSZ-0104] warnings were emitted\n" \
           "[WARNING PSM-0038] Vsrc file not specified.\n"
    _cell(tmp_path, "v1.0.0_pdkX", body)
    cur = _cell(tmp_path, "v1.1.0_pdkX", body)
    cen = G.census(cur)
    assert cen["steps"][_STEP.replace("_", "/", 1)]["denied_count"] == 1, cen
    assert G.total_denied(cen) == 1

    rc, report = G.compare(cur, tmp_path / "v1.0.0_pdkX",
                           tmp_path / "missing.json", TODAY)
    assert rc == 0, report
    assert report["denied_not_counted"]["current"] == 1, report

    project = tmp_path / "proj"
    G.emit_metrics(cen, project)
    assert SM.collect(project)[0][
        f"{_STEP}__tool__denied__diagnostic_count"] == 1

    out = _run(cur, _acc(tmp_path / "a.json", []))[1]
    assert "read as DENIALS" in out, out


def test_PAIRED_an_EMITTED_id_is_not_counted_as_a_denial(tmp_path):
    """Otherwise the disclosure above is satisfied by counting everything."""
    cell = _cell(tmp_path, "v1.0.0_pdkX",
                 "[WARNING RSZ-0104] no clock found for register bank\n")
    cen = G.census(cell)
    assert G.total_denied(cen) == 0, cen
    project = tmp_path / "proj"
    G.emit_metrics(cen, project)
    merged = SM.collect(project)[0]
    assert merged[f"{_STEP}__tool__denied__diagnostic_count"] == 0
    assert merged[f"{_STEP}__tool__id__rsz_0104__warning_count"] == 1
