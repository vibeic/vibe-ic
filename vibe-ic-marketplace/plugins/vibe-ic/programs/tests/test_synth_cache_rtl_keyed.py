"""SYNTH CACHE MUST BE RTL-KEYED, NOT ONLY PDK-KEYED (chip/PDK-AGNOSTIC).

PROVE-FIRST floor (shipped v1.5.78, read at
`phase3_one_shot_runner.main()` around the "preserve provenance" skip):

    _nl_pdk_ok = (netlist_existing.is_file()
                  and _netlist_matches_liberty(
                      netlist_existing, str(pdk.liberty)))
    if _nl_pdk_ok:
        plan.append(StepResult("synth", "PASS", 0.0,
            "netlist already present: ... (skipped re-run to preserve provenance)"))

  * The ONLY guard is `_netlist_matches_liberty` — it asks whether the cached
    netlist's cell masters exist in the ACTIVE liberty. That catches a
    wrong-PDK netlist (PR-A3) and nothing else.
  * It does NOT ask whether the RTL changed. Edit the RTL, re-run phase 3 on
    the SAME PDK, and the stale netlist is reused: the edit is a SILENT
    NO-OP. Measured consequence in the field: two different RTL sources
    yielded a byte-identical netlist and post-route numbers agreeing to 16
    significant figures — the "improvement" measured nothing at all.
  * The PnR cache already solves this class correctly by keying the DEF on
    the requested geometry (`_pnr_cache_valid_for`, #593). Synth had no
    equivalent.

Fix under test: `_synth_cache_valid_for` keys the skip on a content
fingerprint of EXACTLY the files `step_synth` reads (shared selector
`_synth_rtl_files`, so the key and the synth command cannot diverge), plus
the liberty. An older netlist with no sidecar degrades to an mtime staleness
test and DISCLOSES that the fingerprint is unverified rather than claiming a
match it cannot prove.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import phase3_one_shot_runner as p3
import _path_layout as _pl


LIB_A = "/pdk/A/libs.ref/scl/lib/scl_typical.lib"
LIB_B = "/pdk/B/libs.ref/scl/lib/scl_typical.lib"


def _mk_project(tmp_path: Path, rtl: dict[str, str]) -> Path:
    proj = tmp_path / "proj"
    rtl_dir = _pl.rtl_dir(proj)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    for name, body in rtl.items():
        (rtl_dir / name).write_text(body)
    _pl.synth_dir(proj).mkdir(parents=True, exist_ok=True)
    return proj


def _mk_netlist(proj: Path, top: str = "top") -> Path:
    nl = _pl.synth_dir(proj) / f"{top}_synth.v"
    nl.write_text("// mapped netlist\nmodule top(); endmodule\n")
    return nl


# ---------------------------------------------------------------------------
# THE BUG: same PDK + changed RTL must invalidate the cache.
# ---------------------------------------------------------------------------
def test_rtl_edit_invalidates_the_cache(tmp_path):
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    nl = _mk_netlist(proj)
    p3._write_synth_inputs_sidecar(proj, LIB_A)

    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert ok, f"unchanged RTL should reuse: {msg}"

    # The edit that used to be a silent no-op.
    (_pl.rtl_dir(proj) / "core.v").write_text(
        "module core(); wire pipelined; endmodule\n")

    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert not ok, "RTL edit was NOT detected — the edit is a silent no-op"
    assert "core.v" in msg, msg
    assert "RTL changed" in msg


def test_added_rtl_file_invalidates_the_cache(tmp_path):
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    nl = _mk_netlist(proj)
    p3._write_synth_inputs_sidecar(proj, LIB_A)
    (_pl.rtl_dir(proj) / "extra.v").write_text("module extra(); endmodule\n")
    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert not ok and "extra.v" in msg, msg


def test_removed_rtl_file_invalidates_the_cache(tmp_path):
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n",
                                  "extra.v": "module extra(); endmodule\n"})
    nl = _mk_netlist(proj)
    p3._write_synth_inputs_sidecar(proj, LIB_A)
    (_pl.rtl_dir(proj) / "extra.v").unlink()
    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert not ok and "extra.v" in msg, msg


def test_liberty_change_invalidates_the_cache(tmp_path):
    """The PDK key must survive the new RTL key, not be replaced by it."""
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    nl = _mk_netlist(proj)
    p3._write_synth_inputs_sidecar(proj, LIB_A)
    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_B)
    assert not ok and "liberty changed" in msg, msg


def test_unchanged_rtl_still_reuses(tmp_path):
    """The provenance-preserving skip must still fire when nothing moved —
    this fix must not turn every run into a re-synth."""
    proj = _mk_project(tmp_path, {"a.v": "module a(); endmodule\n",
                                  "b.sv": "module b(); endmodule\n"})
    nl = _mk_netlist(proj)
    p3._write_synth_inputs_sidecar(proj, LIB_A)
    for _ in range(3):
        ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
        assert ok, msg
        assert "fingerprint matches" in msg


# ---------------------------------------------------------------------------
# Backwards compatibility: a netlist with no sidecar.
# ---------------------------------------------------------------------------
def test_no_sidecar_older_rtl_reuses_but_discloses_unverified(tmp_path):
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    nl = _mk_netlist(proj)
    old = nl.stat().st_mtime - 500
    os.utime(_pl.rtl_dir(proj) / "core.v", (old, old))
    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert ok, msg
    assert "UNVERIFIED" in msg, "must not claim a match it cannot prove"


def test_no_sidecar_newer_rtl_is_stale(tmp_path):
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    nl = _mk_netlist(proj)
    future = nl.stat().st_mtime + 500
    os.utime(_pl.rtl_dir(proj) / "core.v", (future, future))
    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert not ok and "newer" in msg, msg


def test_missing_netlist_is_never_reusable(tmp_path):
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    ok, msg = p3._synth_cache_valid_for(
        proj, _pl.synth_dir(proj) / "top_synth.v", LIB_A)
    assert not ok and "no cached netlist" in msg


def test_corrupt_sidecar_forces_resynth(tmp_path):
    """An unreadable key must fail CLOSED (re-synth), never open."""
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    nl = _mk_netlist(proj)
    (_pl.synth_dir(proj) / p3._SYNTH_INPUTS_SIDECAR).write_text("{not json")
    ok, msg = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert not ok and "unreadable" in msg, msg


# ---------------------------------------------------------------------------
# The shared selector — the fingerprint must cover EXACTLY synth's inputs.
# ---------------------------------------------------------------------------
def test_selector_excludes_non_silicon_sources(tmp_path):
    proj = _mk_project(tmp_path, {
        "core.v": "module core(); endmodule\n",
        "pkg_types.sv": "package t; endpackage\n",
        "core_tb.v": "module core_tb(); endmodule\n",
        "assertions.sv": "module a(); endmodule\n",
        "de10lite_top.v": "module d(); endmodule\n",
        "host_emulator.v": "module h(); endmodule\n",
        "testbench.v": "module tb(); endmodule\n",
        "stimulus.v": "module s(); endmodule\n",
    })
    picked = [f.name for f in p3._synth_rtl_files(proj)]
    assert "core.v" in picked
    assert "pkg_types.sv" == picked[0], "package files must be read first"
    for excluded in ("core_tb.v", "assertions.sv", "de10lite_top.v",
                     "host_emulator.v", "testbench.v", "stimulus.v"):
        assert excluded not in picked, excluded


def test_fingerprint_covers_exactly_the_selector(tmp_path):
    proj = _mk_project(tmp_path, {
        "core.v": "module core(); endmodule\n",
        "core_tb.v": "module core_tb(); endmodule\n",
    })
    fp = p3._synth_inputs_fingerprint(proj, LIB_A)
    assert set(fp["rtl_sha256"]) == {f.name for f in p3._synth_rtl_files(proj)}
    # A testbench edit must NOT invalidate a silicon netlist.
    nl = _mk_netlist(proj)
    p3._write_synth_inputs_sidecar(proj, LIB_A)
    (_pl.rtl_dir(proj) / "core_tb.v").write_text("module core_tb(); reg x; endmodule\n")
    ok, _ = p3._synth_cache_valid_for(proj, nl, LIB_A)
    assert ok, "a testbench edit must not force a re-synth"


def test_sidecar_write_is_best_effort(tmp_path):
    """A sidecar that cannot be written must never fail a good synth."""
    proj = _mk_project(tmp_path, {"core.v": "module core(); endmodule\n"})
    sd = _pl.synth_dir(proj)
    side = sd / p3._SYNTH_INPUTS_SIDECAR
    side.mkdir()          # a directory where the file should go -> OSError
    p3._write_synth_inputs_sidecar(proj, LIB_A)   # must not raise


def test_fingerprint_is_deterministic(tmp_path):
    proj = _mk_project(tmp_path, {"a.v": "module a(); endmodule\n",
                                  "b.v": "module b(); endmodule\n"})
    assert (p3._synth_inputs_fingerprint(proj, LIB_A)
            == p3._synth_inputs_fingerprint(proj, LIB_A))


def test_new_code_is_chip_agnostic():
    src = Path(p3.__file__).read_text()
    start = src.index("_SYNTH_INPUTS_SIDECAR =")
    end = src.index("def step_synth(")
    body = src[start:end]
    banned = re.compile(
        r"\b(sky130\w*|gf180\w*|nangate\w*|freepdk\w*|asap7|ihp[-_]?sg13\w*|"
        r"skywater|globalfoundries|tsmc|edge_llm\w*|ibex|sha256sum)\b",
        re.IGNORECASE)
    hit = banned.search(body)
    assert hit is None, f"chip-specific literal: {hit.group(0)!r}"
