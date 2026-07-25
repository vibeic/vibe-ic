"""The shipped GDS must be the GDS this run verified.

`step_canonicalize_artefacts` staged the canonical deliverable
`phase3/stage4/gds/<top>.gds` behind an EXISTENCE-only guard
(`if not canon_gds.is_file()`). On any resume / re-run / warm-started
tree that already carried a stage4 GDS the copy was skipped, so the
deliverable kept its old contents while the layout that DRC and LVS had
just signed off went only to `phase3/stage3/pnr/<top>.gds`.

Measured on the fleet (subservient x sky130A, plugin 1.5.50):

    phase3/stage4/gds/<top>.gds          3,067,904 B  03:25:56  <- SHIPPED
    phase3/stage3/pnr/<top>.gds         21,511,808 B  04:02:01  <- verified
    phase3/stage4/foundry_handoff/…gds  31,185,462 B  04:01:57

The shipped file was a page-aligned truncation carrying ZERO ENDLIB
records, 13 of the layout's 18 layers and ~8% of its elements. Every
size-based gate passed it, because at ~3 MB it cleared the 100 KB floor.

This module pins the freshness decision itself. It calls the runner's
real helper — deliberately NOT a mirrored copy of the logic, because a
mirror is exactly what lets emitter and checker drift apart again.
"""
import inspect
import os
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

_SRC = inspect.getsource(R.step_canonicalize_artefacts)


def _write(p: Path, data: bytes, mtime: float) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (mtime, mtime))
    return p


class TestStalenessDecision:
    def test_stale_canon_is_refreshed(self, tmp_path):
        """The exact fleet shape: canonical copy predates the stream-out."""
        canon = _write(tmp_path / "stage4" / "top.gds", b"\x00" * 3_067_904,
                       1_000_000)
        primary = _write(tmp_path / "pnr" / "top.gds", b"\x00" * 21_511_808,
                         1_002_000)
        assert R._canonical_gds_is_stale(primary, canon) is True

    def test_current_canon_is_left_alone(self, tmp_path):
        """A deliverable already at or after the stream-out is not rewritten."""
        primary = _write(tmp_path / "pnr" / "top.gds", b"A" * 100, 1_000_000)
        canon = _write(tmp_path / "stage4" / "top.gds", b"A" * 100, 1_000_000)
        assert R._canonical_gds_is_stale(primary, canon) is False

    def test_newer_canon_is_left_alone(self, tmp_path):
        """A later producer's artefact is never clobbered."""
        primary = _write(tmp_path / "pnr" / "top.gds", b"A" * 100, 1_000_000)
        canon = _write(tmp_path / "stage4" / "top.gds", b"B" * 100, 1_005_000)
        assert R._canonical_gds_is_stale(primary, canon) is False

    def test_absent_canon_is_not_a_staleness_decision(self, tmp_path):
        """First write is the plain copy path, not a refresh."""
        primary = _write(tmp_path / "pnr" / "top.gds", b"A" * 100, 1_000_000)
        assert R._canonical_gds_is_stale(
            primary, tmp_path / "stage4" / "top.gds") is False

    def test_unstattable_canon_is_treated_as_stale(self, tmp_path):
        """Refreshing is always safe here; keeping an unreadable artefact
        as the tape-out deliverable is not."""
        primary = _write(tmp_path / "pnr" / "top.gds", b"A" * 100, 1_000_000)
        canon = _write(tmp_path / "stage4" / "top.gds", b"B" * 100, 900_000)

        real_stat = Path.stat

        def boom(self, *a, **kw):
            if self == canon:
                raise OSError("simulated stat failure")
            return real_stat(self, *a, **kw)

        Path.stat = boom
        try:
            assert R._canonical_gds_is_stale(primary, canon) is True
        finally:
            Path.stat = real_stat


class TestGuardIsWiredIn:
    def test_existence_only_guard_is_gone(self):
        """The regression itself: the copy must not be gated on absence
        alone, or a resumed run ships an unverified artefact again."""
        assert "if not canon_gds.is_file():\n" not in _SRC

    def test_step_consults_the_shared_helper(self):
        """Emitter and checker share one decision site — no mirrored copy
        of the mtime comparison inside the step body."""
        assert "_canonical_gds_is_stale(primary_gds, canon_gds)" in _SRC
        assert "not canon_gds.is_file() or _stale" in _SRC
