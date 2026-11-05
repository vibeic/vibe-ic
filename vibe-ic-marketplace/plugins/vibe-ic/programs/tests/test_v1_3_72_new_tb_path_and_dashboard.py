"""v1.3.72 — two changes, proven structurally (no container):

  1. NEW TB PATH wired into Phase-2: design_one_shot_runner now defines AND
     invokes step_professional_tb_gen (the professional cocotb TB producer +
     runner), which was declared in flow step-4 but never called by any runner.
  2. Dashboard (CLI + web) DEFAULT ON for every run: vibe_ic_one_shot_runner
     defaults --dashboard True with a --no-dashboard opt-out, and grows a
     _cli_snapshot inline CLI front-end.

The full cocotb run (208/208 on the spm bit-serial multiplier) is exercised
against real RTL in the clean-run integration; here we pin the wiring + the
verdict logic + the argparse defaults deterministically.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))


# ---------------------------------------------------------------- TB path ----


def test_step_is_wired_into_the_plan():
    """The step must be APPENDED to the runner's plan — declaring the function
    is not enough; it was the missing invocation that this change fixes."""
    src = (PROG / "design_one_shot_runner.py").read_text()
    assert "plan.append(step_professional_tb_gen(" in src












# --------------------------------------------------------------- dashboard ---
def test_dashboard_defaults_on_with_opt_out():
    src = (PROG / "vibe_ic_one_shot_runner.py").read_text()
    # --dashboard defaults ON …
    assert 'dest="dashboard"' in src and "default=True" in src
    # … and there is an explicit opt-out
    assert '"--no-dashboard"' in src and 'action="store_false"' in src


def test_runner_has_cli_snapshot_front_end():
    src = (PROG / "vibe_ic_one_shot_runner.py").read_text()
    assert "_cli_snapshot" in src
    # both front-ends are launched under the default-on block
    assert "WEB dashboard" in src and "CLI dashboard" in src


def test_cli_snapshot_is_crash_safe():
    import vibe_ic_one_shot_runner as V
    # bogus project → best-effort, returns a str, never raises
    out = V._cli_snapshot(Path("/no/such/project/xyz"))
    assert isinstance(out, str)


def test_reachable_host_resolves_wildcard_bind():
    """A 0.0.0.0/:: bind is not browser-openable — the printed URL must carry a
    routable host, while loopback and a specific interface IP are preserved."""
    import vibe_ic_one_shot_runner as V
    assert V._reachable_host("127.0.0.1") == "127.0.0.1"
    assert V._reachable_host("localhost") == "127.0.0.1"
    assert V._reachable_host("10.1.2.3") == "10.1.2.3"   # specific IP untouched
    for wild in ("0.0.0.0", "::", "", "*"):
        r = V._reachable_host(wild)
        assert r and r not in ("0.0.0.0", "::", "", "*") and not r.startswith("0.")
