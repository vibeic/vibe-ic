"""CVDP harness compose env normalization (read-only-build-dir + PEP-668 pip false-FAIL).

Two harness-packaging shapes make a CORRECT-RTL CVDP problem score as FAIL under
the OSS scorer's non-root / read-only env:
  (1) a docker-compose service that OMITS `working_dir` -> cocotb builds `sim_build/`
      under the read-only `/src` mount -> OSError Read-only file system;
  (2) a compose command that runs a bare `pip install <pkg>` -> under the non-root
      `--user $UID:$GID` + PEP-668 system Python it REFUSES (externally-managed),
      the `&&` short-circuits and pytest never runs.
Both were field-measured on fibonacci_series_0001 (DUT PASSes 2/2 once both are
fixed). cvdp_env_preflight detects (advisory REFUSE) and fixes both idempotently
via --fix-compose-workdir.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[1].parent / "benchmark"
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))

import cvdp_env_preflight as P  # noqa: E402

_BAD = (  # both shapes: no working_dir AND a bare pip install
    "services:\n\n  auto:\n    image: __OSS_SIM_IMAGE__\n"
    "    env_file    : ./src/.env\n    volumes:\n      - ./src:/src/:ro\n"
    '    command     : >\n      sh -c "pip install aes && pytest /src/test_runner.py"\n'
)
_GOOD = (  # already well-formed
    "services:\n\n  01-new-tb:\n    image: __OSS_SIM_IMAGE__\n"
    "    volumes:\n      - ./src/:/src/:ro\n    working_dir : /code/rundir\n"
    "    env_file    : ./src/.env\n    command     : pytest /src/test_runner.py\n"
)


def test_inject_working_dir_after_image():
    out = P.inject_working_dir(_BAD)
    assert "working_dir : /code/rundir" in out
    assert out.index("image:") < out.index("working_dir") < out.index("command")


def test_inject_working_dir_idempotent():
    assert P.inject_working_dir(_GOOD) == _GOOD


def test_inject_pip_break_system():
    out = P.inject_pip_break_system(_BAD)
    assert "pip install --break-system-packages aes" in out
    # idempotent
    assert P.inject_pip_break_system(out) == out


def test_pip_not_touched_when_already_fixed():
    fixed = "command: sh -c \"pip install --break-system-packages aes\""
    assert P.inject_pip_break_system(fixed) == fixed


def test_detect_flags_both_shapes(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "docker-compose.yml").write_text(_BAD)
    good = tmp_path / "good"
    good.mkdir()
    (good / "docker-compose.yml").write_text(_GOOD)
    assert [p.name for p in P.compose_needs_env_fix(bad)] == ["docker-compose.yml"]
    assert P.compose_needs_env_fix(good) == []
    # the individual detectors agree
    assert P.compose_missing_working_dir(bad)
    assert P.compose_pip_needs_break_system(bad)


def test_normalize_fixes_both_and_idempotent(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    cf = d / "docker-compose.yml"
    cf.write_text(_BAD)
    changed = P.normalize_compose_working_dir(d)
    assert changed == [cf]
    txt = cf.read_text()
    assert "working_dir : /code/rundir" in txt
    assert "pip install --break-system-packages aes" in txt
    assert P.normalize_compose_working_dir(d) == []   # idempotent


def test_cli_refuses_then_fix_passes(tmp_path):
    d = tmp_path / "fib"
    d.mkdir()
    (d / "docker-compose.yml").write_text(_BAD)
    j = tmp_path / "v.json"
    assert P.main(["--problem-dir", str(d), "--json", str(j)]) == 1
    assert json.loads(j.read_text())["verdict"] == "REFUSE"
    assert P.main(["--problem-dir", str(d), "--fix-compose-workdir",
                   "--json", str(j)]) == 0
    v = json.loads(j.read_text())
    assert v["verdict"] == "PASS" and v["compose_env_fixed"]
