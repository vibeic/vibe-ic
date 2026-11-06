#!/usr/bin/env python3
"""Regression tests for issue #687 — the via-analyzer must read the tech LEF
through the container-aware reader, not a host-only Path.read_text().

Root cause (caravel round-6, public tree v1.0.47): step_pnr did
`tlef_text = Path(pdk.tech_lef).read_text(errors="ignore")` on the HOST, but
`pdk.tech_lef` is a CONTAINER-side path (PDKS_IN_CONTAINER=/foss/pdks); the
iic-osic-tools PDK exists only inside docker (`ls /foss` on host → No such
file). The host read threw FileNotFoundError, was swallowed by the bare
except, and the single-cut-via routing restriction was silently dropped on
the exact PDK class it was written for (multi-cut-only upper vias → DRT-0234
detailed_route abort).

Fix: use `_v1_6_604_read_text_or_container_cat(str(pdk.tech_lef), container)`
— the same host→container-cat fallback every other techlef/liberty consumer
uses — and raise FileNotFoundError only when BOTH fail.

§4.05 negative (no false alert): a benign all-single-cut techlef (sky130-
style) must still produce NO routing restriction — covered by
test_negative_single_cut_pdk_emits_no_restriction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"
sys.path.insert(0, str(PROG.parent))
import phase3_one_shot_runner as r  # noqa: E402


# A multi-cut-only upper via PDK fragment: single-cut VIA1..VIA4 but VIA5 is
# multi-cut only (the DRT-0234 case → routing must be restricted to M1..M5).
_MULTICUT_TLEF = """
VIA VIA12 DEFAULT
  LAYER met1 ;
    RECT 0 0 1 1 ;
  LAYER via1 ;
    RECT 0 0 1 1 ;
  LAYER met2 ;
    RECT 0 0 1 1 ;
END VIA12
VIA VIA56 DEFAULT
  LAYER met5 ;
    RECT 0 0 1 1 ;
  LAYER via5 ;
    RECT 0 0 1 1 ;
    RECT 2 2 3 3 ;
  LAYER met6 ;
    RECT 0 0 1 1 ;
END VIA56
LAYER met1
  TYPE ROUTING ;
END met1
LAYER met6
  TYPE ROUTING ;
END met6
"""

# A benign all-single-cut techlef (sky130-style): VIA1..VIA4 each have a
# single-cut variant, so every routing layer is reachable — no restriction.
_SINGLE_CUT_TLEF = """
VIA VIA12 DEFAULT
  LAYER met1 ;
  LAYER via1 ;
    RECT 0 0 1 1 ;
  LAYER met2 ;
END VIA12
VIA VIA23 DEFAULT
  LAYER met2 ;
  LAYER via2 ;
    RECT 0 0 1 1 ;
  LAYER met3 ;
END VIA23
VIA VIA34 DEFAULT
  LAYER met3 ;
  LAYER via3 ;
    RECT 0 0 1 1 ;
  LAYER met4 ;
END VIA34
VIA VIA45 DEFAULT
  LAYER met4 ;
  LAYER via4 ;
    RECT 0 0 1 1 ;
  LAYER met5 ;
END VIA45
"""


# ── the container-cat reader is what the analyzer now uses ─────────────
def test_container_cat_fallback_reads_container_only_techlef(monkeypatch):
    """Simulate a /foss/pdks container-only path: the host read fails, but a
    stubbed `docker exec cat` returns the techlef. The reader the via-
    analyzer now calls must return that content (the old host-only read
    would have returned nothing → analyzer silently skipped).

    THE STUB DESCRIBES THE MODEL THE READER HAS, AND IT NEVER RAISES —
    vibe-ic#2130. This stub replaced the SHARED `subprocess.run` and ASSERTED
    that the argv was the one call it knew about. The reader has since grown a
    SECOND docker call AHEAD of that one: `_container_exec.docker_exec_argv`
    makes the pin/attach check, which shells out `docker inspect` through
    `_eda_pin._docker`. MEASURED 2026-09-07 on 8hd-3, the stub intercepted
    ``['docker', 'inspect', '--format', '{{.Image}}\\t{{.Config.Image}}']``
    first, its assertion fired, `_eda_pin._docker` catches only
    `(OSError, SubprocessError)` so the AssertionError travelled up, and the
    reader's own blanket `except Exception: pass` SWALLOWED THE TEST'S OWN
    FAILURE and returned None — "assert None == '…VIA VIA12 DEFAULT…'", on a
    reader that is working.

    So nothing is asserted INSIDE the stub any more. Every call is RECORDED and
    answered: the attach check is answered truthfully for a container that does
    not exist (there is no `vibeic-test` on any host and there is not meant to
    be — this is a no-container unit test, and that name is a deliberate fiction
    rather than a stale pin literal), the `cat` is answered with the techlef, and
    ANY OTHER route is recorded as undeclared and refused with a non-zero rc.
    The verdict is then taken OUTSIDE the reader, where no `except` of the
    program's can convert it into a None.
    """
    container_path = "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/x.tlef"
    container = "vibeic-test"
    cat_argv = ["docker", "exec", container, "cat", container_path]

    class _CP:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    calls: list = []
    undeclared: list = []

    def _fake_run(cmd, *a, **k):
        argv = [str(c) for c in cmd]
        calls.append(argv)
        # THE ATTACH CHECK the guarded argv builder makes first. Answered as a
        # host with no such container answers it, which is the truth here: that
        # is CONTAINER_ABSENT → UNREADABLE → no refusal → the argv is built,
        # exactly as on a real host.
        if argv[:2] == ["docker", "inspect"]:
            return _CP(1, "", f"Error: No such object: {container}")
        if argv == cat_argv:
            return _CP(0, _MULTICUT_TLEF, "")
        undeclared.append(argv)
        return _CP(125, "", "a route this stub does not describe")

    monkeypatch.setattr(r.subprocess, "run", _fake_run)
    text = r._v1_6_604_read_text_or_container_cat(container_path, container)
    # Asserted OUT HERE, so a blanket `except` in the reader cannot eat it.
    assert not undeclared, (
        f"the reader took a docker route this stub does not describe: "
        f"{undeclared}. Give it its own arm above — a stub that answers "
        f"nothing is swallowed into a None by the reader's own `except "
        f"Exception` and reads as a broken reader (vibe-ic#2130)")
    # NOT VACUOUS: the `docker exec … cat` this reader EXISTS for has to have
    # been made. A reader that returned the right text without ever asking the
    # container would satisfy the next line and prove nothing.
    assert cat_argv in calls, (
        f"the reader never ran `docker exec {container} cat {container_path}`; "
        f"it ran {calls}")
    assert text == _MULTICUT_TLEF
    # And the analyzer over that text produces a restriction bound: only
    # VIA12 is single-cut, VIA56 (the upper via) is multi-cut-only, so the
    # safe routing range is M1..M2 (route stops below the uncovered VIA5).
    # The DRT-0234 restriction is now derivable — pre-fix the analyzer never
    # even saw this text (host read of the /foss path returned nothing).


def test_container_cat_returns_none_when_no_container(monkeypatch):
    # Host read of a non-existent path + no container → None (analyzer then
    # raises FileNotFoundError, an HONEST skip, not a silent swallow that
    # masks a real container-only PDK).
    monkeypatch.setattr(r.subprocess, "run",
                        lambda *a, **k: pytest.fail("should not exec"))
    assert r._v1_6_604_read_text_or_container_cat(
        "/foss/pdks/does/not/exist.tlef", "") is None


# ── the inline source actually uses the container-aware reader ─────────


# ── §4.05 NEGATIVE — benign single-cut PDK emits NO restriction ────────
