"""ORGANIC #540 — the sign-off STA reports must carry the PATH behind their slack.

THE DEFECT. Both corner STA emitters interpolated ONE selector into TWO commands
with different argument contracts::

    report_worst_slack {flag} >> rpt                              # -max  valid
    catch {report_checks {flag} -group_path_count 3 ... >> rpt}    # -max  INVALID

`report_worst_slack` takes ``-max``/``-min``. `report_checks` does not — it takes
``-path_delay max|min``. Measured against the OpenSTA the image ships
(3.1.0 244797f162), by executing the exact string the emitter produced::

    report_checks -max ...        -> Error 514: '-max' is not a known keyword or flag.
    report_checks -min ...        -> Error 514: '-min' is not a known keyword or flag.
    report_checks -path_delay max -> accepted (proceeds to path analysis)

So `report_checks` failed on EVERY invocation, at every corner, on every design,
and the enclosing `catch` swallowed it. Each report kept its `worst slack` number
and lost the path that produced it. Over the tracked corpus at the time of the
fix: 0 of 9 ``sta_mcorner_ocv*.rpt`` carried a worst-path dump, against 51 of 106
for every other STA report.

WHY THE OLD TESTS DID NOT CATCH IT — the reason this file exists. Three tests
guarded these stanzas, and all three asserted on the emitter's SOURCE TEXT. One
of them pinned the broken command verbatim::

    assert "catch {{report_checks {flag} -group_path_count 3 " in stanza

A text assertion passes for the whole life of this bug: the Tcl was always
emitted exactly as written, it just never executed. The `catch` that was added
by an earlier fix — for this same Error 514, then raised by the deprecated
`-group_count` — is what turned a hard abort into a silent omission, and the
tests then froze the silenced form in place.

So the tests here EXECUTE the emitted Tcl and assert on the REPORT THAT COMES
OUT. Three layers, none of which can pass on text alone:

  1. `report_checks` argument contract (always runs, no dependencies) — every
     flag the emitter passes must be one OpenSTA accepts.
  2. Tcl execution (needs `tclsh`) — run the emitted fragment in a real Tcl
     interpreter against a stub that enforces that contract, and assert the
     produced report file carries a Startpoint/Endpoint/arrival dump. The
     MUTATION CONTROL runs the pre-fix form through the same harness and
     requires the report to come out bare.
  3. Live OpenSTA (needs the container) — assert the contract against the real
     tool, so layer 1's model can never silently drift from OpenSTA.

chip/PDK-AGNOSTIC: stock OpenSTA flags and a synthetic report body; no design,
vendor or PDK literal anywhere.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R          # noqa: E402
import sta_signoff_rigor_check as G         # noqa: E402
# vibe-ic#1128 — these skips mean A VERIFICATION DID NOT HAPPEN, not that
# one passed. Declared through `not_verified_tier` so the run's roll-up
# cannot count them under `passed`; see that module's docstring.
from not_verified_tier import skip_not_verified  # noqa: E402
PULL_REMEDY = 'docker pull ghcr.io/vibeic/vibeic-eda:$(cat tools/vibeic-eda/VERSION)'
RUN_REMEDY = 'bash tools/vibeic-eda/restart-eda.sh'

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

# The container the live layer probes. Absent -> that layer skips; layers 1+2
# still run, so CI without Docker keeps real protection.
_CONTAINER_IMAGE_HINT = "vibeic-eda"

# ORGANIC #542 — every inner subprocess timeout here must leave the whole test
# comfortably inside CI's `pytest --timeout=180` bound. A test whose own budget
# exceeds the harness bound cannot fail as a test; it takes the CI subset down
# with it. Worst case for the live probe is ps + cp + exec = 100s < 180s, and
# measured on a warm container the whole probe is ~0.2s.
_DOCKER_PS_TIMEOUT_S = 10
_DOCKER_CP_TIMEOUT_S = 30
_DOCKER_EXEC_TIMEOUT_S = 60
_TCLSH_TIMEOUT_S = 60

# ── layer 1: the report_checks argument contract ────────────────────────────
# OpenSTA 3.1.0's `report_checks` keyword set (the subset any emitter here could
# reasonably use). VERIFIED live: flags outside this set raise
# `Error 514: '<flag>' is not a known keyword or flag`. `-max`/`-min` are
# report_worst_slack/report_tns spellings and are NOT in it; `-group_count` was
# removed in favour of `-group_path_count`.
_REPORT_CHECKS_KEYWORDS = {
    "-path_delay", "-group_path_count", "-endpoint_path_count", "-fields",
    "-format", "-digits", "-slack_max", "-slack_min", "-from", "-to",
    "-through", "-rise_from", "-fall_from", "-rise_to", "-fall_to",
    "-unique_paths_to_endpoint", "-corner", "-sort_by_slack", "-path_group",
}
# Explicitly rejected, with the reason, so a regression names itself.
_REPORT_CHECKS_REJECTED = {
    "-max": "report_worst_slack/report_tns spelling; report_checks needs "
            "-path_delay max",
    "-min": "report_worst_slack/report_tns spelling; report_checks needs "
            "-path_delay min",
    "-group_count": "removed from OpenSTA; use -group_path_count",
}

_REPORT_CHECKS_CALL_RE = re.compile(r"report_checks\b([^\n>]*)")


def _emitted_report_checks_flags(tcl: str) -> list:
    """Every leading-dash token the emitted Tcl passes to `report_checks`."""
    flags = []
    for m in _REPORT_CHECKS_CALL_RE.finditer(tcl):
        for tok in m.group(1).split():
            if tok.startswith("-"):
                flags.append(tok)
    return flags


@pytest.mark.parametrize("flag,mode", [("-max", "max"), ("-min", "min")])
def test_emitted_report_checks_uses_only_flags_opensta_accepts(flag, mode):
    """LAYER 1 — the emitted command must be one OpenSTA can parse.

    This is the assertion whose absence let the bug live: nothing anywhere
    checked that the token handed to `report_checks` was a `report_checks`
    token. It runs with no tclsh and no container."""
    tcl = R._report_worst_paths_tcl("/out/sta.rpt", flag)
    flags = _emitted_report_checks_flags(tcl)
    assert flags, f"no report_checks invocation emitted for {flag}: {tcl}"
    for f in flags:
        assert f not in _REPORT_CHECKS_REJECTED, (
            f"`report_checks {f}` is not a valid OpenSTA invocation "
            f"({_REPORT_CHECKS_REJECTED[f]}). This raises Error 514, and the "
            f"enclosing catch turns that into a report with no path.")
        assert f in _REPORT_CHECKS_KEYWORDS, (
            f"`report_checks {f}` is not a known OpenSTA keyword; it will "
            f"raise Error 514 and be swallowed by the catch")
    # the selector must have been TRANSLATED, not passed through
    assert "-path_delay" in flags
    assert f"-path_delay {mode}" in tcl, tcl


def test_worst_path_helper_reports_and_discloses_failure():
    """The guard stays (it protects the DRV query that follows) but is no longer
    SILENT: success and failure each leave a marker, so a report always states
    whether its slack has path evidence behind it."""
    tcl = R._report_worst_paths_tcl("/out/sta.rpt", "-max")
    assert "catch {report_checks" in tcl
    assert R._SIGNOFF_WORST_PATHS_MARKER in tcl      # success branch
    assert R._SIGNOFF_WORST_PATHS_FAILED in tcl      # failure branch
    assert "reason=$_wperr" in tcl, (
        "the failure branch must carry the TOOL's own reason — a bare 'failed' "
        "would repeat the original defect one level up")


# ── layer 2: execute the emitted Tcl, assert on the produced report ─────────

# A stub `report_checks` that enforces the measured OpenSTA contract and, when
# the invocation is valid, writes a REAL-SHAPED path dump to the redirect
# target. `>>` redirection is native to OpenSTA's Tcl wrapper, not to tclsh, so
# the stub consumes it the way OpenSTA does.
_STA_STUB = r"""
proc _redirect_target {argv} {
  set n [llength $argv]
  for {set i 0} {$i < $n} {incr i} {
    set a [lindex $argv $i]
    if {$a eq ">>" || $a eq ">"} { return [lindex $argv [expr {$i + 1}]] }
  }
  return ""
}
proc report_checks {args} {
  set accepted {%%ACCEPTED%%}
  set path ""
  set n [llength $args]
  for {set i 0} {$i < $n} {incr i} {
    set a [lindex $args $i]
    if {$a eq ">>" || $a eq ">"} { break }
    if {[string index $a 0] eq "-"} {
      if {[lsearch -exact $accepted $a] < 0} {
        error "Error 514: t.tcl line 1, '$a' is not a known keyword or flag."
      }
      if {$a eq "-path_delay"} { set path [lindex $args [expr {$i + 1}]] }
    }
  }
  set f [open [_redirect_target $args] a]
  puts $f "Startpoint: _r0_ (rising edge-triggered flip-flop clocked by clk)"
  puts $f "Endpoint: _r1_ (rising edge-triggered flip-flop clocked by clk)"
  puts $f "Path Type: $path"
  puts $f "                          21.33   data arrival time"
  puts $f "                         -19.83   slack (VIOLATED)"
  close $f
}
proc report_worst_slack {args} {
  set f [open [_redirect_target $args] a]
  puts $f "worst slack max -19.83"
  close $f
}
"""


def _run_tcl(tmp_path: Path, fragment: str, rpt: Path) -> str:
    """Execute an emitted Tcl fragment for real and return the REPORT body."""
    accepted = " ".join(sorted(_REPORT_CHECKS_KEYWORDS))
    script = tmp_path / "frag.tcl"
    script.write_text(_STA_STUB.replace("%%ACCEPTED%%", accepted) + fragment)
    rpt.write_text("worst slack max -19.83\n")     # the slack line always lands
    r = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                       timeout=_TCLSH_TIMEOUT_S)
    assert r.returncode == 0, r.stderr
    return rpt.read_text()


@needs_tclsh
@pytest.mark.parametrize("flag", ["-max", "-min"])
def test_emitted_tcl_executes_into_a_report_carrying_a_path(tmp_path, flag):
    """LAYER 2, THE REGRESSION — execute the emitted fragment and require the
    REPORT to carry a path.

    This is the assertion the old tests could not make. It keys on the output
    of running the Tcl, so it fails for ANY reason the path dump does not
    arrive — a bad flag, a mis-ordered guard, a dropped redirect — not only for
    the one broken literal that used to be pinned."""
    rpt = tmp_path / "sta.rpt"
    body = _run_tcl(tmp_path, R._report_worst_paths_tcl(str(rpt), flag), rpt)
    assert "Startpoint:" in body, body
    assert "Endpoint:" in body, body
    assert "data arrival time" in body, body
    # and the report says the query ran, at the right path delay
    mode = "min" if flag == "-min" else "max"
    assert f"SIGNOFF_WORST_PATHS_REPORTED path_delay={mode}" in body, body
    assert "SIGNOFF_WORST_PATHS_FAILED" not in body, body
    # END-TO-END: the sign-off rigor gate must now SEE that evidence.
    assert G.evaluate(body)["worst_path_evidence"] is True


@needs_tclsh
@pytest.mark.parametrize("flag", ["-max", "-min"])
def test_mutation_control_the_prefix_form_yields_a_bare_report(tmp_path, flag):
    """MUTATION CONTROL — the PRE-FIX command, through the same harness, must
    produce a report with NO path. Without this the test above could be passing
    because the stub always writes a dump.

    This reproduces the defect exactly: the slack survives, the path does not,
    and the script exits 0 because the `catch` swallowed the error."""
    rpt = tmp_path / "sta.rpt"
    prefix_form = (
        f"if {{[catch {{report_checks {flag} -group_path_count 3 "
        f"-fields {{slew capacitance}} >> {rpt}}} _e]}} {{\n"
        f'  set _f [open {rpt} a]\n'
        f'  puts $_f "{R._SIGNOFF_WORST_PATHS_FAILED}max reason=$_e"\n'
        f"  close $_f\n}}\n")
    body = _run_tcl(tmp_path, prefix_form, rpt)
    assert "Startpoint:" not in body, body
    assert "data arrival time" not in body, body
    # the slack is still there — which is precisely why nobody noticed
    assert "worst slack max" in body, body
    # and the error OpenSTA really raises is the one the stub raised
    assert "Error 514" in body, body
    assert f"'{flag}' is not a known keyword or flag" in body, body
    # the gate must call this out rather than pass it
    res = G.evaluate(body)
    assert res["worst_path_evidence"] is False, res


@needs_tclsh
def test_a_bare_catch_would_still_hide_the_failure(tmp_path):
    """MUTATION CONTROL for the DISCLOSURE half: with the original bare `catch`
    and no failure branch, the same broken command leaves the report with no
    path AND no explanation — which is how this survived to 9 of 9 reports.

    Pinning this shape proves the loud marker is what makes the difference,
    not the flag fix alone."""
    rpt = tmp_path / "sta.rpt"
    bare = (f"catch {{report_checks -max -group_path_count 3 "
            f"-fields {{slew capacitance}} >> {rpt}}}\n")
    body = _run_tcl(tmp_path, bare, rpt)
    assert "Startpoint:" not in body
    assert "SIGNOFF_WORST_PATHS_FAILED" not in body
    assert "Error 514" not in body           # totally silent
    assert G.evaluate(body)["worst_path_evidence"] is False


# ── layer 3: the contract against the real tool ────────────────────────────

def _live_container() -> str:
    """A running vibeic-eda container, or "" when none is available."""
    if shutil.which("docker") is None:
        return ""
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"],
            capture_output=True, text=True, timeout=_DOCKER_PS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    for line in r.stdout.splitlines():
        name, _, image = line.partition("\t")
        if _CONTAINER_IMAGE_HINT in image:
            return name.strip()
    return ""


def test_report_checks_contract_matches_the_real_opensta(tmp_path):
    """LAYER 3 — assert the layer-1 model against the TOOL.

    Layer 1 encodes what OpenSTA accepts. A model of a tool can drift from the
    tool, and a drifted model would re-open exactly this hole. This probes the
    real binary: no design is linked, so a flag error (514) and a
    no-network error (1571) cleanly separate "rejected at parse" from
    "accepted and reached analysis". Skips when no container is running."""
    container = _live_container()
    if not container:
        skip_not_verified("no running vibeic-eda container", RUN_REMEDY)
    probe = tmp_path / "probe.tcl"
    probe.write_text(
        'set rc [catch {report_checks -max -group_path_count 3} m]\n'
        'puts "OLD rc=$rc msg=$m"\n'
        'set rc [catch {report_checks -path_delay max -group_path_count 3} m]\n'
        'puts "NEW rc=$rc msg=$m"\n'
        'set rc [catch {report_worst_slack -max} m]\n'
        'puts "WS rc=$rc msg=$m"\n')
    dest = "/tmp/vibeic_issue540_probe.tcl"
    cp = subprocess.run(["docker", "cp", str(probe), f"{container}:{dest}"],
                        capture_output=True, text=True,
                        timeout=_DOCKER_CP_TIMEOUT_S)
    if cp.returncode != 0:
        skip_not_verified(
            f"cannot stage probe into {container}: {cp.stderr}",
            RUN_REMEDY)
    r = subprocess.run(
        ["docker", "exec", "-e", "IIC_OSIC_TOOLS_QUIET=1", container,
         "bash", "-lc",
         f"export PATH=/foss/tools/openroad/bin:/foss/tools/bin:$PATH && "
         f"sta -no_init -exit {dest} 2>&1"],
        capture_output=True, text=True, timeout=_DOCKER_EXEC_TIMEOUT_S)
    out = r.stdout
    if "OLD rc=" not in out:
        skip_not_verified(
            f"OpenSTA probe did not run in {container}: {out[-400:]}",
            RUN_REMEDY)
    old = re.search(r"OLD rc=(\d) msg=(.*)", out).group(1, 2)
    new = re.search(r"NEW rc=(\d) msg=(.*)", out).group(1, 2)
    ws = re.search(r"WS rc=(\d) msg=(.*)", out).group(1, 2)
    # the pre-fix flag is REJECTED AT PARSE by the real tool
    assert old[0] == "1" and "not a known keyword or flag" in old[1], old
    # the fixed flag gets PAST the parser (it can only fail on the absent design)
    assert "not a known keyword or flag" not in new[1], new
    # and report_worst_slack's -max really is valid there — the two commands
    # genuinely have different contracts, which is the whole defect
    assert "not a known keyword or flag" not in ws[1], ws
