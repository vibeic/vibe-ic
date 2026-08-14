"""An ABSENT iverilog must not be reported as an elaboration diagnostic.

`_run` returns the sentinel `(127, "", <FileNotFoundError text>)` when the
binary is missing. `iverilog_gate` used to let that fall through to

    return True, "elaboration-only tolerated diagnostics", ""

— a sentence asserting that elaboration RAN and produced only benign messages.
The consequence is not cosmetic: the gate becomes a NO-OP that returns ok=True
for input that is not Verilog at all, while the record reads clean. That is the
same silent false-PASS class `yosys_smoke` already refuses in this very file
("yosys-smoke CANNOT ENFORCE on module …: yosys did not run (rc=127; no yosys
start banner) … Refusing to tolerate as a frontend-gap (#604)").

A check that COULD NOT RUN and a check that found nothing wrong are not the
same result.

Host-independent by construction: tool absence is injected by patching `_run`
to its own documented rc=127 sentinel, so these run identically on a host that
has iverilog and on one that does not.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import cvdp_gate as G  # noqa: E402

# Not Verilog under any reading — the strongest possible witness that the gate
# is enforcing nothing when it answers ok=True.
_NOT_VERILOG = "!!! this is not verilog at all @@@ ###"
_BROKEN = "module b(input a output y); assign y = ; endmodul"
_GOOD = "module g(input a, output y); assign y = a; endmodule"

_ABSENT = (127, "", "[Errno 2] No such file or directory: 'iverilog'")


def _with_absent_iverilog(monkeypatch):
    """Make every _run look like the binary is missing, via the documented
    sentinel `_run` itself produces from FileNotFoundError."""
    monkeypatch.setattr(G, "_run", lambda *a, **k: _ABSENT)


def test_absent_iverilog_does_not_pass_arbitrary_text(tmp_path, monkeypatch):
    _with_absent_iverilog(monkeypatch)
    ok, msg, _ = G.iverilog_gate(_NOT_VERILOG, tmp_path)
    assert ok is False, (
        "iverilog is absent, so nothing was compiled — text that is not "
        f"Verilog at all must not come back ok=True. Got: {msg!r}")


def test_absent_iverilog_is_not_described_as_elaboration(tmp_path, monkeypatch):
    # The MESSAGE is load-bearing: it is what a human reads in the record. It
    # must not claim elaboration happened when the compiler never ran.
    _with_absent_iverilog(monkeypatch)
    _ok, msg, _ = G.iverilog_gate(_GOOD, tmp_path)
    assert "elaboration-only tolerated diagnostics" not in msg, msg
    assert "iverilog" in msg.lower()
    # and it must say, in words, that it could not enforce
    assert "CANNOT ENFORCE" in msg, msg


def test_absent_iverilog_reads_differently_from_a_real_rejection(tmp_path,
                                                                monkeypatch):
    # The whole point: "the tool is missing" and "the tool ran and rejected
    # this RTL" must be DISTINGUISHABLE, not folded into one answer.
    _with_absent_iverilog(monkeypatch)
    ok_absent, msg_absent, _ = G.iverilog_gate(_BROKEN, tmp_path)

    monkeypatch.setattr(
        G, "_run",
        lambda *a, **k: (1, "", "gate.sv:1: syntax error\ngate.sv:1: Errors."))
    ok_rejected, msg_rejected, _ = G.iverilog_gate(_BROKEN, tmp_path)

    assert ok_rejected is False          # a real rejection stays a rejection
    # NEITHER is a pass — the absent tool must not be the MORE PERMISSIVE of
    # the two. (Comparing only the messages would not bind anything: before the
    # fix the two strings already differed, while the verdicts were opposite.)
    assert ok_absent is False, msg_absent
    # …and they must still be told apart by what they SAY, so a reader can act
    # on the difference (install a compiler vs. re-author the RTL).
    assert msg_absent != msg_rejected
    assert "CANNOT ENFORCE" in msg_absent
    assert "CANNOT ENFORCE" not in msg_rejected


def test_a_present_iverilog_still_tolerates_benign_diagnostics(tmp_path,
                                                              monkeypatch):
    # PAIRED GUARD, the direction that keeps the fix from being an
    # over-correction: when iverilog REALLY RAN (rc != 0, rc != 127) and the
    # diagnostics are the benign kind, the existing tolerance must survive.
    # A fix that made every non-zero rc a hard failure would pass the three
    # tests above and silently break the tolerated-diagnostics path.
    monkeypatch.setattr(G, "_run",
                        lambda *a, **k: (1, "", "gate.sv:1: warning: benign"))
    ok, msg, _ = G.iverilog_gate(_GOOD, tmp_path)
    assert ok is True, msg
    assert "CANNOT ENFORCE" not in msg, msg
