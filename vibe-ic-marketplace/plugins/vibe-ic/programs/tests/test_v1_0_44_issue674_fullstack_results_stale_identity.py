"""ORGANIC #674 — full_stack results.json kept a STALE phantom tb/dut identity
across a DUT/TB-identity-changing re-invocation.

The "don't overwrite a richer results.json" guard in `step_full_stack_tb_gen`
preserves the per_vector / input_doc_evidence richness emitted by
step_reference_tb. But it ALSO preserved the `tb`/`dut`/`ts_unix` strings from
the PRIOR pass — so after the #661/#672 DUT resolution picks the real top (a
DIFFERENT TB filename + DUT module), results.json still advertised the prior
PHANTOM identity to every downstream consumer (misleading provenance: a TB/DUT
that is no longer the one verified).

Fix: the guard now REFRESHES `tb`/`dut`/`ts_unix` when the currently-compiled
TB/DUT identity DIFFERS from the stored one; the richness-preservation only
applies to SAME-identity re-runs.

Positive: a re-invocation with a CHANGED dut/tb identity → results.json reflects
the NEW identity, while per_vector / input_doc_evidence richness is preserved.
NO-LEAK: a SAME-identity re-run keeps the richer prior fields byte-for-byte
(ts_unix unchanged, no spurious churn).

chip-AGNOSTIC: pure string-identity compare; no chip / vendor / SKU literal.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as R  # noqa: E402
import _path_layout as _pl  # noqa: E402


_WRAP = (
    "module real_wrapper(input clk, input reset_n, output [7:0] dout);\n"
    "  real_leaf u(.clk(clk), .reset_n(reset_n), .dout(dout));\nendmodule\n")
_LEAF = "module real_leaf(input clk, input reset_n, output [7:0] dout); endmodule\n"


def _scaffold(tmp_path):
    proj = tmp_path / "proj"
    rtl = _pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "real_wrapper.v").write_text(_WRAP)
    (rtl / "real_leaf.v").write_text(_LEAF)
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "real_wrapper",
        "top_ports": [
            {"name": "clk", "direction": "input"},
            {"name": "reset_n", "direction": "input"},
            {"name": "dout", "direction": "output", "width": 8},
        ],
    }))
    sim = _pl.sim_full_stack_dir(proj)
    sim.mkdir(parents=True, exist_ok=True)
    return proj, sim


def _seed_rich(sim, *, tb, dut, ts):
    """Pre-seed a RICHER results.json (per_vector + input_doc_evidence) carrying
    a given tb/dut/ts identity."""
    (sim / "results.json").write_text(json.dumps({
        "verdict": "PASS", "pass": True,
        "tb": tb, "dut": dut, "ts_unix": ts,
        "per_vector": [{"vector_id": "v0", "verdict": "PASS"}],
        "input_doc_evidence": "prior-pass-evidence",
        "opcodes_tested": ["0x70", "0x72", "0x74"],
    }))


def test_changed_identity_refreshes_tb_dut_ts(tmp_path):
    proj, sim = _scaffold(tmp_path)
    _seed_rich(sim, tb="tb_phantom_full.v", dut="phantom_top", ts=1.0)
    res = R.step_full_stack_tb_gen(proj, "chip_top")
    assert res.status in ("PASS", "SKIP"), res.detail
    out = json.loads((sim / "results.json").read_text())
    # identity REFRESHED to the real DUT this pass compiled.
    assert out["dut"] == "real_wrapper"
    assert out["tb"] == "tb_real_wrapper_full.v"
    assert out["ts_unix"] != 1.0
    # richness PRESERVED.
    assert out["per_vector"] == [{"vector_id": "v0", "verdict": "PASS"}]
    assert out["input_doc_evidence"] == "prior-pass-evidence"


def test_no_leak_same_identity_preserves_rich_fields(tmp_path):
    proj, sim = _scaffold(tmp_path)
    # seed with the CORRECT (current-pass) identity → a same-identity re-run.
    _seed_rich(sim, tb="tb_real_wrapper_full.v", dut="real_wrapper", ts=4242.0)
    R.step_full_stack_tb_gen(proj, "chip_top")
    out = json.loads((sim / "results.json").read_text())
    # NO-LEAK: ts_unix is NOT churned (same-identity re-run preserves it).
    assert out["ts_unix"] == 4242.0
    assert out["tb"] == "tb_real_wrapper_full.v"
    assert out["dut"] == "real_wrapper"
    assert out["per_vector"] == [{"vector_id": "v0", "verdict": "PASS"}]
    assert out["input_doc_evidence"] == "prior-pass-evidence"


def test_opcodes_backfill_still_works_on_same_identity(tmp_path):
    proj, sim = _scaffold(tmp_path)
    # richer file with the right identity but MISSING opcodes_tested → backfilled
    # without touching the identity (no ts churn from identity-refresh).
    (sim / "results.json").write_text(json.dumps({
        "verdict": "PASS", "pass": True,
        "tb": "tb_real_wrapper_full.v", "dut": "real_wrapper", "ts_unix": 9.0,
        "per_vector": [{"vector_id": "v0"}],
        "input_doc_evidence": "ev",
    }))
    R.step_full_stack_tb_gen(proj, "chip_top")
    out = json.loads((sim / "results.json").read_text())
    assert out.get("opcodes_tested")            # backfilled
    assert out["ts_unix"] == 9.0                # identity unchanged → no churn
    assert out["tb"] == "tb_real_wrapper_full.v"
