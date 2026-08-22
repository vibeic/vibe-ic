"""An axis proves from a metric somebody actually emits.

WHY
===
MEASURED, and recorded in the feasibility module's own source: across all six
STA artefacts of a real sign-off run both `timing.setup.wns_ns` and
`timing.hold.wns_ns` were NOT_MEASURED on every view, because the two
multi-corner emitters call `report_worst_slack` and `report_tns` and never call
`report_wns`. The hold axis was STRUCTURALLY UNPROVABLE — no run could produce
the evidence it proved from, on any design, ever — and each run appeared to
blame its own evidence rather than the wiring.

WHY EMPIRICAL, ASSERTED AS A TEST
=================================
The first version cross-referenced metric-name LITERALS in producer source. It
declared the whole `drv` axis unprovable and named four keys as unproduced. That
was FALSE and false in the BLOCKING direction: those keys appear under `"metric":`
in real records, because producers build names by format —
`"timing.%s.%s_ns" % (check, kind)` — so no literal scan can see them.
`test_a_format_built_metric_name_is_still_a_producer` pins that, because it is
the failure that would make this gate stop a working flow.

chip-AGNOSTIC: metric-name vocabulary and record shape.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "every_required_metric_key_has_a_producer.py"
_REPO = _PROGRAMS.parents[3]

_spec = importlib.util.spec_from_file_location("erkhap", _TOOL)
erkhap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(erkhap)



def _count_in(text: str, phrase: str) -> bool:
    """`phrase` (which begins with a count) appears with NO digit before it.

    MEASURED: `assert "1 inexpressible" in out` is satisfied by an output saying
    `21 inexpressible`, and `"0 key(s) observed"` by `10 key(s) observed`. A
    substring assertion on a count is not a pin — every one of these tests would
    have passed against a tenfold-wrong number. Taken from the census lane's
    "a substring assertion on a count is not a pin — parse the number".
    """
    return re.search(r"(?<!\d)" + re.escape(phrase), text) is not None


def test_the_count_anchor_actually_fires():
    """PROVE THE PIN FIRES. `_count_in` exists because a substring assertion on a
    count is not a pin — `"1 inexpressible" in out` is satisfied by an output
    saying `21 inexpressible`. A helper that silently never rejects anything would
    reinstate exactly the defect it was added to remove, and nothing else in this
    file would notice, because every other use of it asserts the TRUE case.

    So: the true case passes, and a preceding digit is refused.
    """
    assert _count_in("examined 1 thing", "1 thing")
    assert not _count_in("examined 21 thing", "1 thing"), (
        "the anchor did not fire: a tenfold-wrong count still satisfies the pin")
    assert not _count_in("examined 10 thing", "0 thing")
    assert _count_in("a, 0 thing", "0 thing")

def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


def _axis_keys():
    axes = erkhap.axis_table(_PROGRAMS)
    return axes, {p.metric for ax in axes for g in ax.groups for p in g}


def _corpus(tmp_path, keys):
    """A tree whose records emit exactly `keys`, plus the programs the tool reads."""
    root = tmp_path
    (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic").mkdir(parents=True)
    (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs").symlink_to(
        _PROGRAMS, target_is_directory=True)
    recs = root / "records"
    recs.mkdir()
    (recs / "records_flat.json").write_text(json.dumps(
        [{"metric": k, "status": "MEASURED", "value": 0} for k in sorted(keys)]))
    return root


# ------------------------------------------------------------ red control

def test_an_axis_with_no_producible_group_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: reintroduce the measured defect — drop every key
    of one axis, so no group of it can be proved by anything emitted."""
    axes, keys = _axis_keys()
    hold = next(a for a in axes if a.name == "hold")
    hold_keys = {p.metric for g in hold.groups for p in g}
    root = _corpus(tmp_path, keys - hold_keys)
    rc, out = _run(root)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "'hold'" in out
    assert "IS NOT PROVEN BY ANY RUN IN THIS CORPUS" in out


def test_the_same_corpus_with_the_axis_restored_passes(tmp_path):
    """BIDIRECTIONAL: put the axis's keys back and it goes green."""
    _axes, keys = _axis_keys()
    rc, out = _run(_corpus(tmp_path, keys))
    assert rc == 0, out


def test_one_group_is_enough(tmp_path):
    """The table is an OR of ANDs: one fully-emitted group proves the axis, and
    the other groups' keys are then DISCLOSED, not refused."""
    axes, keys = _axis_keys()
    hold = next(a for a in axes if a.name == "hold")
    first = {p.metric for p in hold.groups[0]}
    others = {p.metric for g in hold.groups[1:] for p in g} - first
    root = _corpus(tmp_path, keys - others)
    rc, out = _run(root)
    assert rc == 0, out
    assert "dead proof path" in out
    assert "DISCLOSED" in out


def test_a_partially_emitted_group_does_not_prove_an_axis(tmp_path):
    """A group is an AND. Emitting some of its keys is not emitting the group."""
    axes, keys = _axis_keys()
    drv = next(a for a in axes if a.name == "drv")
    multi = next(g for g in drv.groups if len(g) > 1)
    drv_keys = {p.metric for g in drv.groups for p in g}
    keep = {multi[0].metric}                      # only ONE key of the AND group
    root = _corpus(tmp_path, (keys - drv_keys) | keep)
    rc, out = _run(root)
    assert rc == 1, out
    assert "'drv'" in out


# --------------------------------- the false positive that must never return

def test_a_format_built_metric_name_is_still_a_producer():
    """The producers build names by format, so a literal scan cannot see them.
    Pinned because the static version blocked a WORKING flow on this."""
    src = (_PROGRAMS / "_ppa" / "timing.py").read_text(encoding="utf-8")
    assert '"timing.%s.%s_ns" % (check, kind)' in src, (
        "the format-built producer this gate must not mis-read has moved")
    _axes, keys = _axis_keys()
    assert "timing.setup.wns_ns" in keys
    # The real tree must show a format-built name as EMITTED...
    prod = erkhap.producers(_REPO, keys)
    assert prod.get("timing.setup.wns_ns"), (
        "timing.setup.wns_ns reads as unproduced — the static false positive "
        "that could not see format-built names has returned")
    # ...and must NOT credit timing.drv.violations, which appears ONLY in
    # NOT_MEASURED records and in the consumer's own report of what it failed to
    # find. An earlier version of this test asserted the opposite, encoding a
    # belief this lane later disproved: 0 MEASURED rows against 370 NOT_MEASURED.
    assert not prod.get("timing.drv.violations"), (
        "a key carried only by NOT_MEASURED records is being credited again")


def test_a_not_measured_canonical_record_is_not_evidence():
    """The sibling gate `measurement_only_artefact_is_not_a_verdict_source`
    refuses a NOT_MEASURED record as verdict evidence. This one used to accept
    it, so two gates in one family gave the same records opposite treatment and
    the flattering one won."""
    import json, tempfile, pathlib as _pl
    with tempfile.TemporaryDirectory() as d:
        root = _pl.Path(d)
        (root / "r.json").write_text(json.dumps([
            {"schema": "vibeic.ppa.metric.v1", "metric": "timing.setup.wns_ns",
             "status": "NOT_MEASURED"}]))
        prod = erkhap.producers(root, {"timing.setup.wns_ns"})
    assert not prod.get("timing.setup.wns_ns"), (
        "a canonical record with status NOT_MEASURED was counted as evidence")


# -------------------------------------------------------------- verdicts

def test_no_records_is_not_checked(tmp_path):
    root = _corpus(tmp_path, set())
    (root / "records" / "records_flat.json").write_text("[]")
    rc, out = _run(root)
    assert rc == 2, out
    assert "no axis was judged" in out


def test_an_empty_corpus_reports_no_finding_at_all(tmp_path):
    """MEASURED DEFECT IN THIS GATE, now pinned.

    Over a tree with no metric records EVERY axis is trivially unprovable. The
    first version computed the findings before checking the corpus size, so it
    printed nine "STRUCTURALLY UNPROVABLE ... forever" lines to stdout and THEN
    returned NOT CHECKED. The exit code was right and the output was an unearned
    claim — absence rendered as a finding, which is the error this whole family
    of rules exists to refuse, and a caller reading stdout would have acted on it.

    The empty-corpus branch must therefore return BEFORE any finding is printed.
    """
    root = _corpus(tmp_path, set())
    (root / "records" / "records_flat.json").write_text("[]")
    rc, out = _run(root)
    assert rc == 2, out
    assert "STRUCTURALLY UNPROVABLE" not in out, (
        "an empty corpus produced findings:\n" + out)
    assert _count_in(out, "0 key(s) observed")


def test_unparseable_json_is_skipped_not_fatal(tmp_path):
    _axes, keys = _axis_keys()
    root = _corpus(tmp_path, keys)
    (root / "records" / "broken.json").write_text("{not json")
    rc, out = _run(root)
    assert rc == 0, out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_the_repository_has_two_axes_with_no_measured_evidence():
    """rc=1 here is a TRUE POSITIVE and is asserted as one.

    MEASURED across the published records: `equivalence.verdict` and
    `reliability.em.*` have ZERO rows with status MEASURED against 370
    NOT_MEASURED, while `physical.drc.violations` has 227 MEASURED and
    `timing.setup.wns_ns` has 485. Two axes are carried by records that never
    measured anything.

    This was found only by composing with another lane whose source-level gate
    reached a related verdict; before that, this gate credited the CONSUMER's own
    report — which lists every proof name it failed to find — as evidence a
    producer had emitted it.
    """
    rc, out = _run(_REPO)
    assert rc == 1, out
    assert "'em'" in out and "'equivalence'" in out
    assert "IS NOT PROVEN BY ANY RUN IN THIS CORPUS" in out
