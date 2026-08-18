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
import design_one_shot_runner as D  # noqa: E402


# ---------------------------------------------------------------- TB path ----
def test_step_and_helper_exist():
    assert hasattr(D, "step_professional_tb_gen")
    assert hasattr(D, "_cocotb_xml_failures")


def test_step_is_wired_into_the_plan():
    """The step must be APPENDED to the runner's plan — declaring the function
    is not enough; it was the missing invocation that this change fixes."""
    src = (PROG / "design_one_shot_runner.py").read_text()
    assert "plan.append(step_professional_tb_gen(" in src


def test_cocotb_xml_failures_counts_suite_attrs(tmp_path):
    (tmp_path / "results.xml").write_text(
        '<testsuites><testsuite failures="2" errors="1">'
        '<testcase name="t"/></testsuite></testsuites>')
    assert D._cocotb_xml_failures(tmp_path) == 3


def test_cocotb_xml_failures_zero_when_clean(tmp_path):
    (tmp_path / "results.xml").write_text(
        '<testsuite failures="0" errors="0"><testcase name="t"/></testsuite>')
    assert D._cocotb_xml_failures(tmp_path) == 0


def test_cocotb_xml_failures_element_form(tmp_path):
    # some cocotb versions emit <failure> elements with no suite attrs
    (tmp_path / "results.xml").write_text(
        '<testsuite><testcase name="t"><failure/></testcase></testsuite>')
    assert D._cocotb_xml_failures(tmp_path) == 1


def test_cocotb_xml_failures_none_when_no_file(tmp_path):
    # no results.xml → the sim never ran → None (infra), NOT a functional 0
    assert D._cocotb_xml_failures(tmp_path) is None


def test_step_skips_gracefully_without_ldocs(tmp_path):
    """Empty project → generate() SKIPs → step returns SKIP and NEVER touches
    the container (safe/additive for every non-arithmetic design)."""
    sr = D.step_professional_tb_gen(tmp_path, "chip_top", "no_such_container")
    assert sr.status == "SKIP"
    # the report is written even on SKIP, so the gate is a no-op N-A
    rep = tmp_path / "reports" / "phase2" / "gates" / "professional_tb.json"
    assert rep.is_file()


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
