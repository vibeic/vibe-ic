#!/usr/bin/env python3
r"""test_cvdp_phase1_entry.py — the DETERMINISTIC Phase-1-entry CVDP driver.

ORGANIC-20260705 (cvdp-phase1-canonical-entry). Verifies the driver that forces
every CVDP record THROUGH the plugin's Phase-1 entry (not the legacy blind-author
Shape-C flow):
  * staging reads ONLY input.prompt + input.context — never output/harness (oracle);
  * staging is deterministic (same record → same files/bytes);
  * the input.context real `module (...)` header is placed where Phase-1's
    real-declaration extractor finds it (deterministic top_module);
  * the emit-path classifier honestly separates deterministic json-to-rtl from
    the needs_ai_backup (prose-body → spec-to-rtl) hand-off.

Run: python3 -m pytest programs/tests/test_cvdp_phase1_entry.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[2] / "benchmark"
_MOD = _BENCH / "cvdp_phase1_entry.py"
_spec = importlib.util.spec_from_file_location("cvdp_phase1_entry", _MOD)
E = importlib.util.module_from_spec(_spec)
sys.modules["cvdp_phase1_entry"] = E
_spec.loader.exec_module(E)


_CTX_RTL = (
    "module decoder_64b66b (\n"
    "    input  wire        clk_in,\n"
    "    input  wire        rst_in,\n"
    "    input  wire [65:0] decoder_data_in,\n"
    "    output reg  [63:0] decoder_data_out\n"
    ");\nendmodule\n")

RECORD = {
    "id": "cvdp_copilot_demo_0001",
    "input": {
        "prompt": "Implement the module `decoder_64b66b` per the spec.",
        "context": {"rtl/decoder_64b66b.sv": _CTX_RTL},
    },
    # oracle — MUST never be read/staged by the Phase-1 entry.
    "output": {"response": "SECRET GOLDEN RTL", "context": {"x": "y"}},
    "harness": {"src": {"test.py": "SECRET COCOTB HARNESS"}},
}


def test_staging_reads_only_input_not_oracle(tmp_path):
    case = tmp_path / "case"
    E._stage_case(RECORD, case)
    # prompt + context staged
    assert (case / "input" / "phase1_prompt.md").read_text().startswith(
        "Implement the module")
    assert (case / "rtl" / "decoder_64b66b.sv").read_text() == _CTX_RTL
    # the oracle strings must appear NOWHERE under the staged case dir.
    blob = "".join(p.read_text(errors="ignore")
                   for p in case.rglob("*") if p.is_file())
    assert "SECRET GOLDEN RTL" not in blob
    assert "SECRET COCOTB HARNESS" not in blob


def test_staging_is_deterministic(tmp_path):
    def snapshot(root: Path):
        return {str(p.relative_to(root)): p.read_text(errors="ignore")
                for p in sorted(root.rglob("*")) if p.is_file()}
    a = tmp_path / "a"
    b = tmp_path / "b"
    E._stage_case(RECORD, a)
    E._stage_case(RECORD, b)
    assert snapshot(a) == snapshot(b)


def test_context_real_decl_is_placed_for_phase1_extractor(tmp_path):
    # the context RTL must be dropped into input/docs so Phase-1's
    # real-`module (...)`-declaration extractor recovers the true top_module.
    case = tmp_path / "case"
    E._stage_case(RECORD, case)
    docs = list((case / "input" / "docs").glob("*"))
    joined = "".join(p.read_text() for p in docs)
    assert "module decoder_64b66b (" in joined
    # cross-check: the plugin's own extractor recovers it from that doc text.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import phase1_doc_one_shot_runner as P
    assert P._doc_real_module_decl_name(
        {"c.txt": _CTX_RTL}) == "decoder_64b66b"


def test_classify_emit_needs_ai_backup_when_rtl_gen_waived(tmp_path):
    case = tmp_path / "case"
    (case / "phase1" / "generated_docs").mkdir(parents=True)
    (case / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "decoder_64b66b",
                    "top_ports": [{"name": "clk_in"}, {"name": "rst_in"}]}))
    (case / "reports" / "orchestrator").mkdir(parents=True)
    (case / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        json.dumps({"steps": [{"name": "rtl_gen", "status": "WAIVED",
                               "note": "rtl_gen=null ... spec-to-rtl"}]}))
    res = E._classify_emit(case)
    assert res["top_module"] == "decoder_64b66b"
    assert res["top_ports_n"] == 2
    assert res["emit_path"] == "needs_ai_backup"
    assert res["rtl_files"] == []


def test_classify_emit_deterministic_when_json_to_rtl_fired(tmp_path):
    case = tmp_path / "case"
    (case / "phase1" / "generated_docs").mkdir(parents=True)
    (case / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "fsm_top", "top_ports": []}))
    rtl = case / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "fsm_top.sv").write_text("module fsm_top(); endmodule\n")
    (case / "reports" / "orchestrator").mkdir(parents=True)
    (case / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        json.dumps({"steps": [{"name": "rtl_gen", "status": "PASS",
                               "note": "deterministic RTL via fsm_table"}]}))
    res = E._classify_emit(case)
    assert res["emit_path"] == "deterministic"
    assert res["rtl_files"] == ["fsm_top.sv"]


def test_allowed_input_keys_exclude_oracle():
    assert "prompt" in E._ALLOWED_INPUT_KEYS
    assert "context" in E._ALLOWED_INPUT_KEYS
    assert "output" not in E._ALLOWED_INPUT_KEYS
    assert "harness" not in E._ALLOWED_INPUT_KEYS


# ---------------------------------------------------------------------------
# issue #121 — parallel-shard STARTUP RACE on shared run-dir initialisation.
# N shards over the SAME --run dir (disjoint --ids) must never strand a first
# case with an empty cases/<id>/ dir. These lock in the race-safe scaffold init.
# ---------------------------------------------------------------------------

def _rec(cid: str) -> dict:
    return {"id": cid, "input": {"prompt": f"spec for {cid}",
                                 "context": {f"rtl/{cid}.sv": _CTX_RTL}}}


def test_ensure_run_scaffold_idempotent(tmp_path):
    run = tmp_path / "run"
    # repeated + already-populated calls never raise and never wipe existing work
    E._ensure_run_scaffold(run)
    (run / "cases" / "sentinel").mkdir(parents=True)
    E._ensure_run_scaffold(run)
    E._ensure_run_scaffold(run)
    assert (run / "cases").is_dir()
    assert (run / "cases" / "sentinel").is_dir()  # peer work untouched


def test_concurrent_shards_first_case_not_stranded(tmp_path):
    # Reproduce the reported topology: several shards, ONE shared run dir whose
    # cases/ parent does not exist yet, each staging its own first case. All hit
    # the shared-scaffold init simultaneously (Barrier). No first case may end up
    # empty (issue #121) and no shard may raise.
    run = tmp_path / "run"
    n = 8
    ids = [f"cvdp_shard_{i}_first" for i in range(n)]
    barrier = threading.Barrier(n)
    errors: list = []

    def shard(cid: str) -> None:
        try:
            E._ensure_run_scaffold(run)   # what main() does at startup
            barrier.wait()                # all shards race the first-case stage
            case_dir = run / "cases" / cid
            E._stage_case(_rec(cid), case_dir)
        except Exception as e:            # noqa: BLE001 - surface any race crash
            errors.append(f"{cid}: {type(e).__name__}: {e}")

    threads = [threading.Thread(target=shard, args=(c,)) for c in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    for cid in ids:
        case_dir = run / "cases" / cid
        staged = list(case_dir.rglob("*"))
        assert staged, f"{cid}: case dir stranded EMPTY (issue #121)"
        prompt = case_dir / "input" / "phase1_prompt.md"
        assert prompt.is_file() and prompt.read_text().startswith("spec for")


def test_stage_case_does_not_wipe_peer(tmp_path):
    # A shard staging its own case must only ever touch its OWN case dir — never
    # a peer shard's already-staged dir sharing the same cases/ parent.
    run = tmp_path / "run"
    E._ensure_run_scaffold(run)
    E._stage_case(_rec("peer_a"), run / "cases" / "peer_a")
    E._stage_case(_rec("peer_b"), run / "cases" / "peer_b")
    assert (run / "cases" / "peer_a" / "input" / "phase1_prompt.md").is_file()
    assert (run / "cases" / "peer_b" / "input" / "phase1_prompt.md").is_file()


def test_atomic_write_text_is_complete_and_leaves_no_temp(tmp_path):
    # The shared report is written atomically — a reader/peer never sees an empty
    # or half-written file, and no .tmp residue is left behind.
    target = tmp_path / "phase1_entry_report.json"
    payload = json.dumps({"cases": list(range(500))})
    E._atomic_write_text(target, payload)
    assert json.loads(target.read_text()) == {"cases": list(range(500))}
    assert not list(tmp_path.glob(".*.tmp"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
