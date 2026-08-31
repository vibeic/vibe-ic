"""A reused --workdir made the official scorer report the PREVIOUS draft.

`run_benchmark.py` will not re-run over an existing `--prefix` tree: it leaves
the earlier `raw_result.json` and `reports/*.txt` in place. `score_one.score_one`
then parsed THAT, so scoring a second draft into the same workdir returned the
first draft's verdict.

Measured on `cvdp_copilot_binary_to_gray_0001` against the official harness:

    correct draft  -> fresh workdir  -> PASS
    WRONG draft    -> same workdir   -> PASS      <-- the lie
    WRONG draft    -> fresh workdir  -> FAIL      <-- the truth

so a broken design could be certified correct. Four independent convergence
agents hit this during a 302-design CVDP campaign; several "cannot determine
the root cause, no log" triage notes were this bug rather than missing evidence.
"""
import importlib.util
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
BENCH = PLUGIN / "benchmark"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))


def _load():
    spec = importlib.util.spec_from_file_location(
        "score_one_under_test", BENCH / "score_one.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_scorer_clears_the_prefix_before_running(monkeypatch, tmp_path):
    """THE REGRESSION, end to end: a second call into the same workdir must not
    return the first call's verdict."""
    so = _load()
    wd = tmp_path / "wd"

    calls = {"n": 0}
    verdicts = ["PASS", "FAIL"]

    def fake_run(cmd, **kw):
        # The image preflight (v1.13.28) runs BEFORE the harness and refuses to
        # score when the named image is absent. This test is about stale
        # verdicts, not about the environment, so report the image as present
        # and let the preflight stay inert. Without this branch the stub reaches
        # for `--out` on a `docker image inspect` command and dies with
        # `ValueError: '--out' is not in list` — a green-looking suite failure
        # that says nothing about the behaviour under test.
        if list(str(c) for c in cmd[:3]) == ["docker", "image", "inspect"]:
            class _Present:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Present()
        # emulate run_benchmark: write raw_result.json ONLY when the prefix is
        # absent, exactly as the real one refuses to re-run over an existing tree
        if any(str(c).endswith("run_benchmark.py") for c in cmd):
            prefix = Path(cmd[cmd.index("--prefix") + 1])
            if not prefix.exists():
                prefix.mkdir(parents=True)
                # CVDP semantics: result 0 = PASS, non-zero = FAIL
                (prefix / "raw_result.json").write_text(
                    '{"cvdp_copilot_x": {"tests": [{"result": %d}]}}'
                    % (0 if verdicts[calls["n"]] == "PASS" else 1))
                calls["n"] += 1
        else:
            # the gate: emit a non-empty response so scoring proceeds
            out = Path(cmd[cmd.index("--out") + 1])
            out.write_text('{"id": "cvdp_copilot_x", "completion": "x"}\n')

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    monkeypatch.setattr(so, "extract_one_record", lambda *a, **k: '{"id": "x"}')

    draft = tmp_path / "d.sv"
    draft.write_text("module x(); endmodule\n")
    ds = tmp_path / "ds.jsonl"
    ds.write_text("{}\n")

    v1, _, _ = so.score_one("cvdp_copilot_x", draft, ds, tmp_path, workdir=wd)
    v2, _, _ = so.score_one("cvdp_copilot_x", draft, ds, tmp_path, workdir=wd)

    assert v1 == "PASS"
    assert v2 == "FAIL", (
        "the second run returned the FIRST run's verdict — the scorer replayed a "
        "stale raw_result.json instead of clearing the prefix")
    assert calls["n"] == 2, "run_benchmark must actually re-run on the second call"


def test_the_source_clears_the_prefix_not_the_whole_workdir():
    """`--workdir` stays usable for inspecting the staged batch and response;
    only the scorer's own output tree is cleared."""
    src = (BENCH / "score_one.py").read_text(encoding="utf-8")
    assert "shutil.rmtree(score_prefix" in src, \
        "score_one must clear the scorer prefix before invoking run_benchmark"
    assert "rmtree(wd" not in src, \
        "clearing the whole workdir would discard the caller's staged inputs"
