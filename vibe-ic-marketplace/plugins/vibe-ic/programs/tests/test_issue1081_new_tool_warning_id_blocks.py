"""A tool diagnostic ID that was not there last time must BLOCK. vibe-ic#1081.

The gate is BLOCKING, so these tests carry the burden flow-change-acceptance
puts on that claim:

* §1 PAIRED negative control. `test_a_new_id_is_reported_and_blocks` is the
  arm that FIRES; `test_no_new_id_is_clean` is its `*_clears` sibling and is
  meaningless alone — on a gate that did not exist, a "clears" assertion passes
  vacuously because nothing can fire it. Neither is presented as a standalone
  control.
* §2 corpus sweep. The published corpus was swept before this gate was written,
  and the sweep is what rejected the naive design: the runs under one cell
  differ BY PDK, so "compare against the directory next to it" produced 3, 12
  and 3 "new" IDs across three consecutive pairs — every one of them a
  legitimate consequence of changing PDK, i.e. a bug in the gate. That is why
  a predecessor is only ever NAMED or COMMITTED, never inferred.
* §4 real-artefact backing. `test_the_real_corpus_pair_reports_the_new_id`
  drives the gate from checked-in run trees via `_hostpaths.require_repo`, so
  this suite is not exclusively fixtures authored beside the code it guards.
* §6 degrade loudly. `test_absent_predecessor_is_not_checked_not_pass` pins
  that "I could not compare" never shares an exit code with "nothing was new".
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hostpaths import require_repo  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "tool_warning_id_regression_check.py"

RC_CLEAN, RC_BLOCKING, RC_NOT_CHECKED = 0, 1, 2


def run_gate(*args):
    r = subprocess.run([sys.executable, str(PROG), *[str(a) for a in args]],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def _run_dir(tmp_path, name, diagnostics):
    """A synthesized run root. No design, PDK, vendor or tool name appears —
    the prefixes below are invented and the gate never enumerates them."""
    d = tmp_path / name
    (d / "reports").mkdir(parents=True)
    (d / "reports" / "step.rpt").write_text(
        "\n".join(f"[WARNING {m}] synthesized diagnostic text" for m in diagnostics) + "\n")
    return d


# --- §1 the PAIRED negative control ----------------------------------------

def test_a_new_id_is_reported_and_blocks(tmp_path):
    """THE FIRING ARM. Without this, the `clears` test below proves nothing."""
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001", "BBB-0002"])
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, out
    assert "BBB-0002" in out
    assert "NEW" in out


def test_no_new_id_is_clean(tmp_path):
    """The `clears` sibling — only meaningful paired with the firing arm."""
    prev = _run_dir(tmp_path, "prev", ["AAA-0001", "BBB-0002"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN, out


def test_an_id_that_disappeared_does_not_block(tmp_path):
    """A warning going away is not a regression. Blocking on it would make the
    gate fire on an improvement, which is criterion §2's false positive."""
    prev = _run_dir(tmp_path, "prev", ["AAA-0001", "BBB-0002", "CCC-0003"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    rc, _ = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN


# --- the acceptance list, which must itself be checked ---------------------

def _accept(run, entries):
    (run / "tool_warning_id_acceptance.json").write_text(json.dumps({"accepted": entries}))


def test_a_live_acceptance_covers_a_new_id(tmp_path):
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001", "BBB-0002"])
    _accept(cur, [{"id": "BBB-0002", "until": "2026-12-31", "why": "adjudicated: benign"}])
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN, out
    assert "ACCEPTED" in out


def test_an_expired_acceptance_blocks_even_when_it_did_not_fire(tmp_path):
    """An expired entry fails whether or not it covered anything. An acceptance
    is a promise to revisit; kept past its reason it is a blind spot the exact
    size of the ID it names, and the run where it silently starts covering a
    real regression is the run nobody is looking at."""
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])          # nothing new at all
    _accept(cur, [{"id": "ZZZ-9999", "until": "2026-01-01", "why": "stale"}])
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, out
    assert "EXPIRED" in out


@pytest.mark.parametrize("entry,why", [
    ({"id": "BBB-0002", "until": "not-a-date", "why": "x"}, "non-ISO date"),
    ({"id": "BBB-0002", "until": "2026-12-31"}, "no reason"),
    ({"id": "BBB-0002", "until": "2026-12-31", "why": "   "}, "blank reason"),
    ({"until": "2026-12-31", "why": "x"}, "no id"),
])
def test_a_malformed_acceptance_is_refused_not_ignored(tmp_path, entry, why):
    """Silently skipping a mis-typed acceptance yields an entry that covers
    nothing while reading as though it covers something."""
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001", "BBB-0002"])
    _accept(cur, [entry])
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, f"{why}: {out}"
    assert "REFUSED" in out, why


# --- §6 degrade loudly ------------------------------------------------------

def test_absent_predecessor_is_not_checked_not_pass(tmp_path):
    """rc 2, and distinct from rc 0. "I could not compare" must never share an
    exit code with "there was nothing new"."""
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    rc, out = run_gate(cur, "--today", "2026-08-12")
    assert rc == RC_NOT_CHECKED, out
    assert "NOT_CHECKED" in out
    assert "not a pass" in out.lower()


def test_a_defect_is_not_masked_by_an_unmeasurable_comparison(tmp_path):
    """An expired acceptance is still a defect when no predecessor exists. If
    rc 2 won here, deleting the baseline would launder every stale entry."""
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _accept(cur, [{"id": "ZZZ-9999", "until": "2026-01-01", "why": "stale"}])
    rc, out = run_gate(cur, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, out


def test_a_nested_run_is_not_attributed_to_its_parent(tmp_path):
    """Measured while scoping this gate: rglob from a cell root made the parent
    read as the UNION of every run beneath it, so the parent appeared to
    produce IDs no single run of it ever did."""
    from importlib import util as _u
    spec = _u.spec_from_file_location("twirc", PROG)
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    parent = _run_dir(tmp_path, "parent", ["AAA-0001"])
    child = _run_dir(parent, "child_run", ["BBB-0002"])
    assert set(mod.collect_ids(parent)) == {"AAA-0001", "BBB-0002"}
    assert set(mod.collect_ids(parent, exclude=[child])) == {"AAA-0001"}


# --- §4 real-artefact backing ----------------------------------------------

def test_the_real_corpus_pair_reports_the_new_id():
    """Driven by checked-in run trees, not by fixtures authored beside this code.

    MEASURED at v1.10.32: these two runs of the same cell are like-for-like —
    the same four report files carry diagnostics in both — and the later one
    gained `DRT-0120` in `reports/phase3/drc_router.rpt`. That is a real change
    in tool behaviour that nothing in the flow can currently see, which is the
    whole of #1081.
    """
    root = require_repo("benchmark-data/ic/sha256")
    prev = root / "clean_run_v1422_20260715"
    cur = root / "clean_run_v1427_20260715"
    for p in (prev, cur):
        if not p.is_dir():
            pytest.skip(f"published run absent from this checkout: {p}")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, out
    assert "DRT-0120" in out, out


def test_the_real_corpus_pair_is_clean_in_the_other_direction():
    """The same two runs compared the other way round have no new ID — so the
    firing above is a property of the DATA, not of the gate always firing."""
    root = require_repo("benchmark-data/ic/sha256")
    prev = root / "clean_run_v1427_20260715"
    cur = root / "clean_run_v1422_20260715"
    for p in (prev, cur):
        if not p.is_dir():
            pytest.skip(f"published run absent from this checkout: {p}")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN, out


# ===========================================================================
# §N — SCANNER COVERAGE PORTED FROM vibe-ic#1092
#
# #1092 built the same gate on an inferred predecessor, which is why it is being
# closed in favour of this one. But its SCANNER saw three shapes this one did
# not, and each is paired here: the red case with the coverage, and the green
# twin proving the coverage is not "match everything".
# ===========================================================================
def _rpt(run, rel, text):
    p = run / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_family_B_standalone_OpenSTA_numbered_form_is_compared(tmp_path):
    """`Warning 168:` is `STA-0168`. Unbracketed, and previously invisible.

    Two of the ids the corpus actually carries in `aging_sta.rpt`/`power.rpt`
    are this shape. Before the port they were absent from every comparison while
    the gate still reported a clean one.
    """
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _rpt(cur, "reports/phase3/aging_sta.rpt",
         "Warning 168: constraint.sdc line 3, something was not allowed.\n")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, out
    assert "STA-0168" in out, out


def test_PAIRED_family_B_present_in_BOTH_runs_is_clean(tmp_path):
    """The twin. Coverage that cannot say "unchanged" is not coverage."""
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    for r in (prev, cur):
        _rpt(r, "reports/phase3/aging_sta.rpt", "Warning 168: same in both.\n")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN, out


def test_PAIRED_family_B_needs_line_start_not_prose(tmp_path):
    """`... see Warning 168: below` inside prose is NOT a diagnostic.

    The anchor is the whole reason this regex is safe to widen. Without this
    twin, "compare family B" would be satisfied by matching the substring
    anywhere and the gate would invent ids out of sentences.
    """
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _rpt(cur, "reports/notes.rpt",
         "The tool may emit Warning 168: in some configurations.\n")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN, out
    assert "STA-0168" not in out, out


def test_ids_inside_json_tool_output_are_compared(tmp_path):
    """The runner stores console output in JSON fields; 3 corpus files do this.

    `dynamic_ir.json` carries `[WARNING ODB-0220]` verbatim. That is tool
    output, not a report about tool output, and `.json` was not scanned.
    """
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _rpt(cur, "reports/phase3/dynamic_ir.json",
         json.dumps({"tool_stdout": "[WARNING BBB-0002] rail check\n"}) + "\n")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, out
    assert "BBB-0002" in out, out


def test_the_emitted_baseline_stores_ids_BARE_so_the_regex_cannot_harvest_them(
        tmp_path):
    """WHAT ACTUALLY CLOSES THE LOOP FOR THE BASELINE — measured, not assumed.

    An earlier version of this test asserted the schema skip was what stopped
    `--emit-baseline`'s output being read back, and it SURVIVED a mutant that
    deleted the skip. The reason is worth pinning instead of hiding: the baseline
    stores ids BARE (`"ids": ["ZZZ-0009"]`), and `_DIAG` requires the bracketed
    `[WARNING ZZZ-0009]` form, so the regex cannot harvest them whatever the skip
    does. The serialization format is the real defence.

    That is exactly why the format must not drift. If anyone ever stores the
    console LINE beside the id — the obvious next feature — the loop opens, and
    the schema skip below is what will hold. This test pins the format; the next
    one proves the skip works when the format is not enough.
    """
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _rpt(cur, "reports/phase3/x.rpt", "[WARNING ZZZ-0009] one real new id\n")
    rc, _ = run_gate(cur, "--emit-baseline")
    assert rc == RC_CLEAN, "emitting a baseline should not itself block"
    text = (cur / "tool_warning_ids.json").read_text()
    assert "ZZZ-0009" in text, text
    assert "[WARNING ZZZ-0009]" not in text, (
        "the emitted baseline now carries a BRACKETED diagnostic line. The loop "
        "this gate must not have is open unless the schema skip catches it — see "
        "the next test, and do not relax it.")


def test_an_own_artefact_carrying_a_bracketed_line_is_still_not_harvested(
        tmp_path):
    """THE SKIP, proved on the case the format does not cover.

    A run artefact that carries this gate's SCHEMA and a bracketed diagnostic
    line — what the baseline becomes the day it stores console text — must not be
    scanned. Deleting the skip makes this red, which is what makes it a check.
    """
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _rpt(cur, "reports/phase3/prior_answer.json", json.dumps({
        "schema": "vibe-ic/tool-warning-ids/v1",
        "ids": ["WWW-0004"],
        "lines": ["[WARNING WWW-0004] quoted from the previous run's log"],
    }) + "\n")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN, (
        f"an id was harvested out of this gate's OWN previous answer: {out}")
    assert "WWW-0004" not in out, out


def test_PAIRED_an_acceptance_file_cannot_manufacture_the_id_it_excuses(tmp_path):
    """The acceptance file carries no schema and sits in the same run root.

    Its `why` is free text where a reviewer would paste the log line being
    excused. Reading that back would let an acceptance CREATE the id it exists
    to excuse — an exemption that is also its own evidence.
    """
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _accept(cur, [{"id": "QQQ-0007", "until": "2099-01-01",
                   "why": "seen as [WARNING QQQ-0007] in the log"}])
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_CLEAN, out
    assert "QQQ-0007" not in out, (
        f"an id was harvested out of the acceptance file's own text: {out}")


def test_a_five_digit_message_number_is_not_invisible(tmp_path):
    """The widened id regex. `[A-Z]{2,5}-\\d{3,4}` could not see this at all."""
    prev = _run_dir(tmp_path, "prev", ["AAA-0001"])
    cur = _run_dir(tmp_path, "cur", ["AAA-0001"])
    _rpt(cur, "reports/phase3/y.rpt", "[WARNING ABC-12345] numbered past 9999\n")
    rc, out = run_gate(cur, "--baseline-run", prev, "--today", "2026-08-12")
    assert rc == RC_BLOCKING, out
    assert "ABC-12345" in out, out
