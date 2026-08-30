#!/usr/bin/env python3
"""test_score_one_missing_image_is_not_a_design_fail.py

When the OSS sim image named by `--sim-image` / `OSS_SIM_IMAGE` is not present
locally, the official harness still runs: it cannot start the container, writes a
`reports/1.txt` whose whole body is "Running harness with project name: ..." /
"Cleaning up Docker resources...", and records `{"result": 1, "errors": 1,
"execution": 1.27}`. `parse_result` reads that faithfully as FAIL — so an absent
image is reported as a DEFECT IN THE DESIGN.

Measured when this was written: `cvdp-sim-oss:v110` was present on 1 of the 6
fleet hosts, so on the other 5 every design scored FAIL regardless of its
content. A draft and a deliberately altered variant of it both came back FAIL,
which reads as "the change made no difference" when in truth neither was ever
simulated — a convergence loop fed those verdicts re-authors a correct design
forever.

The verdict must therefore be could-not-score (exit 2), never FAIL (exit 1).
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import score_one as S  # noqa: E402


def _stub_run(monkeypatch, present):
    """docker image inspect succeeds only for images in `present`."""
    import subprocess as sp
    real = sp.run
    calls = []

    def fake(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and list(cmd[:3]) == ["docker", "image", "inspect"]:
            calls.append(cmd[3])
            rc = 0 if cmd[3] in present else 1
            return sp.CompletedProcess(cmd, rc, b"", b"")
        c = [str(x) for x in cmd] if isinstance(cmd, (list, tuple)) else []
        if any("cvdp_gate" in x for x in c):
            # stand in for the gate (the sole emit path) so the test exercises
            # the preflight rather than gate behaviour
            if "--out" in c:
                out = Path(c[c.index("--out") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text('{"id": "cvdp_copilot_x_0001", "response": "module m(); endmodule"}\n')
            return sp.CompletedProcess(cmd, 0, "", "")
        if any(x.endswith("run_benchmark.py") for x in c):
            if present:
                # image is there: reaching the harness is the correct path
                return sp.CompletedProcess(cmd, 0, "", "")
            raise AssertionError(
                "the harness was invoked even though the image is absent — the "
                "preflight must refuse BEFORE the run, because afterwards an "
                "environment failure is indistinguishable from a design failure")
        return real(cmd, *a, **kw)

    monkeypatch.setattr(S.subprocess, "run", fake)
    return calls


def test_absent_image_is_could_not_score_not_fail(monkeypatch, tmp_path):
    calls = _stub_run(monkeypatch, present=set())
    verdict, logs, note = _invoke(monkeypatch, tmp_path)
    assert verdict != "FAIL", (
        "an absent image was reported as a FAILING DESIGN — that is a verdict "
        "about the environment attributed to the draft")
    assert verdict == "IMAGE_MISSING", verdict
    assert "cvdp-sim-oss" in note or "not present" in note, note
    # exit-code contract: anything that is not PASS/FAIL is could-not-score (2)
    assert (0 if verdict == "PASS" else (1 if verdict == "FAIL" else 2)) == 2
    assert calls, "the preflight never asked docker whether the image exists"


def test_present_image_does_not_refuse(monkeypatch, tmp_path):
    _stub_run(monkeypatch, present={"img:present"})
    verdict, _, _ = _invoke(monkeypatch, tmp_path, sim_image="img:present")
    assert verdict != "IMAGE_MISSING", (
        "the preflight refused an image that IS present — it must be inert "
        "whenever the environment is sound")


def _invoke(monkeypatch, tmp_path, sim_image="cvdp-sim-oss:v110"):
    """Drive run_one far enough to reach the preflight, with the gate stubbed."""
    draft = tmp_path / "d.sv"
    draft.write_text("module m(); endmodule\n")
    ds = tmp_path / "ds.jsonl"
    ds.write_text('{"id": "cvdp_copilot_x_0001", "input": {"prompt": "p"}}\n')
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "run_benchmark.py").write_text("")

    # The gate is the sole emit path; stub it to "emitted a response" so the
    # test exercises the preflight rather than gate behaviour.
    return S.score_one(design_id="cvdp_copilot_x_0001", draft=draft, dataset=ds,
                     bench=bench, sim_image=sim_image, workdir=tmp_path / "wd")
