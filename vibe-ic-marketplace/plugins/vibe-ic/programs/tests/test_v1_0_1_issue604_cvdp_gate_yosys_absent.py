"""ORGANIC #604 — cvdp_gate must NOT silently degrade to PASS when the yosys
binary is entirely absent.

The synthesizability smoke (#531) ran `_run(["yosys", ...])` and, on any
non-zero rc, decided frontend-vs-synth purely by the absence of a SYNTH /
HIERARCHY pass header. When yosys is NOT installed, `_run` returns rc=127 with
a FileNotFoundError blob that contains neither header → the old code declared a
"frontend-gap", emitted "tolerated", and `continue`d for every module → the
record PASSed on iverilog alone with ZERO synth evidence (the exact silent
false-PASS #531 exists to catch).

POSITIVE (the bug): yosys-absent (rc=127, FileNotFoundError) must BLOCK with a
"cannot enforce" verdict, NEVER "frontend-gap tolerated".

NEGATIVE no-leak (the fix must not over-block): a REAL host-yosys frontend gap
— yosys actually started (banner present) then rejected SV the official 0.40
accepts — is STILL tolerated, preserving the field-accepted version-skew path.

chip-AGNOSTIC: synthetic blobs only; no benchmark/design specifics.
"""
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

_CODE = "module m;\n  reg a;\nendmodule\n"

# A FileNotFoundError blob exactly as _run emits it on a yosys-less host — note
# it CONTAINS the literal 'yosys' command name, which must NOT count as "yosys
# started".
_FNF_BLOB = "[Errno 2] No such file or directory: 'yosys'"

# A real frontend gap: yosys STARTED (banner) then errored in read_verilog,
# before any SYNTH / HIERARCHY pass header.
_FRONTEND_GAP_BLOB = (
    "\n Yosys 0.33 (git sha1 1234abcd)\n\n"
    "-- Running command `read_verilog -sv smoke.sv; synth -top m; stat' --\n"
    "ERROR: syntax error, unexpected TOK_PARAMETER near line 2\n"
)


def _patch_run(monkeypatch, rc, out, err):
    monkeypatch.setattr(G, "_run", lambda cmd, timeout=120: (rc, out, err))


def test_yosys_absent_rc127_blocks_not_tolerated(tmp_path, monkeypatch):
    """POSITIVE: yosys missing (rc=127) → BLOCK, never silently tolerated."""
    _patch_run(monkeypatch, 127, "", _FNF_BLOB)
    ok, why = G.yosys_smoke(_CODE, tmp_path)
    assert ok is False, f"yosys-absent must block, got ok={ok}: {why}"
    assert "frontend-gap tolerated" not in why, (
        f"yosys-absent must NOT be reported as a tolerated frontend-gap: {why}")
    assert ("CANNOT ENFORCE" in why) and ("#604" in why), (
        f"verdict must name the cannot-enforce / #604 cause: {why}")


def test_no_yosys_banner_also_blocks(tmp_path, monkeypatch):
    """Defense-in-depth: a non-127 error with NO yosys start banner (yosys
    never really ran) must also block, not slip through as a frontend-gap."""
    _patch_run(monkeypatch, 1, "", "some opaque error with no yosys banner")
    ok, why = G.yosys_smoke(_CODE, tmp_path)
    assert ok is False
    assert "frontend-gap tolerated" not in why
    assert "CANNOT ENFORCE" in why


def test_real_frontend_gap_still_tolerated(tmp_path, monkeypatch):
    """NEGATIVE no-leak: a genuine host-yosys frontend gap (banner present,
    no SYNTH/HIERARCHY pass) is STILL tolerated — the fix did not over-block
    the field-accepted version-skew path."""
    _patch_run(monkeypatch, 1, _FRONTEND_GAP_BLOB, "")
    ok, why = G.yosys_smoke(_CODE, tmp_path)
    assert ok is True, f"a real frontend-gap must stay tolerated, got: {why}"
    assert "frontend-gap tolerated" in why, why


def test_main_refuses_when_yosys_absent(tmp_path, monkeypatch):
    """The gate-startup guard mirrors the iverilog-absent refuse: yosys absent
    → main returns 2 (cannot enforce), so no ungated responses are emitted."""
    real_which = shutil.which

    def fake_which(name):
        if name == "yosys":
            return None
        if name == "iverilog":
            return real_which("iverilog") or "/usr/bin/iverilog"
        return real_which(name)

    monkeypatch.setattr(G.shutil, "which", fake_which)
    batch = tmp_path / "drafts.jsonl"
    batch.write_text("")  # empty is fine — guard runs before processing
    out = tmp_path / "gated.jsonl"
    rc = G.main(["--batch", str(batch), "--out", str(out)])
    assert rc == 2, f"yosys-absent must refuse (rc=2), got {rc}"
