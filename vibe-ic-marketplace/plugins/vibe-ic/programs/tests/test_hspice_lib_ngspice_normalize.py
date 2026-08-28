#!/usr/bin/env python3
"""tests/test_hspice_lib_ngspice_normalize.py

D1 test for the chip-AGNOSTIC HSPICE->ngspice model-lib normalizer
(hspice_lib_ngspice_normalize.py), floor G-ANALOG-SPICE F1.

The SYNTHETIC fixtures use FICTIONAL device / alias names (qzdev_*, wobble_*,
frobnitz_*) that appear in NO real PDK, proving the normalizer keys on directive
SYNTAX (`.malias`) and hardcodes nothing PDK-specific.

Two layers:
  * PURE-PYTHON tests (always run) — strip genericity, byte-identical NO-OP on an
    ngspice-native lib, transitive include/lib rewriting, section-vs-include
    disambiguation, and the capability probe.
  * ONE in-container FAIL->PASS test — reproduces ngspice exit!=0 +
    "Undefined parameter" on a synthetic `.malias` lib, then proves ngspice
    exit 0 on the normalized copy. SKIPS (never fails / never fakes a pass) when
    docker / ngspice / a writable verbatim bind-mount is unavailable (mirrors
    analog_real_corner_sweep's rc=2 unreachable fallback).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parent.parent
        / "hspice_lib_ngspice_normalize.py")


def _load():
    spec = importlib.util.spec_from_file_location(
        "hspice_lib_ngspice_normalize", PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


HLN = _load()


# ── synthetic fixtures (fictional names — in NO real PDK) ────────────────────

_SYNTH_MALIAS_LIB = """\
* synthetic HSPICE-style model lib — fictional device/alias names
.lib tt
.model qzdev_canon nmos level=1 vto=0.55 kp=42u
.model wobble_res r
.malias qzdev_canon = qzdev_esd_layoutcell
.malias qzdev_canon = qzdev_esd_iovariant
.malias wobble_res  = wobble_res_thickmetal
.endl tt
"""

_SYNTH_CLEAN_LIB = """\
* synthetic ngspice-native lib — no HSPICE-only directive at all
.lib tt
.model frobnitz_dev nmos level=1 vto=0.6 kp=50u
.endl tt
"""


def test_strip_malias_generic():
    """Every `.malias` line (regardless of the fictional names) is stripped;
    real model lines are preserved verbatim."""
    out, n = HLN.normalize_lib_text(_SYNTH_MALIAS_LIB)
    assert n == 3, f"expected 3 stripped .malias, got {n}"
    # No live `.malias` remains (only commented-out echoes).
    for ln in out.splitlines():
        assert not ln.lstrip().lower().startswith(".malias"), ln
    # Every fictional alias RHS is now inside a comment, never a live directive.
    assert "qzdev_esd_layoutcell" in out and "wobble_res_thickmetal" in out
    # Real model definitions survive.
    assert ".model qzdev_canon nmos" in out
    assert ".model wobble_res r" in out
    assert ".lib tt" in out and ".endl tt" in out


def test_contains_probe():
    assert HLN.contains_hspice_only_directive(_SYNTH_MALIAS_LIB) is True
    assert HLN.contains_hspice_only_directive(_SYNTH_CLEAN_LIB) is False


def test_noop_on_ngspice_native_lib(tmp_path):
    """A lib whose closure has NO HSPICE-only directive is a byte-identical
    NO-OP: changed=False and the ORIGINAL path is returned unchanged."""
    lib = tmp_path / "native.lib"
    lib.write_text(_SYNTH_CLEAN_LIB)
    stage = tmp_path / "stage"
    res = HLN.normalize_for_ngspice(lib, stage)
    assert res["changed"] is False
    assert Path(res["normalized_lib"]) == lib.resolve()
    assert res["directives_removed"] == 0
    # nothing staged
    assert not stage.exists() or not any(stage.iterdir())


def test_probe_closure(tmp_path):
    """include_closure_has_hspice_only follows .include into an offending file."""
    inc = tmp_path / "aliases.inc"
    inc.write_text(_SYNTH_MALIAS_LIB)
    top = tmp_path / "top.lib"
    top.write_text("* top\n.include 'aliases.inc'\n")
    assert HLN.include_closure_has_hspice_only(top) is True
    assert HLN.include_closure_has_hspice_only(inc) is True
    clean = tmp_path / "clean.lib"
    clean.write_text(_SYNTH_CLEAN_LIB)
    assert HLN.include_closure_has_hspice_only(clean) is False


def test_transitive_include_rewrite(tmp_path):
    """A top lib that .include's an OFFENDING file and .lib-references a CLEAN
    file: top + offending file are staged; the offending reference points at the
    stage-local basename; the clean reference is rewritten to a RELATIVE path
    that still resolves back to the ORIGINAL clean file."""
    pdk = tmp_path / "pdk"
    pdk.mkdir()
    (pdk / "aliases.inc").write_text(_SYNTH_MALIAS_LIB)
    (pdk / "models.lib").write_text(_SYNTH_CLEAN_LIB)
    top = pdk / "corner.lib"
    top.write_text(
        "* synthetic corner deck\n"
        ".lib tt\n"
        ".lib 'models.lib' tt\n"
        ".include 'aliases.inc'\n"
        ".endl tt\n"
    )
    stage = tmp_path / "phase3" / "analog" / "blk" / "_pdk_stage"
    res = HLN.normalize_for_ngspice(top, stage)
    assert res["changed"] is True
    # top + aliases staged (2); models.lib is clean -> NOT staged.
    staged = [Path(p).name for p in res["staged_files"]]
    assert len(res["staged_files"]) == 2, staged
    norm_top = Path(res["normalized_lib"])
    assert norm_top.parent == stage.resolve()
    top_txt = norm_top.read_text()
    # (a) offending include now points at a stage-local basename (no path sep).
    inc_lines = [l for l in top_txt.splitlines()
                 if l.lstrip().lower().startswith(".include")]
    assert len(inc_lines) == 1
    inc_target = inc_lines[0].split("'")[1]
    # stage-local basename (no path separator) that exists in the stage dir.
    assert os.sep not in inc_target and "/" not in inc_target
    assert (stage / inc_target).is_file()
    # the staged alias file has NO LIVE .malias (commented echoes are fine).
    for ln in (stage / inc_target).read_text().splitlines():
        assert not ln.lstrip().lower().startswith(".malias"), ln
    # (b) clean .lib reference rewritten to a RELATIVE path that resolves back to
    # the ORIGINAL models.lib (mount-scheme invariant — no absolute path).
    lib_file_lines = [l for l in top_txt.splitlines()
                      if l.lstrip().lower().startswith(".lib '")]
    assert len(lib_file_lines) == 1
    clean_target = lib_file_lines[0].split("'")[1]
    assert not os.path.isabs(clean_target)
    resolved = (stage / clean_target).resolve()
    assert resolved == (pdk / "models.lib").resolve()
    # (c) the one-arg section start `.lib tt` is preserved as a section, NOT
    # rewritten into a file include.
    assert any(l.strip() == ".lib tt" for l in top_txt.splitlines())


def test_section_start_not_treated_as_include(tmp_path):
    """`.lib tt` (one token) is a SECTION start, never a file reference."""
    refs = list(HLN._iter_references(".lib tt\n.lib 'models.lib' tt\n"
                                     ".include 'x.inc'\n"))
    kinds_files = [(k, f) for (k, _raw, f) in refs]
    assert ("lib", "models.lib") in kinds_files
    assert ("include", "x.inc") in kinds_files
    # `.lib tt` produced NO reference.
    assert all(f != "tt" for (_k, f) in kinds_files)


def test_no_chip_or_pdk_literal_in_program():
    """Belt-and-suspenders on the chip-AGNOSTIC invariant (the authoritative
    gate is source_chip_agnostic_check.py). The program source must not carry a
    real-PDK filename / vendor / node literal."""
    # NOTE: sky130 / gf180 are OPEN-PDK family names the plugin supports
    # everywhere (they are NOT chip-specific detection literals), so they are
    # allowed; the forbidden set is the commercial-chip / vendor / node literals.
    src = PROG.read_text().lower()
    # The commercial NDA tokens are reconstructed from the encoded store so this
    # test carries no literal SKU; "hawaii" is an extra private-source token.
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import _commercial_pdk as _cpdk  # noqa: E402
    for bad in [t.lower() for t in _cpdk.nda_tokens()] + ["hawaii"]:
        assert bad not in src, f"forbidden literal {bad!r} in normalizer source"


# ── in-container FAIL->PASS (skip-not-fail) ──────────────────────────────────

def _verbatim_container():
    """Return (container_name, host_dir Path) for a RUNNING container that:
      * exposes ngspice, and
      * has a WRITABLE bind-mount whose Source == Destination (verbatim), so a
        host path is valid inside the container unchanged.
    Returns None when nothing suitable exists -> caller SKIPS."""
    if not shutil.which("docker"):
        return None
    try:
        names = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30).stdout.split()
    except Exception:
        return None
    for name in names:
        try:
            mounts = subprocess.run(
                ["docker", "inspect", name, "--format",
                 "{{range .Mounts}}{{.Source}}::{{.Destination}}::{{.RW}}\n{{end}}"],
                capture_output=True, text=True, timeout=30).stdout
        except Exception:
            continue
        # ngspice present?
        probe = _pr.run(
            ["docker", "exec", name, "bash", "-lc",
             "command -v ngspice || ls /foss/tools/*/bin/ngspice 2>/dev/null "
             "| head -1"], capture_output=True, text=True)
        ng = ""
        for line in (probe.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("/") and "ngspice" in line:
                ng = line
                break
        if not ng:
            continue
        for row in mounts.splitlines():
            parts = row.split("::")
            if len(parts) != 3:
                continue
            src, dst, rw = parts
            if src and src == dst and rw == "true" and os.access(src, os.W_OK):
                return name, Path(src), ng
    return None


def test_ngspice_fail_to_pass_incontainer(tmp_path):
    env = _verbatim_container()
    if env is None:
        pytest.skip("no running container with ngspice + writable verbatim "
                    "bind-mount — in-container FAIL->PASS not exercised here")
    container, host_root, ngspice = env
    # Work inside the verbatim mount so the same absolute path is valid in the
    # container. Use a private subdir; clean up after.
    work = host_root / ".vibeic_hln_test"
    work.mkdir(parents=True, exist_ok=True)
    try:
        lib = work / "syn_models.lib"
        lib.write_text(_SYNTH_MALIAS_LIB)
        before = work / "before.sp"
        before.write_text(
            f".lib '{lib}' tt\n"
            "v1 a 0 1\n"
            "r1 a 0 wobble_res r=1k\n"
            ".control\nop\nprint v(a)\n.endc\n.end\n")

        def _run(sp):
            cp = _pr.run(
                ["docker", "exec", container, "bash", "-lc",
                 f"{ngspice} -b {sp} 2>&1; echo RC=$?"],
                capture_output=True, text=True)
            out = cp.stdout
            rc = 999
            for line in out.splitlines():
                if line.startswith("RC="):
                    rc = int(line[3:])
            undef = sum("undefined parameter" in l.lower()
                        for l in out.splitlines())
            return rc, undef, out

        # BEFORE — native synthetic lib fails on `.malias`.
        b_rc, b_undef, b_out = _run(before)
        assert b_rc != 0, f"expected native .malias lib to FAIL:\n{b_out[-800:]}"
        assert b_undef >= 1, f"expected Undefined-parameter error:\n{b_out[-800:]}"

        # Normalize (pure python) then AFTER — normalized lib runs clean.
        stage = work / "stage"
        if stage.exists():
            shutil.rmtree(stage)
        res = HLN.normalize_for_ngspice(lib, stage)
        assert res["changed"] is True
        norm = res["normalized_lib"]
        after = work / "after.sp"
        after.write_text(
            f".lib '{norm}' tt\n"
            "v1 a 0 1\n"
            "r1 a 0 wobble_res r=1k\n"
            ".control\nop\nprint v(a)\n.endc\n.end\n")
        a_rc, a_undef, a_out = _run(after)
        assert a_rc == 0, f"expected normalized lib to run clean:\n{a_out[-800:]}"
        assert a_undef == 0, f"expected 0 undefined-parameter:\n{a_out[-800:]}"
        # a real op solved v(a)=1V through the 1k resistor.
        assert "v(a)" in a_out.lower()
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
