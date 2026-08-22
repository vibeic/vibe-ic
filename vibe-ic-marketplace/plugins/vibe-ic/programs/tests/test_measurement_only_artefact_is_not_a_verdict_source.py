"""A measurement is not a verdict, and an unmeasured axis is not a zero.

WHY
===
MEASURED: a consumer resolved a reliability axis to the emitter's RAW
MEASUREMENT — 2431 segments, max segment current 1.951e-4 A, no limit and no
count anywhere in it — instead of to the sign-off checker that compares against
the limit from the process kit's technology file. With no count in the artefact
the ABSENCE of a count became indistinguishable from a count of ZERO, and the
axis reported a pass no comparison had produced.

The emitter said so itself, and this tree still carries the sentence at
`_ppa/backends/orfs.py:436` — asserted below, because if that self-declaration
is ever dropped this rule silently loses its subject.

chip-AGNOSTIC: metric-record vocabulary only.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "measurement_only_artefact_is_not_a_verdict_source.py"
_REPO = _PROGRAMS.parents[3]

_spec = importlib.util.spec_from_file_location("moainavs", _TOOL)
moainavs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(moainavs)

_KEY = "reliability.em.violations"
_NOTE = ("this is the router's own count of its own result; it is not a "
         "sign-off verdict and must not be used as the eligibility term")


def _tree(tmp_path, records):
    (tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic").mkdir(parents=True)
    (tmp_path / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
     / "programs").symlink_to(_PROGRAMS, target_is_directory=True)
    r = tmp_path / "records"
    r.mkdir()
    (r / "records.json").write_text(json.dumps(records, indent=2))
    return tmp_path


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


_GOOD = {"metric": _KEY, "state": "MEASURED", "value": 0,
         "outcomes": ["SATISFIED"]}


# ------------------------------------------------------------ red controls

def test_a_self_declared_non_verdict_satisfying_an_axis_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: the measured defect — the raw measurement, which
    says in its own words that it is not a verdict, carrying the verdict."""
    rec = dict(_GOOD, note=_NOTE)
    rc, out = _run(_tree(tmp_path, [rec]))
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "declares itself not a verdict" in out
    assert "absence of a count is not a count of zero" in out


def test_a_not_measured_record_satisfying_an_axis_goes_red(tmp_path):
    """"Nobody looked" counted as "looked and found none"."""
    rec = dict(_GOOD, state="NOT_MEASURED")
    rc, out = _run(_tree(tmp_path, [rec]))
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "NOT_MEASURED" in out
    assert "measured zero" in out


def test_a_nested_disclaimer_is_still_the_records_own_words(tmp_path):
    """MEASURED FALSE PASS: the check read only TOP-LEVEL fields, so a record
    carrying its disclaimer under `provenance` reported PASS. Emitters nest
    provenance routinely and a disclaimer one level down binds just as hard."""
    rec = dict(_GOOD, provenance={"note": _NOTE})
    rc, out = _run(_tree(tmp_path, [rec]))
    assert rc == 1, f"a nested disclaimer was not caught:\n{out}"
    assert "declares itself not a verdict" in out


def test_an_unrelated_nested_string_is_not_a_disclaimer(tmp_path):
    """BIDIRECTIONAL: nesting must not turn every record into a finding."""
    rec = dict(_GOOD, provenance={"note": "measured against the kit limit"})
    rc, out = _run(_tree(tmp_path, [rec]))
    assert rc == 0, out


def test_the_same_record_measured_and_unqualified_passes(tmp_path):
    """BIDIRECTIONAL: without the self-declaration and measured, it goes green."""
    rc, out = _run(_tree(tmp_path, [dict(_GOOD)]))
    assert rc == 0, out


# -------------------------------------- a proxy may exist, it may not decide

def test_a_self_declared_proxy_that_satisfies_nothing_is_not_a_finding(tmp_path):
    """The rule refuses a proxy CARRYING a verdict, not a proxy existing. A
    measurement is allowed to be published, read and reported."""
    proxy = {"metric": _KEY, "state": "MEASURED", "value": 3, "note": _NOTE}
    rc, out = _run(_tree(tmp_path, [proxy, dict(_GOOD)]))
    assert rc == 0, out


def test_a_non_axis_metric_is_out_of_scope(tmp_path):
    """`area.*` proxy records are numerous and legitimate; they prove no axis."""
    rec = {"metric": "area.proxy.cell_count", "state": "MEASURED",
           "outcomes": ["SATISFIED"], "note": _NOTE}
    rc, out = _run(_tree(tmp_path, [rec, dict(_GOOD)]))
    assert rc == 0, out


# ------------------------------------- the self-declaration must still exist

def test_the_emitters_own_disqualifying_sentence_is_still_in_the_tree():
    src = (_PROGRAMS / "_ppa" / "backends" / "orfs.py").read_text(encoding="utf-8")
    assert "it is not a sign-off verdict and must not be used" in src, (
        "the emitter's self-declaration has moved — this rule's subject is "
        "gone and it would pass over nothing")


def test_the_phrase_is_actually_matched():
    assert moainavs._self_declared_non_verdict({"note": _NOTE})
    assert moainavs._self_declared_non_verdict({"reason": "estimate only"})
    assert moainavs._self_declared_non_verdict({"note": "x is a proxy"})
    assert not moainavs._self_declared_non_verdict(
        {"note": "measured against the kit limit"})


def test_satisfied_is_read_from_several_spellings():
    assert moainavs._satisfies({"outcomes": ["SATISFIED"]})
    assert moainavs._satisfies({"verdict": "satisfied"})
    assert not moainavs._satisfies({"outcomes": ["VIOLATED"]})
    assert not moainavs._satisfies({})


# -------------------------------------------------------------- verdicts

def test_no_axis_record_is_not_checked(tmp_path):
    rc, out = _run(_tree(tmp_path, [{"metric": "area.proxy.cell_count"}]))
    assert rc == 2, out
    assert "absent corpus is not a clean one" in out


def test_unparseable_json_is_skipped_not_fatal(tmp_path):
    root = _tree(tmp_path, [dict(_GOOD)])
    (root / "records" / "broken.json").write_text("{not json")
    rc, out = _run(root)
    assert rc == 0, out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_REPO)
    assert rc == 0, out
