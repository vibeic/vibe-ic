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
