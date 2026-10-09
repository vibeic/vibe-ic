"""Focused contracts for Default producer invocation evidence."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import default_invocation_evidence as evidence


INVOCATION = {
    "invocation_id": "i" * 64,
    "request_digest": "r" * 64,
    "route_digest": "t" * 64,
    "source_sha": "s" * 64,
    "project_digest": "p" * 64,
}


def _producer(value):
    def run():
        return value
    return run


def _read_one(project: Path):
    files = list((project / "reports/execution" / INVOCATION["invocation_id"] / "default").glob("*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text().splitlines() if line]
    assert len(rows) == 1
    return rows[0]


def test_default_receipt_binds_producer_and_gate_to_same_invocation(tmp_path):
    (tmp_path / "phase2/stage1").mkdir(parents=True)
    source = tmp_path / "phase2/stage1/input.v"
    output = tmp_path / "phase2/stage1/output.v"
    source.write_text("module input; endmodule\n")

    session = evidence.start(
        tmp_path, "design_one_shot_runner", "rtl_gen", ("1", "2", "3"),
        producer=_producer("pass"), inputs=("phase2/stage1/input.v",),
        declared_outputs=("phase2/stage1/output.v",), invocation=INVOCATION)
    output.write_text("module output; endmodule\n")
    entry = session.finish({"status": "PASS"}, preflight=type("D", (), {
        "verdict": "READY", "identity": "confirmed"})())

    assert entry["invocation_id"] == INVOCATION["invocation_id"]
    assert entry["request_digest"] == INVOCATION["request_digest"]
    assert entry["flow_steps"] == ["1", "2", "3"]
    assert entry["producer_status"] == "PASS"
    assert entry["gate"]["same_invocation"] == INVOCATION["invocation_id"]
    assert entry["output_hashes"]
    assert evidence.verify_record(tmp_path, entry) == (True, "ok")


def test_hash_mutation_refuses_the_recorded_invocation(tmp_path):
    output = tmp_path / "result.json"
    output.write_text('{"value": 1}\n')
    session = evidence.start(
        tmp_path, "phase3_one_shot_runner", "synth", ("9",),
        producer=_producer("pass"), declared_outputs=("result.json",), invocation=INVOCATION)
    entry = session.finish({"status": "PASS"})
    output.write_text('{"value": 2}\n')
    ok, reason = evidence.verify_record(tmp_path, entry)
    assert not ok
    assert reason == "output:result.json"


def test_consumer_metadata_mutation_refuses_without_recomputed_digest(tmp_path):
    output = tmp_path / "result.json"
    session = evidence.start(
        tmp_path, "phase3_one_shot_runner", "synth", ("9",),
        producer=_producer("pass"), declared_outputs=("result.json",), invocation=INVOCATION)
    output.write_text("fresh\n")
    entry = session.finish({"status": "PASS"}, preflight=type("D", (), {
        "verdict": "READY", "identity": "confirmed"})())
    assert evidence.verify_record(tmp_path, entry) == (True, "ok")
    entry["consumer"]["reason"] = "tampered"
    assert evidence.verify_record(tmp_path, entry) == (False, "receipt-digest")


def test_receipt_write_failure_is_not_fail_open(tmp_path, monkeypatch):
    output = tmp_path / "result.json"
    session = evidence.start(
        tmp_path, "phase3_one_shot_runner", "synth", ("9",),
        producer=_producer("pass"), declared_outputs=("result.json",), invocation=INVOCATION)
    output.write_text("fresh\n")
    monkeypatch.setattr(evidence, "_append", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    try:
        session.finish({"status": "PASS"})
    except RuntimeError as exc:
        assert "disk full" in str(exc)
    else:
        raise AssertionError("receipt write failure was accepted")


def test_controller_dispatch_is_not_attributed_to_native_producer(tmp_path):
    output = tmp_path / "result.json"
    session = evidence.start(
        tmp_path, "phase3_one_shot_runner", "synth", ("9",),
        producer=_producer("native"), declared_outputs=("result.json",), invocation=INVOCATION)
    session.bind_dispatch("execution_policy.dispatch_ordinary_site", "controller", producer=lambda: None)
    output.write_text("controller\n")
    entry = session.finish({"status": "PASS"})
    assert entry["producer_kind"] == "controller"
    assert entry["dispatch_path"] == "execution_policy.dispatch_ordinary_site"


def test_coarse_span_is_preserved_and_not_expanded_into_fake_rows(tmp_path):
    output = tmp_path / "pnr.def"
    session = evidence.start(
        tmp_path, "phase3_one_shot_runner", "pnr",
        ("15", "15.5ic", "16", "17", "18", "19", "20", "21", "22"),
        producer=_producer("pass"), declared_outputs=("pnr.def",), invocation=INVOCATION)
    output.write_text("VERSION 5.8 ;\n")
    entry = session.finish({"status": "PASS"})
    assert entry["flow_steps"] == ["15", "15.5ic", "16", "17", "18", "19", "20", "21", "22"]
    assert len(entry["flow_steps"]) > 1
    assert entry["receipt_kind"] == "canonical-producer-invocation"
