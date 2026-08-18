#!/usr/bin/env python3
"""The fleet shard layer must refuse a partial answer, and must not let the
shard layout leak into the report.

Every test here is aimed at one of the two ways a sharded arm silently stops
being a landing gate:

  1. A host that did not answer is quietly dropped, so the denominator shrinks
     and "green" now means "green on the hosts that felt like reporting".
  2. A case lands under the wrong file, or the report's order depends on which
     host was fastest, so a red is unattributable and two rounds cannot be
     differenced.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import pytest_fleet_shard as F  # noqa: E402


# ───────────────────────────── balancing ──────────────────────────────────────

def test_balance_without_costs_spreads_neighbours_across_hosts():
    """The selector emits SORTED paths, so consecutive files are directory
    neighbours. Handing one host a contiguous block hands it a whole cluster."""
    sel = [f"programs/tests/test_{i:03d}.py" for i in range(12)]
    bins = F.balance(sel, 4, {})
    assert [len(b) for b in bins] == [3, 3, 3, 3]
    assert sorted(p for b in bins for p in b) == sorted(sel)
    # No bin may be a contiguous run of the input.
    for b in bins:
        assert sel.index(b[1]) - sel.index(b[0]) == 4


def test_balance_with_costs_is_longest_processing_time_first():
    """One 140 s file and forty 1 s files must not land on the same host."""
    sel = ["heavy_a.py", "heavy_b.py"] + [f"cheap_{i}.py" for i in range(40)]
    cost = {"heavy_a.py": 140.0, "heavy_b.py": 130.0}
    cost.update({f"cheap_{i}.py": 1.0 for i in range(40)})
    bins = F.balance(sel, 2, cost)
    loads = [sum(cost[p] for p in b) for b in bins]
    assert max(loads) - min(loads) <= 10.0, loads
    heavy_bins = {i for i, b in enumerate(bins)
                  if "heavy_a.py" in b or "heavy_b.py" in b}
    assert len(heavy_bins) == 2, "both heavy files landed on one host"


def test_balance_is_deterministic():
    sel = [f"f{i}.py" for i in range(30)]
    cost = {p: float(len(p)) for p in sel}
    assert F.balance(sel, 3, cost) == F.balance(sel, 3, cost)


def test_balance_loses_no_file():
    sel = [f"f{i}.py" for i in range(37)]
    for cost in ({}, {p: float(i) for i, p in enumerate(sel)}):
        bins = F.balance(sel, 5, cost)
        assert sorted(p for b in bins for p in b) == sorted(sel)


# ────────────────────────── shard verification ────────────────────────────────

def _shard(tmp_path, files, log_text, junit_text):
    log = tmp_path / "shard.log"
    junit = tmp_path / "shard.xml"
    log.write_text(log_text, encoding="utf-8")
    if junit_text is not None:
        junit.write_text(junit_text, encoding="utf-8")
    return F.Shard(host="h", tree="/t", files=list(files), index=0,
                   log_path=log, junit_path=junit)


def _junit(files):
    root = ET.Element("testsuites", {"name": "pytest tests"})
    for path in files:
        suite = ET.SubElement(root, "testsuite", {"name": path, "tests": "1"})
        ET.SubElement(suite, "testcase",
                      {"classname": path.replace("/", ".").rstrip(".py"),
                       "name": "test_thing", "file": path, "time": "0.5"})
        proc = ET.SubElement(root, "testsuite",
                             {"name": f"{path}::process_exit", "tests": "1"})
        case = ET.SubElement(proc, "testcase",
                             {"classname": "pytest_per_file_process",
                              "name": f"{path}::process_exit", "file": path})
        props = ET.SubElement(case, "properties")
        ET.SubElement(props, "property",
                      {"name": "process_rc", "value": "0"})
    return ET.tostring(root, encoding="unicode")


_GOOD_LOG = ("FALLBACK_PROGRESS  completed=2/2\n"
             "[PASS] suite_write_guard: this pytest session wrote nothing.\n"
             "[PASS] suite_write_guard: this pytest session wrote nothing.\n"
             "=== pytest junit summary\n"
             "  asked      2\n"
             "  recorded   2\n"
             "FLEET_SHARD_END rc=0\n")


def test_a_shard_that_answered_is_ingested(tmp_path):
    files = ["a.py", "b.py"]
    s = _shard(tmp_path, files, _GOOD_LOG, _junit(files))
    F.verify_and_ingest(s)
    assert not s.refused, s.refusal
    assert set(s.suites_by_file) == set(files)
    assert set(s.process_suites) == set(files)


@pytest.mark.parametrize("log,junit,why", [
    (_GOOD_LOG.replace("FLEET_SHARD_END rc=0\n", ""), _junit(["a.py", "b.py"]),
     "end sentinel"),
    (_GOOD_LOG.replace("=== pytest junit summary\n", ""),
     _junit(["a.py", "b.py"]), "no summary"),
    (_GOOD_LOG.replace("  asked      2", "  asked      1"),
     _junit(["a.py", "b.py"]), "denominator"),
    (_GOOD_LOG, "<testsuites><this is not xml", "did not parse"),
    (_GOOD_LOG, _junit(["a.py", "zzz_not_mine.py"]), "not in this shard"),
    (_GOOD_LOG.replace("rc=0", "rc=90"), _junit(["a.py", "b.py"]),
     "tree was not usable"),
    (_GOOD_LOG.replace("rc=0", "rc=3"), _junit(["a.py", "b.py"]),
     "could not be asked"),
    (_GOOD_LOG.replace(
        "[PASS] suite_write_guard: this pytest session wrote nothing.\n", "",
        1), _junit(["a.py", "b.py"]), "a session ran without the write guard"),
])
def test_every_way_a_shard_can_fail_to_report_is_a_refusal(
        tmp_path, log, junit, why):
    """A CHECK THAT CANNOT FAIL IS WORSE THAN NO CHECK. Each of these is a way
    a host can hand back something that LOOKS like an answer."""
    s = _shard(tmp_path, ["a.py", "b.py"], log, junit)
    F.verify_and_ingest(s)
    assert s.refused, f"a shard with {why} was believed"


def test_a_missing_report_is_a_refusal_not_an_empty_one(tmp_path):
    s = _shard(tmp_path, ["a.py"], _GOOD_LOG.replace("      2", "      1"),
               None)
    s.refusal = "the shard report was not retrievable"
    F.verify_and_ingest(s)
    assert s.refused


# ─────────────────────────────── merge ────────────────────────────────────────

def _ingested(tmp_path, name, files):
    d = tmp_path / name
    d.mkdir()
    log = ("[PASS] suite_write_guard: wrote nothing.\n" * len(files)
           + f"=== pytest junit summary\n  asked      {len(files)}\n"
           + "FLEET_SHARD_END rc=0\n")
    s = _shard(d, files, log, _junit(files))
    F.verify_and_ingest(s)
    assert not s.refused, s.refusal
    return s


def test_merge_is_in_global_selection_order_not_shard_order(tmp_path):
    """Which host ran a file must leave NO trace in the report, or two rounds
    of the same selection cannot be differenced."""
    selection = [f"f{i}.py" for i in range(8)]
    s0 = _ingested(tmp_path, "s0", selection[0::2])
    s1 = _ingested(tmp_path, "s1", selection[1::2])
    out = tmp_path / "merged.xml"
    F.merge_global(selection, [s0, s1], out)
    root = ET.parse(out).getroot()
    names = [s.get("name") for s in root
             if not (s.get("name") or "").endswith("::process_exit")]
    assert names == selection
    # Reversing the shard argument order must not move a single element.
    other = tmp_path / "merged2.xml"
    F.merge_global(selection, [s1, s0], other)
    assert out.read_bytes() == other.read_bytes()


def test_merge_preserves_file_attribution(tmp_path):
    selection = [f"f{i}.py" for i in range(6)]
    s0 = _ingested(tmp_path, "s0", selection[:3])
    s1 = _ingested(tmp_path, "s1", selection[3:])
    out = tmp_path / "merged.xml"
    F.merge_global(selection, [s0, s1], out)
    root = ET.parse(out).getroot()
    for suite in root:
        for case in suite.iter("testcase"):
            assert case.get("file") == suite.get("name").replace(
                "::process_exit", "")


def test_a_refused_shard_contributes_nothing_to_the_report(tmp_path):
    selection = [f"f{i}.py" for i in range(6)]
    good = _ingested(tmp_path, "s0", selection[:3])
    bad = _ingested(tmp_path, "s1", selection[3:])
    bad.refusal = "the host was lost"
    out = tmp_path / "merged.xml"
    F.merge_global(selection, [good, bad], out)
    root = ET.parse(out).getroot()
    names = {s.get("name") for s in root}
    assert names == {p for p in selection[:3]} | {
        f"{p}::process_exit" for p in selection[:3]}


# ─────────────────────────── cost map round trip ──────────────────────────────

def test_costmap_from_junit_sums_case_time_per_file(tmp_path):
    j = tmp_path / "j.xml"
    j.write_text(_junit(["a.py", "b.py"]), encoding="utf-8")
    cost = F.costmap_from_junit(j)
    assert cost == {"a.py": 0.5, "b.py": 0.5}


def test_costmap_ignores_the_synthetic_process_suites(tmp_path):
    j = tmp_path / "j.xml"
    j.write_text(_junit(["a.py"]), encoding="utf-8")
    assert list(F.costmap_from_junit(j)) == ["a.py"]


def test_an_unusable_costmap_degrades_the_schedule_and_nothing_else(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert F.load_cost_map(bad) == {}
