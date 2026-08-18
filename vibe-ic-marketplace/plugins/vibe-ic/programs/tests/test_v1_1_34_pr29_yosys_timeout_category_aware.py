"""PR #29 gatekeeper remediation — the yosys-smoke synth-TIMEOUT tolerance is
CATEGORY-AWARE and §4.05-fail-safe.

PR #29 relaxed a `synth` TIMEOUT from BLOCK to tolerate-EMIT, justified by "the
official CVDP scorer is cocotb+iverilog — it NEVER runs yosys". A Step-2.7
multi-lens review proved that premise FALSE for the area-optimization / synth-
quality category (cid007), whose OFFICIAL harness DOES run yosys 0.40
(cvdp_fail_triage SYNTH_GATE/SYNTH_THRESHOLD; cvdp_env_preflight #714
__OSS_PNR_IMAGE__; ppa_area_threshold_check #729) — so tolerating a synth-timeout
there EMITs a design the official synth gate may FAIL and loses the re-author the
#531 smoke exists to trigger (a §4.05 false-SKIP). Two MEDs accompanied it: keying
on bare rc==124 mis-tolerated a `timeout(N)`-wrapped yosys exiting 124 WITH a real
error; and an all-timeout record emitted as a clean "yosys-smoke ok" PASS.

These regressions pin the §4.05-safe remediation:
  HIGH — a genuine synth-timeout on a SYNTH-SCORED problem (detected via ANY of the
         three signals) BLOCKS (fail-safe → re-author); on a NON-synth-scored
         problem it is tolerated as INCONCLUSIVE (the dominant cocotb/iverilog
         functional population — no false fail).
  MED-B — the timeout is matched on the genuine empty-blob SHAPE `(124,"","timeout")`,
          NOT bare rc==124, so a wrapped yosys exiting 124 WITH a real ERROR falls
          through and BLOCKS.
  MED-C — when any module was only timeout-tolerated, the top-line reads
          "yosys-smoke INCONCLUSIVE", never a clean "yosys-smoke ok".

chip-AGNOSTIC: synthetic blobs / a tiny synthetic module + pure CVDP-category
structure; no design id / oracle value.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

_CODE = "module m;\n  reg a;\nendmodule\n"
_TIMEOUT = (124, "", "timeout")                       # _run's TimeoutExpired sentinel
_REAL_ERR_BLOB_OUT = " Yosys 0.40 (git sha1 deadbeef)\n2. Executing SYNTH pass.\n"
_REAL_ERR_BLOB_ERR = "ERROR: Async reset \\rst_n yields non-constant value.\n"


def _patch(monkeypatch, ret, yosys="/usr/bin/yosys"):
    monkeypatch.setattr(G, "_run", lambda cmd, timeout=120:
                        (0, "", "") if cmd[:1] == ["iverilog"] else ret)
    import shutil as _sh
    real = _sh.which
    monkeypatch.setattr(G.shutil, "which",
                        lambda n: yosys if n == "yosys" else real(n))


# --------------------------------------------------------------------------- #
# HIGH — synth-scored timeout BLOCKS; functional timeout tolerates              #
# --------------------------------------------------------------------------- #
def test_high_synth_scored_timeout_blocks(monkeypatch):
    _patch(monkeypatch, _TIMEOUT)
    ok, why = G.yosys_smoke(_CODE, Path("/tmp"), synth_scored=True)
    assert ok is False                                # §4.05: no false-SKIP
    assert "BLOCK" in why and "synth-scored" in why.lower()


def test_high_functional_timeout_tolerated_inconclusive(monkeypatch):
    _patch(monkeypatch, _TIMEOUT)
    ok, why = G.yosys_smoke(_CODE, Path("/tmp"), synth_scored=False)
    assert ok is True                                 # no false-fail of a scorable design
    assert "INCONCLUSIVE" in why                      # MED-C honest headline


def test_high_unknown_category_is_failsafe_block(monkeypatch):
    # Step-2.7 round-2: the category signals are structurally absent on a bare
    # {id,completion} draft, so UNKNOWN (synth_scored=None, the default) must
    # FAIL-SAFE BLOCK — a synth-timeout is tolerated only when POSITIVELY confirmed
    # non-synth-scored, never on unknown (else every cid007 timeout in a no-dataset
    # run leaks).
    _patch(monkeypatch, _TIMEOUT)
    ok, why = G.yosys_smoke(_CODE, Path("/tmp"))                    # default None
    assert ok is False and "UNKNOWN" in why
    ok2, _ = G.yosys_smoke(_CODE, Path("/tmp"), synth_scored=None)  # explicit None
    assert ok2 is False


# --------------------------------------------------------------------------- #
# MED-B — shape-exact sentinel: a wrapped yosys exiting 124 WITH output blocks  #
# --------------------------------------------------------------------------- #
def test_medb_wrapped_124_with_real_error_blocks(monkeypatch):
    # a `timeout(N)` PATH wrapper that exits 124 but carries a real banner+ERROR:
    # NOT the empty-blob (124,"","timeout") shape -> must fall through and BLOCK.
    _patch(monkeypatch, (124, _REAL_ERR_BLOB_OUT, _REAL_ERR_BLOB_ERR))
    ok, why = G.yosys_smoke(_CODE, Path("/tmp"), synth_scored=False)
    assert ok is False, why                           # real error not mis-tolerated
    assert "INCONCLUSIVE" not in why


def test_medb_bare_124_nonempty_not_treated_as_timeout(monkeypatch):
    # even on a non-synth-scored problem, a 124 with a NON-empty blob is not a timeout
    _patch(monkeypatch, (124, "some synth output\n", ""))
    ok, _ = G.yosys_smoke(_CODE, Path("/tmp"), synth_scored=False)
    assert ok is False


# --------------------------------------------------------------------------- #
# #604 + real-error preserved                                                  #
# --------------------------------------------------------------------------- #
def test_604_absent_yosys_still_blocks(monkeypatch):
    _patch(monkeypatch, (127, "", "No such file"), yosys=None)
    ok, _ = G.yosys_smoke(_CODE, Path("/tmp"), synth_scored=False)
    assert ok is False


def test_real_synth_error_still_blocks(monkeypatch):
    _patch(monkeypatch, (1, _REAL_ERR_BLOB_OUT, _REAL_ERR_BLOB_ERR))
    ok, _ = G.yosys_smoke(_CODE, Path("/tmp"), synth_scored=False)
    assert ok is False


# --------------------------------------------------------------------------- #
# the synth-scored detector — three single-source signals                      #
# --------------------------------------------------------------------------- #
def test_detector_area_threshold_prompt():
    assert G._problem_is_synth_scored(
        "Optimize this RTL to reduce the area (cell count) by at least 20%.",
        {"id": "x"}) is True


def test_detector_categories_cid007():
    assert G._problem_is_synth_scored(
        "any prompt", {"id": "cvdp_copilot_area_opt_0007",
                       "categories": ["cid007", "medium"]}) is True


def test_detector_oss_pnr_image_context():
    assert G._problem_is_synth_scored(
        "any prompt", {"id": "x", "input": {"context": {
            "docker/Dockerfile.synth": "FROM __OSS_PNR_IMAGE__\nRUN yosys"}}}) is True


def test_detector_functional_is_not_synth_scored():
    assert G._problem_is_synth_scored(
        "Implement a barrel shifter that rotates the input by a shift amount.",
        {"id": "cvdp_copilot_barrel_shifter_0037",
         "categories": ["cid003", "easy"]}) is False


def test_detector_no_overblock_on_functional_reduce_by_percent():
    # Step-2.7 round-2: the #729 parser treats the bare verb "reduce" as an area
    # word, so a functional "reduce <latency|power> by N%" prompt must NOT be
    # flagged synth-scored (that would over-block its synth-timeout). Signal 1 now
    # requires an explicit synthesis-AREA noun (area/cell/wire/gate/lut/netlist).
    for p in (
        "Reduce the pipeline latency by 50% while keeping throughput.",
        "Reduce dynamic power by 20% via clock gating.",
        "Generate a clock with a 10% duty cycle.",
        "Refactor to use fewer FSM states for clarity.",
    ):
        assert G._problem_is_synth_scored(p, {"id": "x"}) is False, p
    # but a real area-opt prompt (area/cell/wire noun + threshold) still fires
    for p in (
        "Optimize to reduce the cell area by at least 25%.",
        "Reduce the design to use 30% fewer cells.",
        "Achieve a 15% reduction in wires.",
    ):
        assert G._problem_is_synth_scored(p, {"id": "x"}) is True, p


# --------------------------------------------------------------------------- #
# end-to-end through gate_record — the reproduced HIGH leak is closed          #
# --------------------------------------------------------------------------- #
def test_e2e_synth_scored_area_opt_timeout_blocked(monkeypatch, tmp_path):
    _patch(monkeypatch, _TIMEOUT)
    rec = {"id": "cvdp_copilot_area_opt_0007",
           "completion": "```verilog\nmodule m;\n reg a;\nendmodule\n```"}
    prompt = "Reduce the area of this RTL by at least 30% (fewer cells and wires)."
    ok, _out, entry = G.gate_record(rec, tmp_path, prompt_text=prompt)
    assert ok is False                                # synth-scored timeout -> BLOCKED
    assert entry["verdict"] == "BLOCKED"


def test_e2e_functional_timeout_emitted(monkeypatch, tmp_path):
    _patch(monkeypatch, _TIMEOUT)
    rec = {"id": "cvdp_copilot_barrel_shifter_0037",
           "completion": "```verilog\nmodule m;\n reg a;\nendmodule\n```",
           "categories": ["cid003", "easy"]}        # known non-cid007 -> confirmed functional
    prompt = "Implement a barrel shifter that rotates the input by a shift amount."
    ok, _out, entry = G.gate_record(rec, tmp_path, prompt_text=prompt)
    assert ok is True                                 # functional timeout -> emitted
    assert "INCONCLUSIVE" in entry.get("synth", "")


# --------------------------------------------------------------------------- #
# Step-2.7 round-2: the structural deadness of categories/context on a bare    #
# {id,completion} draft is closed by the tri-state fail-safe + dataset map     #
# --------------------------------------------------------------------------- #
def test_tristate_resolver():
    R = G._resolve_synth_scored
    assert R(None, {"id": "x"}, hint=True) is True            # dataset hint synth
    assert R(None, {"id": "x"}, hint=False) is False          # dataset hint functional
    assert R("Reduce the cell area by 25%.", {"id": "x"}) is True   # prompt signal
    assert R(None, {"id": "x", "categories": ["cid014"]}) is False  # known non-cid007
    assert R(None, {"id": "x"}) is None                       # UNKNOWN -> fail-safe


def test_e2e_no_prompts_bare_cid007_rec_failsafe_blocks(monkeypatch, tmp_path):
    # the reviewer's HIGH #1: a bare {id,completion} draft (NO prompt, NO
    # categories/context) for a cid007 problem must NOT be tolerated — UNKNOWN
    # resolves to fail-safe BLOCK (no synth_scored hint, no prompt).
    _patch(monkeypatch, _TIMEOUT)
    rec = {"id": "cvdp_copilot_area_opt_0001",
           "completion": "```verilog\nmodule m;\n reg a;\nendmodule\n```"}
    ok, _out, entry = G.gate_record(rec, tmp_path)               # no prompt, no hint
    assert ok is False                                          # fail-safe BLOCK
    assert entry["verdict"] == "BLOCKED"


def test_e2e_dataset_hint_confirms_functional_tolerates(monkeypatch, tmp_path):
    # with the authoritative hint from --dataset/--prompts the SAME bare draft is
    # confirmed non-synth-scored and its timeout tolerated (no false-fail).
    _patch(monkeypatch, _TIMEOUT)
    rec = {"id": "x", "completion": "```verilog\nmodule m;\n reg a;\nendmodule\n```"}
    ok, _out, entry = G.gate_record(rec, tmp_path, synth_scored=False)
    assert ok is True
    assert "INCONCLUSIVE" in entry.get("synth", "")


def test_load_synth_scored_map(tmp_path):
    import json
    ds = tmp_path / "dataset.jsonl"
    ds.write_text("\n".join(json.dumps(r) for r in [
        {"id": "a", "categories": ["cid007", "medium"]},          # synth-scored
        {"id": "b", "categories": ["cid003", "easy"]},            # functional
        {"id": "c", "prompt": "Reduce the cell area by 25%."},    # synth via prompt
        {"id": "d", "input": {"context": {"D": "FROM __OSS_PNR_IMAGE__"}}},  # synth via ctx
        {"id": "e", "completion": "no metadata"},                 # omitted -> None
    ]))
    m = G._load_synth_scored_map(ds)
    assert m == {"a": True, "b": False, "c": True, "d": True}
    assert "e" not in m


def test_load_synth_scored_map_true_wins_intra_file_duplicate_id(tmp_path):
    # Step-2.7 round-3 HIGH: a positive synth-scored signal must WIN over a
    # non-synth-scored one for the SAME id regardless of line order — a later
    # non-cid007 line must NOT downgrade an earlier cid007=True (else a duplicate
    # -id dataset tolerates a synth-scored timeout = false-SKIP).
    import json
    for lines, want in (
        ([{"id": "d", "categories": ["cid007"]}, {"id": "d", "categories": ["cid003"]}], True),
        ([{"id": "d", "categories": ["cid003"]}, {"id": "d", "categories": ["cid007"]}], True),
        ([{"id": "d", "categories": ["cid007"], "input": {"context": {"D": "__OSS_PNR_IMAGE__"}}},
          {"id": "d", "categories": ["cid003"]}], True),
        ([{"id": "d", "categories": ["cid003"]}], False),
    ):
        f = tmp_path / "dup.jsonl"
        f.write_text("\n".join(json.dumps(x) for x in lines))
        assert G._load_synth_scored_map(f).get("d") is want, (lines, want)


def _run_main(tmp_path, batch, prompts=None, dataset=None, monkeypatch=None):
    """Drive cvdp_gate.main([...]) with yosys returning the timeout sentinel;
    return {id: verdict}. Mirrors the production --batch (+ optional --prompts/
    --dataset) invocation — the path Step-2.7 round-2 flagged as the one where the
    category signals must actually reach the timeout fail-safe."""
    import json
    import contextlib
    import io
    import shutil
    realwhich = shutil.which
    monkeypatch.setattr(G, "_run", lambda cmd, timeout=120:
                        (0, "", "") if cmd[:1] == ["iverilog"]
                        else ((124, "", "timeout") if cmd[:1] == ["yosys"]
                              else (0, "", "")))
    monkeypatch.setattr(G.shutil, "which",
                        lambda n: ("/usr/bin/" + n) if n in ("yosys", "iverilog")
                        else realwhich(n))
    bp = tmp_path / "batch.jsonl"
    bp.write_text("\n".join(json.dumps(r) for r in batch))
    out = tmp_path / "out.jsonl"
    rep = tmp_path / "rep.json"
    argv = ["--batch", str(bp), "--out", str(out), "--report", str(rep)]
    if prompts is not None:
        pp = tmp_path / "prompts.jsonl"
        pp.write_text("\n".join(json.dumps(r) for r in prompts))
        argv += ["--prompts", str(pp)]
    if dataset is not None:
        dp = tmp_path / "dataset.jsonl"
        dp.write_text("\n".join(json.dumps(r) for r in dataset))
        argv += ["--dataset", str(dp)]
    with contextlib.redirect_stderr(io.StringIO()), \
            contextlib.redirect_stdout(io.StringIO()):
        G.main(argv)
    r = json.loads(rep.read_text())
    recs = r if isinstance(r, list) else (r.get("records") or r.get("report") or [])
    return {e.get("id"): e.get("verdict") for e in recs}


def test_e2e_main_plumbing_category_reaches_failsafe(monkeypatch, tmp_path):
    # Step-2.7 round-2 HIGH: the per-id category hint from --prompts/--dataset must
    # actually reach the yosys-smoke timeout fail-safe through main()→gate_record.
    comp = "```verilog\nmodule m;\n reg a;\nendmodule\n```"
    draft = [{"id": "p1", "completion": comp}]
    # (a) no metadata at all → UNKNOWN → fail-safe BLOCK
    assert _run_main(tmp_path, draft, monkeypatch=monkeypatch).get("p1") == "BLOCKED"
    # (b) --dataset confirms a non-cid007 category → tolerate (emit)
    assert _run_main(tmp_path, draft, dataset=[{"id": "p1", "categories": ["cid003"]}],
                     monkeypatch=monkeypatch).get("p1") == "PASS"
    # (c) --dataset marks cid007 → BLOCK (the reproduced HIGH leak, closed)
    assert _run_main(tmp_path, draft, dataset=[{"id": "p1", "categories": ["cid007"]}],
                     monkeypatch=monkeypatch).get("p1") == "BLOCKED"
    # (d) --prompts area-opt prompt → BLOCK
    assert _run_main(tmp_path, draft,
                     prompts=[{"id": "p1", "prompt": "Reduce the cell area by 25%."}],
                     monkeypatch=monkeypatch).get("p1") == "BLOCKED"
