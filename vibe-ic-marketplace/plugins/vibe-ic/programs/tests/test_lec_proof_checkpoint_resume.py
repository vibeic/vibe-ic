"""The LEC ladder checkpoints, and a restarted leg RESUMES instead of re-proving.

THE MEASURED FACT THIS SUITE IS BUILT ON (8HD-9, 2026-09-06). yosys marks a
`$equiv` key-point PROVEN by REWIRING that cell's \\B input to the same signal
as \\A. That is ordinary RTLIL — no side table — so `write_rtlil` /
`read_rtlil` ROUND-TRIPS the proven set across a FRESH PROCESS: on a 33-point
miter a resumed leg's `equiv_induct` reports "Found 1 unproven $equiv cells"
where the same pass from zero reports 33, and the same holds between induction
depths (`-seq 4` -> `-seq 16`).

The engine could therefore always resume. `lec_run.py` NEVER ASKED IT TO: its
recipe emitted no `write_rtlil` and no `read_rtlil` anywhere, and its PASS
cache accepts only a COMPLETED proof — so every killed or stalled leg re-proved
the same points from nothing.

WHAT THESE TESTS PIN, and each one is a direction the change could go wrong in:

  * with no checkpoint directory the emitted recipe is BYTE-IDENTICAL to the
    one before this existed (the feature is opt-in at the API, so the
    no-checkpoint path is a control and not a claim);
  * a checkpoint is written as `<rung>.il.part` and PROMOTED only for the rungs
    a log SENTINEL attests, so a write killed halfway can never be resumed from;
  * a checkpoint is refused BY NAME when it belongs to another netlist, to
    another ladder, or when its bytes changed since it was written — each with
    an interleaved POSITIVE control, because a validator that refuses
    everything passes every negative test;
  * a checkpoint is NOT A PASS: `pass_cache_eligible` is untouched and a
    complete ladder beside a non-PASS verdict stays ineligible;
  * a STOPPED run says in `lec.json` WHICH RUNG it can be resumed from, instead
    of leaving a reader to believe the work is gone.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "lec_run.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import lec_run  # noqa: E402
from not_verified_tier import skip_not_verified  # noqa: E402

_ARGS = dict(gold_files=["/p/rtl/a.v"], gate_netlist="/p/synth/netlist.v",
             top="dut", liberty="/foss/pdks/x.lib")

# The five command lines the ladder has always ended with. Spelled out here on
# purpose: if the ladder is ever reordered, the control below must be updated
# DELIBERATELY rather than silently agreeing with whatever the code now emits.
_UNCHECKPOINTED_TAIL = (
    "equiv_simple -short\n"
    "equiv_simple\n"
    "equiv_induct -seq 4\n"
    "equiv_induct -seq 16\n"
    "equiv_induct -seq 64\n"
    "equiv_status\n"
)


# ---------------------------------------------------------------------------
# The recipe
# ---------------------------------------------------------------------------
def test_recipe_without_a_checkpoint_dir_is_the_uncheckpointed_ladder():
    script = lec_run.build_equiv_script(**_ARGS)
    assert script.endswith(_UNCHECKPOINTED_TAIL), (
        "the default recipe no longer ends in the un-checkpointed ladder; a "
        "checkpoint directive leaked into the path that must stay byte-stable")
    for token in ("write_rtlil", "read_rtlil", lec_run.LEC_CHECKPOINT_SENTINEL):
        assert token not in script, f"{token} leaked into the default recipe"


def test_every_rung_writes_a_part_and_attests_it_after_the_write():
    script = lec_run.build_equiv_script(**_ARGS, checkpoint_dir="/ck")
    lines = script.splitlines()
    for idx, rung in enumerate(lec_run.LEC_CHECKPOINT_RUNGS):
        write = f"write_rtlil /ck/{rung}.il.part"
        attest = f"log {lec_run.LEC_CHECKPOINT_SENTINEL} ck:{rung}"
        assert write in lines, f"rung {rung} writes no checkpoint"
        assert attest in lines, f"rung {rung} is never attested"
        assert lines.index(attest) == lines.index(write) + 1, (
            f"the {rung} sentinel is not immediately after its write — it is "
            "the ONLY thing that says the backend pass finished")
    # ...and the ladder order is the ladder order.
    positions = [lines.index(f"write_rtlil /ck/{r}.il.part")
                 for r in lec_run.LEC_CHECKPOINT_RUNGS]
    assert positions == sorted(positions), "the rungs are emitted out of order"
    assert script.rstrip().endswith("equiv_status"), (
        "the closing equiv_status — the parser's only authority — is gone")


def test_resume_script_reads_the_checkpoint_and_emits_only_later_rungs():
    resume = {"rung": "equiv_induct_seq4", "rung_index": 1,
              "il_path": "/ck/equiv_induct_seq4.il"}
    script = lec_run.build_equiv_script(**_ARGS, checkpoint_dir="/ck",
                                        resume_from=resume)
    assert script.startswith("read_rtlil /ck/equiv_induct_seq4.il\n")
    for gone in ("read_verilog", "read_liberty", "equiv_make", "equiv_struct",
                 "equiv_simple", "equiv_induct -seq 4\n", "prep -top"):
        assert gone not in script, (
            f"{gone!r} survived into a resumed script — the whole point is "
            "that the work before the checkpoint is NOT redone")
    assert "equiv_induct -seq 16" in script and "equiv_induct -seq 64" in script


def test_resume_script_keeps_the_read_only_observables_the_parser_needs():
    """`stat` feeds `miter_is_stateless`; the closing `equiv_status` feeds the
    verdict. Losing either would make a resumed run parse differently from a
    from-zero run for a reason that has nothing to do with the design."""
    resume = {"rung": "equiv_simple_full", "rung_index": 0,
              "il_path": "/ck/equiv_simple_full.il"}
    script = lec_run.build_equiv_script(**_ARGS, checkpoint_dir="/ck",
                                        resume_from=resume)
    lines = [ln for ln in script.splitlines() if ln]
    assert "stat" in lines, "the miter histogram observable is gone"
    assert lines[2] == "equiv_status", (
        "a resumed run must STATE the position it resumed at in its own log")
    assert lines[-1] == "equiv_status"


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------
def _identity(**over):
    base = {
        "recipe_schema_version": lec_run.LEC_RECIPE_SCHEMA_VERSION,
        "gold_rtl": [{"path": "rtl/a.v", "sha256": "sha256:" + "a" * 64}],
        "gate_netlist": {"path": "n.v", "sha256": "sha256:" + "b" * 64},
        "equivalence_script": {"sha256": "sha256:" + "c" * 64},
        "top": "dut",
        "scan": {"metadata": {"state": "absent"},
                 "gate_wrapper": {"state": "absent"},
                 "gold_wrapper": {"state": "absent"}},
        "liberty": {"state": "unused"},
        "yosys": {"version": "Yosys 0.68+"},
        "container": {"image_digest": "sha256:image"},
    }
    base.update(over)
    return base


def test_checkpoint_key_ignores_the_script_and_binds_the_gate_netlist():
    a = _identity()
    b = _identity(equivalence_script={"sha256": "sha256:" + "d" * 64})
    assert lec_run.lec_checkpoint_key(a) == lec_run.lec_checkpoint_key(b), (
        "the checkpoint key moved with the script — a RESUMED run runs a "
        "different script, so it could then never find its own checkpoint")
    c = _identity(gate_netlist={"path": "n.v", "sha256": "sha256:" + "e" * 64})
    assert lec_run.lec_checkpoint_key(a) != lec_run.lec_checkpoint_key(c), (
        "a DIFFERENT gate netlist addresses the SAME checkpoint directory")
    d = _identity(recipe_schema_version="vibeic.lec.recipe.vX")
    assert lec_run.lec_checkpoint_key(a) != lec_run.lec_checkpoint_key(d)
    assert lec_run.lec_checkpoint_key(a) != lec_run.lec_cache_key(a), (
        "the checkpoint key and the PASS-cache key are the same value; one of "
        "them is then not doing its own job")


# ---------------------------------------------------------------------------
# Promotion and selection
# ---------------------------------------------------------------------------
_KEY = "sha256:" + "1" * 64
_BASE = "sha256:" + "2" * 64


def _plant(ck: Path, rung: str, body: bytes = b"# rtlil\n"):
    ck.mkdir(parents=True, exist_ok=True)
    (ck / f"{rung}.il.part").write_bytes(body)


def _log(*rungs, scope="ck"):
    return "".join(f"{lec_run.LEC_CHECKPOINT_SENTINEL} {scope}:{r}\n"
                   for r in rungs)


def test_only_a_log_attested_part_is_promoted(tmp_path):
    ck = tmp_path / "ck"
    _plant(ck, "equiv_simple_full")
    _plant(ck, "equiv_induct_seq4", b"# truncated by a kill")
    got = lec_run.promote_and_record_checkpoints(
        ck, _KEY, _BASE, _log("equiv_simple_full"))
    assert got == ["equiv_simple_full"]
    assert (ck / "equiv_simple_full.il").is_file()
    assert (ck / "equiv_simple_full.json").is_file()
    assert (ck / "equiv_induct_seq4.il.part").is_file(), (
        "the un-attested part was consumed")
    assert not (ck / "equiv_induct_seq4.il").exists(), (
        "a write the log never attested was promoted — a checkpoint truncated "
        "by a kill mid-write is exactly what this must refuse")
    picked = lec_run.select_resume_checkpoint(ck, _KEY, _BASE)
    assert picked and picked["rung"] == "equiv_simple_full"


def test_select_takes_the_furthest_rung(tmp_path):
    ck = tmp_path / "ck"
    for rung in ("equiv_simple_full", "equiv_induct_seq4",
                 "equiv_induct_seq16"):
        _plant(ck, rung, f"# {rung}".encode())
    lec_run.promote_and_record_checkpoints(
        ck, _KEY, _BASE,
        _log("equiv_simple_full", "equiv_induct_seq4", "equiv_induct_seq16"))
    picked = lec_run.select_resume_checkpoint(ck, _KEY, _BASE)
    assert picked["rung"] == "equiv_induct_seq16"
    assert picked["rung_index"] == 2


@pytest.mark.parametrize("how", ["foreign_key_asked", "foreign_key_declared",
                                 "foreign_ladder_asked",
                                 "foreign_ladder_declared", "bytes_changed",
                                 "il_removed"])
def test_select_refuses_a_checkpoint_that_is_not_this_one(tmp_path, how):
    """Each negative is bracketed by a POSITIVE control on the SAME directory:
    a validator that refuses everything would pass every negative test."""
    ck = tmp_path / "ck"
    _plant(ck, "equiv_simple_full")
    lec_run.promote_and_record_checkpoints(
        ck, _KEY, _BASE, _log("equiv_simple_full"))
    assert lec_run.select_resume_checkpoint(ck, _KEY, _BASE), (
        "POSITIVE CONTROL failed before the negative even ran")

    man = ck / "equiv_simple_full.json"
    doc = json.loads(man.read_text())
    ask_key, ask_base = _KEY, _BASE
    if how == "foreign_key_asked":
        ask_key = "sha256:" + "9" * 64
    elif how == "foreign_ladder_asked":
        ask_base = "sha256:" + "9" * 64
    elif how == "foreign_key_declared":
        doc["checkpoint_key"] = "sha256:" + "9" * 64
        man.write_text(json.dumps(doc))
    elif how == "foreign_ladder_declared":
        doc["base_script_sha256"] = "sha256:" + "9" * 64
        man.write_text(json.dumps(doc))
    elif how == "bytes_changed":
        (ck / "equiv_simple_full.il").write_bytes(b"# something else\n")
    elif how == "il_removed":
        (ck / "equiv_simple_full.il").unlink()

    assert lec_run.select_resume_checkpoint(ck, ask_key, ask_base) is None, (
        f"a checkpoint was accepted despite {how}")


# ---------------------------------------------------------------------------
# A checkpoint is not a pass
# ---------------------------------------------------------------------------
def test_a_complete_ladder_beside_a_non_pass_verdict_is_not_cache_eligible():
    inconclusive = {
        "verdict": "INCONCLUSIVE", "equivalent": False,
        "compared_points": 802, "non_equivalent_points": 0,
        "unproven_points": 1068, "inconclusive": True,
        "lec_resume": {"state": "RESUMABLE",
                       "rungs_available": list(lec_run.LEC_CHECKPOINT_RUNGS)},
    }
    assert lec_run.pass_cache_eligible(inconclusive) is False
    ok = {"verdict": "PASS", "equivalent": True, "compared_points": 32,
          "non_equivalent_points": 0, "unproven_points": 0}
    assert lec_run.pass_cache_eligible(ok) is True, (
        "POSITIVE CONTROL: the PASS shape must still be eligible, else the "
        "assertion above proves nothing")
    stopped = dict(ok, budget_exhausted=True)
    assert lec_run.pass_cache_eligible(stopped) is False
    stalled = dict(ok, progress_stalled=True)
    assert lec_run.pass_cache_eligible(stalled) is False


# ---------------------------------------------------------------------------
# Where a resumed run says it resumed from
# ---------------------------------------------------------------------------
_RESUMED_LOG = (
    "1. Executing RTLIL frontend.\n"
    "3. Executing EQUIV_STATUS pass.\n"
    "Found 9 $equiv cells in equiv:\n"
    "  Of those cells 8 are proven and 1 are unproven.\n"
    "4. Executing EQUIV_INDUCT pass.\n"
    "Found 1 unproven $equiv cells in module equiv:\n"
    "10. Executing EQUIV_STATUS pass.\n"
    "Found 9 $equiv cells in equiv:\n"
    "  Of those cells 9 are proven and 0 are unproven.\n"
    "  Equivalence successfully proven!\n"
)
_FROM_ZERO_LOG = (
    "20. Executing EQUIV_SIMPLE pass.\n"
    "Found 9 unproven $equiv cells (9 groups) in equiv:\n"
    "Proved 8 previously unproven $equiv cells.\n"
    "23. Executing EQUIV_INDUCT pass.\n"
    "Found 1 unproven $equiv cells in module equiv:\n"
    "29. Executing EQUIV_STATUS pass.\n"
    "  Of those cells 9 are proven and 0 are unproven.\n"
)


def test_resume_status_counts_reads_the_position_not_the_final_verdict():
    at = lec_run.resume_status_counts(_RESUMED_LOG)
    assert at == {"proved": 8, "unproven": 1}, (
        "the checkpoint position was read off the FINAL status — which would "
        "report the run's outcome as the position it started from")


def test_resume_status_counts_says_not_measured_rather_than_zero():
    assert lec_run.resume_status_counts(_FROM_ZERO_LOG) is None, (
        "a log whose first status comes AFTER the induction is not a "
        "read-back position, and must not be reported as one")
    assert lec_run.resume_status_counts("") is None


# ---------------------------------------------------------------------------
# End to end through main(), with a yosys that honours the checkpoint protocol
# ---------------------------------------------------------------------------
_RTL = "module dut(input a, input b, output y); assign y = a & b; endmodule\n"
_GATE = ("module dut(input a, input b, output y);\n"
         "  AND2X1 u0 (.A(a), .B(b), .Y(y));\nendmodule\n")

_STOPPED_TAIL = (
    "Found 9 $equiv cells in equiv:\n"
    + lec_run._TIMEOUT_MARKER + " (rc=124)\n")
_PASS_TAIL = ("equiv_status: Found 9 $equiv cells in equiv:\n"
              "  Of those cells 9 are proven and 0 are unproven.\n"
              "  Equivalence successfully proven!\n")


def _project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "phase2/stage1/rtl").mkdir(parents=True)
    (proj / "phase2/stage2/synth").mkdir(parents=True)
    (proj / "phase2/stage1/rtl/dut.v").write_text(_RTL, encoding="utf-8")
    (proj / "phase2/stage2/synth/netlist.v").write_text(_GATE, encoding="utf-8")
    return proj


def _install_fake_yosys(monkeypatch, scripts, *, stop_after_rung, tail,
                        writable=True):
    """A yosys that OBEYS the checkpoint protocol: it executes `write_rtlil`
    and echoes the sentinel, up to `stop_after_rung`, then stops."""
    monkeypatch.setattr(lec_run, "_container_available", lambda _c: True)
    monkeypatch.setattr(lec_run, "_container_file_exists", lambda *_a: False)
    monkeypatch.setattr(lec_run, "_yosys_version", lambda _c: "Yosys 0.68+")
    monkeypatch.setattr(lec_run, "_container_image_digest",
                        lambda _c: "sha256:image-id")
    monkeypatch.setattr(
        lec_run, "_container_dir_writable",
        lambda _c, _p: (True, "") if writable else (False, "probe refused"))

    _live_box = {}

    def _fake(_container, ys, **_kw):
        script = Path(ys).read_text(encoding="utf-8")
        scripts.append(script)
        # The real runner tees yosys into `live_log_path`; the stub must too,
        # because that file is the EVIDENCE a later resumed run carries.
        _live_box["path"] = _kw.get("live_log_path")
        out = []
        for line in script.splitlines():
            if line.startswith("write_rtlil "):
                target = Path(line.split(" ", 1)[1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"# rtlil checkpoint\n")
                out.append("Executing RTLIL backend.")
            elif line.startswith("log " + lec_run.LEC_CHECKPOINT_SENTINEL):
                rung = line.rsplit(":", 1)[1]
                out.append(line[len("log "):])
                if stop_after_rung is not None and rung == stop_after_rung:
                    return _emit(out)
        return _emit(out)

    def _emit(out):
        text = "\n".join(out) + "\n" + tail
        if _live_box.get("path"):
            try:
                Path(_live_box["path"]).write_text(text, encoding="utf-8")
            except OSError:
                pass
        return True, text

    monkeypatch.setattr(lec_run, "run_yosys_equiv", _fake)


def test_e2e_a_second_invocation_resumes_at_the_next_rung(monkeypatch,
                                                          tmp_path):
    proj = _project(tmp_path)
    argv = [str(proj), "--top", "dut", "--container", "fake",
            "--liberty", "/missing"]
    scripts = []
    _install_fake_yosys(monkeypatch, scripts,
                        stop_after_rung="equiv_simple_full",
                        tail=_STOPPED_TAIL)
    lec_run.main(argv)
    first = json.loads((proj / "reports/lec.json").read_text())
    assert first["lec_resume"]["rungs_recorded_this_run"] == \
        ["equiv_simple_full"]
    assert first["lec_resume"]["state"] == "RESUMABLE"
    assert "read_rtlil" not in scripts[0], "the FIRST run resumed from nothing"

    scripts.clear()
    _install_fake_yosys(monkeypatch, scripts, stop_after_rung=None,
                        tail=_PASS_TAIL)
    lec_run.main(argv)
    second = json.loads((proj / "reports/lec.json").read_text())
    assert scripts, "the second invocation launched nothing"
    assert scripts[0].startswith("read_rtlil "), (
        "the second invocation re-proved from zero although a checkpoint for "
        "this exact netlist was on disk")
    resumed = second["lec_resume"]["resumed_from"]
    assert second["lec_resume"]["resumed"] is True
    assert resumed["rung"] == "equiv_simple_full"
    assert resumed["rung_index"] == 0
    assert resumed["checkpoint_sha256"].startswith("sha256:")
    assert second["proof_identity"]["resume"]["checkpoint_sha256"] == \
        resumed["checkpoint_sha256"], (
            "the .il the proof consumed is not named in the proof identity, "
            "so it could be swapped under a cached PASS")
    assert "resume" not in first["proof_identity"], (
        "a FROM-ZERO identity grew a resume key; every identity on the fleet "
        "would move for a run that resumed nothing")


def test_e2e_a_stopped_run_says_which_rung_it_can_be_resumed_from(monkeypatch,
                                                                  tmp_path):
    proj = _project(tmp_path)
    scripts = []
    _install_fake_yosys(monkeypatch, scripts,
                        stop_after_rung="equiv_induct_seq4",
                        tail=_STOPPED_TAIL)
    lec_run.main([str(proj), "--top", "dut", "--container", "fake",
                  "--liberty", "/missing"])
    rep = json.loads((proj / "reports/lec.json").read_text())
    rec = rep["lec_resume"]
    assert rep["verdict"] == "INCONCLUSIVE", rep["verdict"]
    assert rec["state"] == "RESUMABLE"
    assert rec["resumable_from_rung"] == "equiv_induct_seq4"
    assert rec["state_label"] == "INCONCLUSIVE-resumable-from-rung-1"
    assert "resumes THERE" in rec["statement"]
    assert "sign-off LEC" not in rec["statement"], (
        "a resumable proof was told to buy a commercial tool")
    tele = rep["telemetry"]["record"]
    assert tele["checkpoint_state"] == "RESUMABLE"
    assert tele["rungs_recorded"] == ["equiv_simple_full", "equiv_induct_seq4"]


def test_e2e_checkpointing_is_off_when_the_container_cannot_write(monkeypatch,
                                                                  tmp_path):
    """`write_rtlil` to an unwritable path is a HARD yosys ERROR that aborts
    the whole script (measured in-container). A checkpoint is an optimisation,
    so it must never be able to fail a proof that would otherwise succeed."""
    proj = _project(tmp_path)
    scripts = []
    _install_fake_yosys(monkeypatch, scripts, stop_after_rung=None,
                        tail=_PASS_TAIL, writable=False)
    lec_run.main([str(proj), "--top", "dut", "--container", "fake",
                  "--liberty", "/missing"])
    rep = json.loads((proj / "reports/lec.json").read_text())
    assert "write_rtlil" not in scripts[0], (
        "a checkpoint write was emitted into a directory the tool cannot "
        "write — that aborts yosys and fails the proof")
    assert scripts[0].endswith(_UNCHECKPOINTED_TAIL)
    assert rep["lec_resume"]["enabled"] is False
    assert rep["lec_resume"]["reason"] == "probe refused", (
        "the probe's own reason did not reach the report verbatim — a "
        "disabled optimisation with an invented reason is a silent degrade")
    assert rep["lec_resume"]["state"] == "DISABLED"
    assert rep["verdict"] == "PASS", (
        "a probe failure changed the VERDICT; it may only change the recipe")


def test_prune_removes_only_part_files(tmp_path):
    ck = tmp_path / "ck"
    ck.mkdir()
    (ck / "equiv_simple_full.il").write_bytes(b"keep")
    (ck / "equiv_simple_full.json").write_text("{}")
    (ck / "equiv_induct_seq4.il.part").write_bytes(b"leftover")
    (ck / "somebody_elses_file").write_bytes(b"keep")
    removed = lec_run.prune_stale_checkpoint_parts(ck)
    assert removed == ["equiv_induct_seq4.il.part"]
    assert sorted(p.name for p in ck.iterdir()) == [
        "equiv_simple_full.il", "equiv_simple_full.json", "somebody_elses_file"]


# ---------------------------------------------------------------------------
# The real engine. NOT_VERIFIED when the container is out of reach, because
# "the image was missing" and "resumption does not work" are different answers.
# ---------------------------------------------------------------------------
def _eda_image():
    """The image the fleet's own EDA container runs, or None.

    A `docker run --rm -v <tmp>:<tmp>` is used rather than a `docker exec`:
    the running container does not mount pytest's tmp_path, so an exec would
    report "file not found" and be read as "resumption does not work".
    """
    import subprocess
    for probe in (["docker", "inspect", "--format", "{{.Config.Image}}",
                   "vibeic-eda"],):
        try:
            r = subprocess.run(probe, capture_output=True, text=True,
                               timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode == 0 and (r.stdout or "").strip():
            return r.stdout.strip()
    return None


def test_real_yosys_carries_the_proven_set_across_a_fresh_process(tmp_path):
    """THE MEASURED FACT the whole feature rests on, re-measured here.

    If `write_rtlil` did NOT preserve the `$equiv` proven-marking across a
    fresh-process `read_rtlil`, every resume this program does would be
    re-proving in disguise while reporting that it resumed.
    """
    import subprocess
    image = _eda_image()
    if not image:
        skip_not_verified("vibeic-eda image not available",
                          "bash tools/vibeic-eda/restart-eda.sh")
    (tmp_path / "d.v").write_text(
        "module dut(input clk, input rst, input x, output y);\n"
        "  reg st;\n"
        "  always @(posedge clk) if (rst) st <= 1'b0; else st <= st ^ x;\n"
        "  assign y = st;\nendmodule\n", encoding="utf-8")
    (tmp_path / "leg1.ys").write_text(
        "read_verilog d.v\nrename dut gold\nprep -top gold\n"
        "design -stash g\n"
        "read_verilog d.v\nrename dut gate\nprep -top gate\n"
        "design -stash t\n"
        "design -copy-from g -as gold gold\n"
        "design -copy-from t -as gate gate\n"
        "equiv_make gold gate equiv\nhierarchy -top equiv\n"
        "equiv_simple\nequiv_status\nwrite_rtlil ck.il\n", encoding="utf-8")
    (tmp_path / "leg2.ys").write_text("read_rtlil ck.il\nequiv_status\n",
                                      encoding="utf-8")

    def _run(script):
        return subprocess.run(
            ["docker", "run", "--rm", "-v", f"{tmp_path}:{tmp_path}",
             "-w", str(tmp_path), image, "--skip", "bash", "-c",
             f"yosys -s {script} 2>&1"],
            capture_output=True, text=True, timeout=900)

    r1 = _run("leg1.ys")
    if "$equiv" not in (r1.stdout or ""):
        skip_not_verified("yosys did not run in the EDA image",
                          "bash tools/vibeic-eda/restart-eda.sh")
    first = lec_run.parse_equiv_output(r1.stdout)
    assert (tmp_path / "ck.il").is_file(), "write_rtlil produced no checkpoint"
    assert first["proven"] and first["proven"] > 0, r1.stdout[-2000:]

    r2 = _run("leg2.ys")
    reread = lec_run.parse_equiv_output(r2.stdout)
    assert reread["proven"] == first["proven"], (
        "a FRESH yosys process read the checkpoint back and saw "
        f"{reread['proven']} proven where the writing process saw "
        f"{first['proven']} — the proven marking did NOT survive "
        "write_rtlil/read_rtlil, so every resume would be re-proving in "
        "disguise:\n" + (r2.stdout or "")[-2000:])
    assert "EQUIV_SIMPLE" not in (r2.stdout or "").upper(), (
        "the second leg re-ran the proof instead of reading it back, so the "
        "counts above agree for the wrong reason")


# ---------------------------------------------------------------------------
# The orphan a killed run leaves behind
# ---------------------------------------------------------------------------
def test_a_log_from_another_ladder_cannot_vouch_for_these_bytes(tmp_path):
    """The sentinel names the checkpoint DIRECTORY as well as the rung. The
    retry ladder runs up to three recipes, each with its own key and its own
    directory; without the scope, the verilog attempt's log would attest the
    slang attempt's `.part` of the same rung name."""
    ck = tmp_path / "ck"
    _plant(ck, "equiv_simple_full")
    foreign = _log("equiv_simple_full", scope="some_other_key")
    assert lec_run.checkpoints_attested_by_log(foreign, scope="ck") == []
    assert lec_run.promote_and_record_checkpoints(ck, _KEY, _BASE, foreign) == []
    assert not (ck / "equiv_simple_full.il").exists()
    # POSITIVE CONTROL on the same directory and the same rung.
    assert lec_run.promote_and_record_checkpoints(
        ck, _KEY, _BASE, _log("equiv_simple_full", scope="ck")) == \
        ["equiv_simple_full"]


def test_a_checkpoint_a_killed_run_never_published_is_recovered(tmp_path):
    """MEASURED on sha256: two COMPLETE 43.8 MB rungs sat as `.part` while the
    run was in flight. Promotion happens on this program's own return path, so
    a stop that does not route through it — the runner's outer budget killing
    lec_run.py, an OOM, a reboot — leaves them unpublished, and the next
    invocation's prune would DELETE them."""
    reports = tmp_path / "reports"
    ck = reports / "lec_checkpoints" / "ck"
    _plant(ck, "equiv_simple_full")
    _plant(ck, "equiv_induct_seq4")
    # ...but only the first write finished before the kill.
    (reports / "lec.live.20260906T000000-aaaa.rpt").write_text(
        "some yosys output\n" + _log("equiv_simple_full", scope="ck"),
        encoding="utf-8")

    got = lec_run.recover_orphan_checkpoints(ck, _KEY, _BASE, reports)
    assert got == ["equiv_simple_full"], got
    assert (ck / "equiv_simple_full.il").is_file()
    assert (ck / "equiv_induct_seq4.il.part").is_file(), (
        "the un-attested part was consumed by recovery")
    assert not (ck / "equiv_induct_seq4.il").exists()
    assert lec_run.select_resume_checkpoint(ck, _KEY, _BASE)["rung"] == \
        "equiv_simple_full"
    # The prune then removes only what recovery could not vouch for.
    assert lec_run.prune_stale_checkpoint_parts(ck) == \
        ["equiv_induct_seq4.il.part"]


def test_recovery_finds_nothing_when_no_log_attests_the_orphan(tmp_path):
    """The other direction: an orphan with NO attestation anywhere stays an
    orphan. A recovery that promoted on presence alone would resume from a
    checkpoint truncated mid-write."""
    reports = tmp_path / "reports"
    ck = reports / "lec_checkpoints" / "ck"
    _plant(ck, "equiv_simple_full", b"# truncated")
    (reports / "lec.live.20260906T000000-aaaa.rpt").write_text(
        "yosys ran and said nothing about checkpoints\n", encoding="utf-8")
    assert lec_run.recover_orphan_checkpoints(ck, _KEY, _BASE, reports) == []
    assert lec_run.select_resume_checkpoint(ck, _KEY, _BASE) is None
    assert not (reports / "lec_checkpoints" / "ck" /
                "equiv_simple_full.il").exists()


def test_recovery_runs_before_the_prune_in_main(monkeypatch, tmp_path):
    """ORDER IS THE WHOLE POINT. Recovering after pruning recovers nothing."""
    import inspect
    src = inspect.getsource(lec_run.main)
    rec = src.index("recover_orphan_checkpoints(")
    pru = src.index("prune_stale_checkpoint_parts(")
    assert rec < pru, (
        "main() prunes the `.part` files before trying to recover them, so a "
        "killed run's complete checkpoints are deleted rather than published")


# ---------------------------------------------------------------------------
# THE VERDICT A RESUMED RUN REACHES
# ---------------------------------------------------------------------------
# MEASURED ON sha256 (8HD-9, RTL vs post-DFT scan netlist, sky130A), and it is
# the defect this section exists for. From zero the proof reached
#
#     INCONCLUSIVE — 798/1837 proven, 1039 unproven, equiv_induct did NOT
#     converge, 0 counterexamples
#
# and the RESUMED run on the SAME checkpoint reached
#
#     FAIL — "the RTL and gate netlist may genuinely differ at these points"
#
# with the SAME 798/1039 counts. Not a near miss: a false NOT_EQUIVALENT, the
# exact harm `lec_run`'s module docstring says it exists to prevent, introduced
# by resumption itself. The cause is structural — a resumed run does not re-run
# the rungs below its checkpoint, so its log carries no `equiv_induct` pass,
# and `induction_did_not_converge` / `induction_ladder_exhausted` read exactly
# those lines to tell a non-converging proof from a refuted one.
_FROM_ZERO_LADDER = (
    "equiv_simple: Starting.\n"
    "Found 9 unproven $equiv cells (9 groups) in equiv:\n"
    "Proved 8 previously unproven $equiv cells.\n"
    "equiv_induct: Proving $equiv cells in module equiv.\n"
    "Found 1 unproven $equiv cells in module equiv:\n"
    "Proved 0 previously unproven $equiv cells.\n"
    "equiv_status: Found 9 $equiv cells in equiv:\n"
    "  Of those cells 8 are proven and 1 are unproven.\n")
_RESUMED_LEG_ONLY = (
    "Executing RTLIL frontend.\n"
    "equiv_status: Found 9 $equiv cells in equiv:\n"
    "  Of those cells 8 are proven and 1 are unproven.\n"
    "equiv_status: Found 9 $equiv cells in equiv:\n"
    "  Of those cells 8 are proven and 1 are unproven.\n")


def test_a_resumed_leg_alone_reaches_the_WRONG_verdict():
    """The RED, pinned. Not an academic worry — this is what shipped for one
    real sha256 run before the carry existed, and it is a false FAIL."""
    alone = lec_run.parse_equiv_output(_RESUMED_LEG_ONLY)
    full = lec_run.parse_equiv_output(_FROM_ZERO_LADDER)
    assert full["verdict"] == "INCONCLUSIVE", full["verdict"]
    assert alone["verdict"] == "FAIL", (
        "the fixture no longer reproduces the defect, so the test below proves "
        "nothing: " + alone["verdict"])
    assert alone["proven"] == full["proven"] == 8


def test_the_carried_leg_restores_the_from_zero_verdict():
    """The GREEN. Both legs, in order, are the evidence for the proof."""
    carried = lec_run.parse_equiv_output(
        _FROM_ZERO_LADDER + _RESUMED_LEG_ONLY)
    full = lec_run.parse_equiv_output(_FROM_ZERO_LADDER)
    assert carried["verdict"] == full["verdict"] == "INCONCLUSIVE"
    assert carried["equivalent"] == full["equivalent"] is False
    assert (carried["proven"], carried["unproven"]) == \
        (full["proven"], full["unproven"])


def test_the_counts_come_from_the_LAST_equiv_status_not_the_first():
    """A resumed recipe emits TWO `equiv_status`: one STATING the position it
    resumed at, one closing. Read first-match, the verdict publishes the counts
    the run STARTED from and every point the resumed rungs proved is
    invisible."""
    two = ("equiv_status: Found 9 $equiv cells in equiv:\n"
           "  Of those cells 8 are proven and 1 are unproven.\n"
           "equiv_induct: Proving $equiv cells in module equiv.\n"
           "Found 1 unproven $equiv cells in module equiv:\n"
           "Proved 1 previously unproven $equiv cells.\n"
           "equiv_status: Found 9 $equiv cells in equiv:\n"
           "  Of those cells 9 are proven and 0 are unproven.\n"
           "  Equivalence successfully proven!\n")
    p = lec_run.parse_equiv_output(two)
    assert (p["proven"], p["unproven"]) == (9, 0), (
        f"the verdict read the position the run resumed AT: {p}")
    assert p["verdict"] == "PASS"
    # ...and the probe, which already took the last one, still agrees.
    assert lec_run.lec_proved_points_from_output(two) == \
        {"proved": 9, "unproven": 0}


def test_a_prior_legs_stop_marker_is_not_carried_forward():
    """A stop marker says how THAT leg ended. Carried, it would make this run
    report a kill it did not suffer — `budget_exhausted` and `progress_stalled`
    are read off exactly these strings."""
    prior = (_FROM_ZERO_LADDER + lec_run._TIMEOUT_MARKER + " (rc=124)\n")
    text, dropped = lec_run.strip_producer_stop_markers(prior)
    assert dropped == 1
    assert lec_run._TIMEOUT_MARKER not in text
    assert "Proved 8 previously unproven" in text, (
        "the strip took the evidence with the marker")
    # POSITIVE CONTROL: a leg that was NOT stopped loses nothing.
    same, none = lec_run.strip_producer_stop_markers(_FROM_ZERO_LADDER)
    assert none == 0 and same == _FROM_ZERO_LADDER
    assert lec_run.strip_producer_stop_markers("") == ("", 0)


def test_a_checkpoint_whose_carried_evidence_is_gone_is_refused(tmp_path):
    """The conservative rule: no evidence, no resume. Running from zero is
    slower and is the only answer that stays true."""
    reports = tmp_path / "reports"
    ck = reports / "lec_checkpoints" / "ck"
    _plant(ck, "equiv_simple_full")
    log = reports / "lec.live.20260906T000000-aaaa.rpt"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("yosys output\n" + _log("equiv_simple_full", scope="ck"),
                   encoding="utf-8")
    assert lec_run.promote_and_record_checkpoints(
        ck, _KEY, _BASE, log.read_text(), evidence_log=log) == \
        ["equiv_simple_full"]

    def sel():
        r = lec_run.select_resume_checkpoint(ck, _KEY, _BASE,
                                             reports_dir=reports)
        return r["rung"] if r else None

    assert sel() == "equiv_simple_full", "POSITIVE CONTROL failed"
    raw = log.read_bytes()
    log.unlink()
    assert sel() is None, "a checkpoint was resumed with its evidence gone"
    log.write_bytes(raw)
    assert sel() == "equiv_simple_full"
    log.write_bytes(raw + b"# tampered\n")
    assert sel() is None, "a checkpoint was resumed with its evidence CHANGED"
    log.write_bytes(raw)
    assert sel() == "equiv_simple_full"
    # ...and the OLD contract, without reports_dir, still answers — which is
    # what proves the refusals above come from THIS check and nothing else.
    log.unlink()
    r = lec_run.select_resume_checkpoint(ck, _KEY, _BASE)
    assert r and r["rung"] == "equiv_simple_full"


def test_the_manifest_says_when_the_rung_finished(tmp_path):
    """`written_timestamp` is when the HOST filed the checkpoint; every rung of
    one run shares it to the millisecond. How long a rung TOOK is the .il's own
    mtime, which `os.replace` preserves and a copy does not — so the manifest
    records it."""
    ck = tmp_path / "ck"
    _plant(ck, "equiv_simple_full")
    os_mtime = 1_757_000_000
    import os as _os
    _os.utime(ck / "equiv_simple_full.il.part", (os_mtime, os_mtime))
    lec_run.promote_and_record_checkpoints(
        ck, _KEY, _BASE, _log("equiv_simple_full", scope="ck"))
    man = json.loads((ck / "equiv_simple_full.json").read_text())
    assert man["il"]["written_utc"].startswith("2025-09-04T"), \
        man["il"]["written_utc"]
    assert man["il"]["written_utc"] != man["written_timestamp"]


def test_e2e_a_resumed_run_reaches_THE_SAME_VERDICT_as_the_run_it_resumes(
        monkeypatch, tmp_path):
    """THE PROPERTY, driven through `main()` and not through the parser alone.

    A parser fed both legs classifies correctly whether or not `main` ever
    hands it both — so a test that only calls `parse_equiv_output` passes on
    the code that shipped the false FAIL. This one makes invocation 1 emit a
    FULL ladder (with equiv_induct evidence) and invocation 2 emit a RESUMED
    leg (without it), and requires the two verdicts to agree.
    """
    proj = _project(tmp_path)
    argv = [str(proj), "--top", "dut", "--container", "fake",
            "--liberty", "/missing"]

    scripts = []
    _install_fake_yosys(monkeypatch, scripts, stop_after_rung=None,
                        tail=_FROM_ZERO_LADDER)
    lec_run.main(argv)
    first = json.loads((proj / "reports/lec.json").read_text())
    assert first["verdict"] == "INCONCLUSIVE", first["verdict"]

    # A leg that got as far as rung 0 and no further is what is on disk now.
    ck = next((proj / "reports/lec_checkpoints").iterdir())
    for rung in lec_run.LEC_CHECKPOINT_RUNGS[1:]:
        for ext in (".il", ".json"):
            (ck / (rung + ext)).unlink(missing_ok=True)

    scripts.clear()
    _install_fake_yosys(monkeypatch, scripts, stop_after_rung=None,
                        tail=_RESUMED_LEG_ONLY)
    lec_run.main(argv)
    second = json.loads((proj / "reports/lec.json").read_text())

    assert second["lec_resume"]["resumed"] is True
    assert scripts[0].startswith("read_rtlil ")
    carried = second["lec_resume"].get("carried_evidence")
    assert carried, ("the resumed run carried NO evidence, so its verdict is "
                     "reached on a log that cannot contain the induction it "
                     "did not re-run")
    assert carried["sha256"].startswith("sha256:")
    assert carried["prior_leg_was_stopped"] is False
    assert second["verdict"] == first["verdict"], (
        f"resumed verdict {second['verdict']} != from-zero {first['verdict']} "
        "-- the same proof, the same design, two different answers")
    assert second["equivalent"] == first["equivalent"]
    assert (second["compared_points"], second["unproven_points"]) == \
           (first["compared_points"], first["unproven_points"])
    # ...and the published log is BOTH legs, which is what the verdict rests on.
    rpt = (proj / "reports/lec.rpt").read_text()
    assert "equiv_induct" in rpt and "RTLIL frontend" in rpt
