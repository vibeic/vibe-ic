"""ROUND 19 — a gate report must say when it ran and what it read.

MEASURED (u_hawaii_adc / ihp-sg13g2). Round 18's acceptance verdict cited
`a8_topology_behaviour.json` as "the behaviour gate's own report ... verdict
FAIL". File times on that host:

    14:50:28   a8_topology_behaviour.json   (the cited report)
    15:24:48   the round's workspace was cloned
    16:12:02   delta_sigma.sp, the netlist it was supposed to have judged

The report predates the workspace by 34 minutes and the netlist by 82. It was
the PREVIOUS round's, left on disk because A8 waived before the gate ran, and
it was read as this round's verdict. A lane measurement and a gate verdict are
different things, and the report as it stood could not tell them apart: it
carried `{gate, verdict, blocks, rc}` and nothing else — no time, no identity
of what it read — so a stale file was indistinguishable from a fresh one.

Nothing here stops a gate from being skipped; that is the runner's business.
This makes the skip VISIBLE after the fact, which is what was missing.
"""
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
mod = importlib.import_module("analog_topology_behaviour_check")


def _project(tmp_path, block="blk", netlist=b"* a netlist\n"):
    b = tmp_path / "phase3" / "analog" / block
    b.mkdir(parents=True)
    (b / "topology.json").write_bytes(b'{"x":1}')
    (b / f"{block}.sp").write_bytes(netlist)
    (b / "spec.json").write_bytes(b'{"specs":[]}')
    return tmp_path


def test_the_report_states_when_it_was_produced(tmp_path):
    p = _project(tmp_path)
    out = tmp_path / "r.json"
    mod.main([str(p), "--block", "blk", "--json", str(out)])
    d = json.loads(out.read_text())
    assert "produced_at" in d and d["produced_at"].endswith("Z"), d.keys()


def test_the_report_names_the_bytes_it_judged(tmp_path):
    p = _project(tmp_path)
    out = tmp_path / "r.json"
    mod.main([str(p), "--block", "blk", "--json", str(out)])
    ident = json.loads(out.read_text())["inputs"]["blk"]
    assert set(ident) == {"topology.json", "blk.sp", "spec.json"}
    assert all(len(v) == 16 for v in ident.values()), ident


def test_a_changed_netlist_changes_the_recorded_identity(tmp_path):
    # The load-bearing property: this is what lets a later reader ask "is this
    # report about the netlist I am looking at?" — the question round 18 could
    # not ask. A stamp that does not move when the input moves is decoration.
    a = tmp_path / "a"
    b = tmp_path / "b"
    _project(a, netlist=b"* first\n")
    _project(b, netlist=b"* second, materially different\n")
    ids = []
    for root in (a, b):
        out = root / "r.json"
        mod.main([str(root), "--block", "blk", "--json", str(out)])
        ids.append(json.loads(out.read_text())["inputs"]["blk"]["blk.sp"])
    assert ids[0] != ids[1], f"identity did not move with the netlist: {ids}"


def test_an_absent_input_is_recorded_as_ABSENT_not_as_a_hash(tmp_path):
    p = _project(tmp_path)
    (p / "phase3" / "analog" / "blk" / "spec.json").unlink()
    out = tmp_path / "r.json"
    mod.main([str(p), "--block", "blk", "--json", str(out)])
    ident = json.loads(out.read_text())["inputs"]["blk"]
    assert ident["spec.json"] == "ABSENT"
    # and the ones that ARE there still hash, so one absence does not blank
    # the whole record.
    assert ident["topology.json"] != "ABSENT"


def test_the_verdict_and_rc_still_travel_with_the_report(tmp_path):
    # Adding fields must not displace what readers already consume.
    p = _project(tmp_path)
    out = tmp_path / "r.json"
    rc = mod.main([str(p), "--block", "blk", "--json", str(out)])
    d = json.loads(out.read_text())
    assert d["rc"] == rc and d["gate"] and d["verdict"] in ("PASS", "FAIL")
    assert isinstance(d["blocks"], list)
