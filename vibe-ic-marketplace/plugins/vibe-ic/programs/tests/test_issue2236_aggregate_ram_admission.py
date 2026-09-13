"""Deterministic coverage for #2236 aggregate PVT-corner admission."""
from __future__ import annotations
import importlib.util
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_corner_admission.py"
spec = importlib.util.spec_from_file_location("aca", PROG)
aca = importlib.util.module_from_spec(spec); spec.loader.exec_module(aca)
G = 1024 ** 3

def load_sweep():
    sweep = PROG.parent / "analog_real_corner_sweep.py"
    spec = importlib.util.spec_from_file_location("issue2236_sweep", sweep)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def ledger(tmp_path, active=0, state_dir=None):
    return aca.AdmissionLedger(tmp_path, ram_bytes=126 * G, headroom=16 * G,
                               active_bytes=lambda: active,
                               state_dir=state_dir or tmp_path / "host-state")

def test_five_32g_corners_admit_exactly_three_then_release_unblocks_fourth(tmp_path):
    l = ledger(tmp_path)
    assert l.plan([{"id": str(i)} for i in range(5)], 32 * G)["safe_concurrency"] == 3
    held = [l.reserve(f"corner-{i}", 32 * G) for i in range(3)]
    with pytest.raises(aca.AdmissionRefused, match="aggregate RAM"):
        l.reserve("corner-4", 32 * G)
    l.release(held.pop(), outcome="docker_rc_0")
    assert l.reserve("corner-4", 32 * G)

@pytest.mark.parametrize("value", ["", "0", "0g", "32", "garbage", "129g"])
def test_unknown_zero_malformed_or_over_budget_never_reaches_docker(tmp_path, value):
    calls = []
    l = ledger(tmp_path)
    def run(argv, **_): calls.append(argv); return subprocess.CompletedProcess(argv, 0, "", "")
    if value == "129g":
        with pytest.raises(aca.AdmissionRefused):
            aca.launch(l, job_id="x", reservation=value, image="image", project=tmp_path,
                       workdir=tmp_path, simulation_args=["--skip", "ngspice"], runner=run)
    else:
        with pytest.raises(aca.AdmissionRefused): aca.parse_bytes(value)
    assert calls == []

def test_no_explicit_corner_reservation_is_refused():
    with pytest.raises(aca.AdmissionRefused):
        aca.declared_reservation({})

def test_selected_container_memory_is_the_no_env_reservation_fallback():
    raw, amount = aca.declared_reservation({}, container_memory=str(32 * G))
    assert raw == str(32 * G)
    assert amount == 32 * G

def test_a4_reads_selected_container_memory_when_env_is_unset(monkeypatch):
    sweep = load_sweep()
    monkeypatch.delenv("VIBEIC_ANALOG_CORNER_MEMORY", raising=False)
    monkeypatch.delenv("VIBEIC_DOCKER_MEMORY", raising=False)
    monkeypatch.setattr(sweep.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, str(32 * G) + "\n", ""))
    assert sweep._corner_reservation("selected-a4") == (str(32 * G), 32 * G)

def test_a4_refuses_zero_container_memory_before_launch(monkeypatch):
    sweep = load_sweep()
    monkeypatch.delenv("VIBEIC_ANALOG_CORNER_MEMORY", raising=False)
    monkeypatch.delenv("VIBEIC_DOCKER_MEMORY", raising=False)
    monkeypatch.setattr(sweep.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, "0\n", ""))
    with pytest.raises(sweep._aca.AdmissionRefused):
        sweep._corner_reservation("selected-a4")

@pytest.mark.parametrize("value", ["", "0", "-1", "not-a-number"])
def test_missing_or_invalid_container_memory_fallback_is_refused(value):
    with pytest.raises(aca.AdmissionRefused):
        aca.declared_reservation({}, container_memory=value)

def test_preexisting_reservations_reduce_admission(tmp_path):
    l = ledger(tmp_path, active=32 * G)
    assert l.plan([{"id": str(i)} for i in range(5)], 32 * G)["safe_concurrency"] == 2
    assert l.reserve("one", 32 * G)
    assert l.reserve("two", 32 * G)
    with pytest.raises(aca.AdmissionRefused): l.reserve("three", 32 * G)

def test_host_scoped_ledgers_from_distinct_projects_contend_for_three_total_slots(tmp_path):
    host = tmp_path / "one-host-state"
    ledgers = [ledger(tmp_path / f"project-{i}", state_dir=host) for i in range(5)]
    def reserve(i):
        try:
            return ledgers[i].reserve(f"corner-{i}", 32 * G)
        except aca.AdmissionRefused:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        tokens = list(pool.map(reserve, range(5)))
    assert sum(token is not None for token in tokens) == 3
    assert sum(token is None for token in tokens) == 2
    assert ledgers[0].reserved_bytes() == 3 * 32 * G
    assert ledgers[0].state == ledgers[4].state == host / "reservations.json"

def test_docker_command_preserves_limit_init_and_simulation_args(tmp_path):
    args = ["--skip", "bash", "-lc", "ngspice -b /w/pvt.sp"]
    argv = aca.docker_run_argv(image="immutable@sha256:abc", reservation="32g",
                               project=tmp_path, workdir=tmp_path, simulation_args=args, name="n")
    assert "--init" in argv
    assert argv[argv.index("--memory") + 1] == "32g"
    assert argv[argv.index("--memory-swap") + 1] == "32g"
    assert argv[-len(args):] == args

def test_receipts_are_machine_readable_and_swap_is_not_budgeted(tmp_path):
    l = ledger(tmp_path)
    l.plan([{"id": "a"}], 32 * G)
    token = l.reserve("a", 32 * G); l.release(token, outcome="docker_rc_0")
    root = tmp_path / "reports" / "analog" / "corner-admission"
    assert (root / "plans.jsonl").read_text()
    assert '"swap_bytes": null' in (root / "plans.jsonl").read_text()
    assert '"outcome": "docker_rc_0"' in (root / "completions.jsonl").read_text()

def test_canonical_a4_producer_is_wired_to_the_admission_api():
    source = (PROG.parent / "analog_real_corner_sweep.py").read_text()
    assert "import analog_corner_admission as _aca" in source
    assert "ThreadPoolExecutor(max_workers=workers" in source
    assert "_aca.launch(" in source
    assert '"id": f"{block}:{typ_section}:27c-base"' in source
    assert "def _corner_reservation(container):" in source
    assert "{{.HostConfig.Memory}}" in source
