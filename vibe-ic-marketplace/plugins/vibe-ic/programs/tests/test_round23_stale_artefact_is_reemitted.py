"""A producer fix the runner does not re-emit reaches nobody.

MEASURED (round 23). The A1-A3 producers were invoked only on the gate's rc 2
— the artefact-MISSING path. With a stale artefact present the gate returned
rc 0, the step reported PASS, and the producer never ran, so a lane that had
just fixed the topology library simulated the OLD netlist (old comparator,
4 um keeper, 181 um bias, ci 6.949 um) and the run was indistinguishable from
a successful one from the outside.

The judgement is derived from what the ARTEFACT ITSELF says — each producer
stamps a digest of its own source into the provenance it writes. Not mtime (a
copy or a checkout resets it) and not a file name (one spelling defines a
blind population).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_one_shot_runner as r  # noqa: E402
import analog_a1_spec_emit as a1  # noqa: E402
import analog_a2_topology_emit as a2  # noqa: E402
import analog_a3_netlist_emit as a3  # noqa: E402


def _mk(tmp_path, step, fp):
    """A project carrying one provenance artefact claiming fingerprint `fp`."""
    fname = r._PRODUCER_STAMP[step][0]
    d = tmp_path / "phase3" / "analog" / "blk"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"_provenance": {"producer": "x"}}
    if fp is not None:
        doc["_provenance"]["producer_fingerprint"] = fp
    (d / fname).write_text(json.dumps(doc))
    return tmp_path


def _live(step):
    return r._live_producer_fingerprint(r._A1_A3_PRODUCERS[step]["program"])


def test_every_A1_A3_producer_is_stamped_none_left_over():
    """Round 23 fixed A2 and A3 and LISTED A1 as the remaining instance.
    A listed instance nobody closes is a defect with a note attached."""
    import analog_one_shot_runner as _r
    assert set(_r._A1_A3_PRODUCERS) == set(_r._PRODUCER_STAMP)


def test_both_producers_stamp_a_fingerprint_at_all():
    for mod in (a1, a2, a3):
        fp = mod.producer_fingerprint()
        assert fp and len(fp) == 16, (mod.__name__, fp)
    # and they are DIFFERENT files, so a shared constant would be a bug
    fps = {a1.producer_fingerprint(), a2.producer_fingerprint(),
           a3.producer_fingerprint()}
    assert len(fps) == 3, "different files must not share a fingerprint"


def test_a_matching_artefact_is_REUSED_and_the_decision_names_it():
    # THE CONTROL that keeps this from being "the cache is off": an artefact
    # this producer really did make must NOT be re-emitted, or every run pays
    # the producers again.
    for step in ("A1_spec_extract", "A2_topology_select", "A3_netlist_gen"):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = _mk(Path(td), step, _live(step))
            d = r.producer_reuse_decision(p, "blk", step)
            assert d["reuse"] is True, (step, d)
            assert "REUSED" in d["detail"]
            assert r._PRODUCER_STAMP[step][0] in d["detail"]


def test_a_stale_artefact_is_RE_EMITTED_and_the_decision_says_why():
    for step in ("A1_spec_extract", "A2_topology_select", "A3_netlist_gen"):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = _mk(Path(td), step, "0000stale0000000")
            d = r.producer_reuse_decision(p, "blk", step)
            assert d["reuse"] is False, (step, d)
            assert "0000stale0000000" in d["detail"]
            assert _live(step) in d["detail"]


def test_an_artefact_that_names_no_producer_is_not_inherited():
    # silence is not agreement
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = _mk(Path(td), "A2_topology_select", None)
        d = r.producer_reuse_decision(p, "blk", "A2_topology_select")
        assert d["reuse"] is False
        assert "UNKNOWN" in d["detail"]


def test_the_judgement_does_not_use_mtime_or_a_file_name():
    src = Path(r.__file__).read_text()
    blk = src[src.index("def producer_reuse_decision"):]
    blk = blk[:blk.index("\n\n\n")] if "\n\n\n" in blk else blk
    for banned in ("st_mtime", "getmtime", "stat()"):
        assert banned not in blk, banned


def test_the_decision_is_taken_before_the_gate_runs():
    """A stale artefact can make the gate FAIL as easily as PASS — measured on
    A3, where a leftover netlist disagreed with a freshly re-emitted topology
    and the step failed with nothing re-emitting the netlist."""
    src = Path(r.__file__).read_text()
    i_dec = src.index("_reuse = producer_reuse_decision(project, bname")
    i_gate = src.index("cp = _pr.run(cmd, capture_output=True, text=True)")
    assert i_dec < i_gate, "the reuse decision must precede the gate"
