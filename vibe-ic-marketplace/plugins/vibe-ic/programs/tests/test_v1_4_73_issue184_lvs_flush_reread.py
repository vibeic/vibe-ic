"""v1.4.73 — #184: phase3 LVS `_read_lvs_report_flushed` gave up on the
overlayfs flush microseconds before the terminal `Final result:` verdict
landed, stamping a netgen rc=0 clean MATCH as INCOMPLETE / LVS_NO_TERMINAL_VERDICT
on 6/6 digital ICs @ v1.4.67.

Two chip-AGNOSTIC hardenings, both fail-safe (a genuinely-absent completion
marker still classifies INCOMPLETE — the marker is the sole gate):

  (1) ONE FINAL RE-READ after the bounded poll loop exits — the loop returns
      the LAST content it read, which is the pre-flush (empty) text when the
      flush lands in the sleep window right before the deadline break. The
      re-read catches a report that flushed during that final wait.

  (2) `rc == 0` SCALES the budget — a clean netgen exit means the verdict WILL
      arrive; only the flush is pending. Waiting longer cannot mask a genuine
      kill (a killed run has rc != 0, or never emits the marker). A non-zero /
      unknown rc keeps the tight budget so a real failure fails fast.

Each test reproduces the exact race and FAILS against the pre-#184 form.
Chip-AGNOSTIC: pure file-I/O timing, no design/PDK literal.
"""
import sys
import time
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402
import lvs_verdict_tokens as _lvt  # noqa: E402

_VERDICT = (
    "Subcircuit summary:\n"
    "Circuit 1: sha256          Circuit 2: sha256\n"
    "Final result: Circuits match uniquely.\n"
)


class _CountLaggingReport:
    """Report path whose content flushes only AFTER `reads_until_flush` reads —
    models the flush landing between the loop's last read and the return."""

    def __init__(self, reads_until_flush: int, final_text: str = _VERDICT):
        self._n = 0
        self._until = reads_until_flush
        self._final = final_text

    def is_file(self) -> bool:
        return True

    def read_text(self, *a, **k) -> str:
        self._n += 1
        return self._final if self._n > self._until else ""


class _TimedLaggingReport:
    """Report path whose content becomes visible only after `flush_after`
    wall-clock seconds — models a real overlayfs flush that lands at an instant
    independent of read count."""

    def __init__(self, flush_after: float, final_text: str = _VERDICT):
        self._t0 = time.time()
        self._after = flush_after
        self._final = final_text

    def is_file(self) -> bool:
        return True

    def read_text(self, *a, **k) -> str:
        return self._final if (time.time() - self._t0) >= self._after else ""


# ── (2) final re-read catches a flush landed during the last wait window ──

def test_final_reread_catches_late_flush():
    # max_wait=0 → the loop reads once (empty), the deadline is already past so
    # it breaks; the flush lands on the NEXT read. Pre-#184 the loop returned
    # the empty `txt` → INCOMPLETE. The final re-read now returns the verdict.
    rpt = _CountLaggingReport(reads_until_flush=1)
    txt = R._read_lvs_report_flushed(rpt, max_wait=0.0, base_delay=0.0)
    assert _lvt.has_terminal_verdict(txt)
    assert _lvt.classify(txt) == "MATCH"


# ── (1) rc==0 scales the budget past a genuinely-late flush ──

def test_clean_exit_rc0_budget_outlasts_late_flush():
    # The verdict only appears at ~0.35 s of wall clock. A TIGHT budget (rc=1,
    # max_wait=0.03) — even WITH the final re-read — reads empty at ~0.03 s and
    # stamps INCOMPLETE. A CLEAN exit (rc=0) scales the budget and polls long
    # enough to see the flush → MATCH. This proves the rc scaling is
    # load-bearing, not subsumed by the final re-read.
    tight = _TimedLaggingReport(flush_after=0.35)
    txt_tight = R._read_lvs_report_flushed(
        tight, max_wait=0.03, base_delay=0.01, rc=1)
    assert not _lvt.has_terminal_verdict(txt_tight)

    scaled = _TimedLaggingReport(flush_after=0.35)
    txt_scaled = R._read_lvs_report_flushed(
        scaled, max_wait=0.03, base_delay=0.02, rc=0,
        clean_exit_max_wait=1.2, clean_exit_attempts=60)
    assert _lvt.has_terminal_verdict(txt_scaled)
    assert _lvt.classify(txt_scaled) == "MATCH"


# ── fail-safe: a genuinely-absent marker stays INCOMPLETE even on rc==0 ──

def test_genuine_incomplete_stays_incomplete_even_on_clean_exit():
    truncated = "Flattening unmatched subcell ...\n"  # no Final result: line

    class _NeverFlushes:
        def is_file(self):
            return True

        def read_text(self, *a, **k):
            return truncated

    txt = R._read_lvs_report_flushed(
        _NeverFlushes(), max_wait=0.02, base_delay=0.0, rc=0,
        clean_exit_max_wait=0.05, clean_exit_attempts=4)
    assert not _lvt.has_terminal_verdict(txt)
    assert _lvt.classify(txt) != "MATCH"
