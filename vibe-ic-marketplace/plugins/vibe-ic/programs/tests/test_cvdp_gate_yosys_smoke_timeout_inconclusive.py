"""cvdp_gate yosys-smoke: a `synth` TIMEOUT (rc=124) is INCONCLUSIVE, not the
#604 "yosys absent" case.

The #531 synthesizability smoke runs a full `synth` with a 300s budget. On a
host where yosys IS present and the design already ELABORATED under the iverilog
gate, `synth` can still exceed the budget (observed on a 44-line parameterized
barrel_shifter and a binary-search-tree sorter: `iverilog -g2012` parses in <1s,
`synth` does not converge in 300s). `_run` returns rc=124 with an EMPTY blob on
TimeoutExpired, so the #604 "no yosys start banner" guard misclassified the
timeout as "yosys did not run" and BLOCKED — DROPPING a design the official CVDP
scorer (cocotb + iverilog, which NEVER runs yosys) would have scored.

POSITIVE (the fix): rc=124 with yosys present → tolerate as INCONCLUSIVE (emit
with an advisory synth note), never a "CANNOT ENFORCE" block.

NEGATIVE no-leak:
  (a) #604 preserved — yosys ABSENT (rc=127) still BLOCKS; and a rc=124 with
      yosys NOT on PATH (shutil.which None) also still BLOCKS (the timeout
      tolerance can never silently cover an absent yosys).
  (b) a REAL synth-stage ERROR (yosys ran, banner present, rc!=124) still BLOCKS
      — the fix did not weaken real-error detection.

chip-AGNOSTIC: synthetic blobs / a tiny synthetic module; no design specifics.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

_CODE = "module m;\n  reg a;\nendmodule\n"

# A real synth-stage error: yosys STARTED (banner) and reached a SYNTH/HIERARCHY
# pass, then errored on a non-constant async reset (the scrambler class) — NOT a
# frontend gap, NOT a latch ERROR, NOT an unknown CONTEXT module.
_REAL_SYNTH_ERROR_BLOB = (
    "\n Yosys 0.40 (git sha1 deadbeef)\n\n"
    "-- Running command `read_verilog -sv smoke.sv; synth -top m; stat' --\n"
    "2. Executing SYNTH pass.\n"
    "2.2.5. Executing PROC_ARST pass (detect async resets in processes).\n"
    "ERROR: Async reset \\rst_n yields non-constant value for signal \\lfsr.\n"
)


def _patch_run(monkeypatch, rc, out, err):
    monkeypatch.setattr(G, "_run", lambda cmd, timeout=120: (rc, out, err))


def _patch_which(monkeypatch, yosys_path):
    import shutil as _sh
    real = _sh.which

    def fake(name):
        if name == "yosys":
            return yosys_path
        return real(name)

    monkeypatch.setattr(G.shutil, "which", fake)


def test_synth_timeout_with_yosys_present_is_inconclusive_not_block(
        tmp_path, monkeypatch):
    """POSITIVE: rc=124 (timeout) + yosys present + a POSITIVELY non-synth-scored
    problem (`synth_scored=False`) → tolerate as INCONCLUSIVE. (Gatekeeper PR #29
    remediation: the tolerance is category-aware — `synth_scored=False` is the
    confirmed cocotb/iverilog functional case; UNKNOWN / synth-scored fail-safe
    BLOCK — see test_v1_1_34_pr29_*.)"""
    _patch_run(monkeypatch, 124, "", "timeout")
    _patch_which(monkeypatch, "/usr/bin/yosys")
    ok, why = G.yosys_smoke(_CODE, tmp_path, synth_scored=False)
    assert ok is True, f"a non-synth-scored synth timeout must NOT block: {why}"
    assert "INCONCLUSIVE" in why, why
    assert "CANNOT ENFORCE" not in why, (
        f"a timeout must not be reported as the #604 absent-yosys block: {why}")


def test_synth_timeout_with_yosys_absent_still_blocks(tmp_path, monkeypatch):
    """NEGATIVE no-leak (a): rc=124 but yosys NOT on PATH → still BLOCK (the
    timeout tolerance can never silently cover an absent yosys)."""
    _patch_run(monkeypatch, 124, "", "timeout")
    _patch_which(monkeypatch, None)
    ok, why = G.yosys_smoke(_CODE, tmp_path)
    assert ok is False, f"timeout with yosys absent must block: {why}"
    assert "CANNOT ENFORCE" in why and "#604" in why, why


def test_yosys_absent_rc127_still_blocks(tmp_path, monkeypatch):
    """NEGATIVE no-leak (a, #604 preserved): yosys missing (rc=127) → BLOCK."""
    _patch_run(monkeypatch, 127, "", "[Errno 2] No such file or directory: 'yosys'")
    ok, why = G.yosys_smoke(_CODE, tmp_path)
    assert ok is False
    assert "CANNOT ENFORCE" in why and "#604" in why, why


def test_real_synth_error_still_blocks(tmp_path, monkeypatch):
    """NEGATIVE no-leak (b): a real synth-stage ERROR (banner present, rc!=124)
    still BLOCKS — the timeout tolerance did not weaken real-error detection."""
    _patch_run(monkeypatch, 1, _REAL_SYNTH_ERROR_BLOB, "")
    _patch_which(monkeypatch, "/usr/bin/yosys")
    ok, why = G.yosys_smoke(_CODE, tmp_path)
    assert ok is False, f"a real synth error must still block: {why}"
    assert "yosys-smoke failed" in why and "INCONCLUSIVE" not in why, why
