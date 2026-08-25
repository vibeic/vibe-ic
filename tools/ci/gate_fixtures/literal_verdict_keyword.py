"""`literal verdict keyword` - a measurement that is a Python literal.

THE MUTATION IS THE OTHER HALF OF THE SAME ESCAPE. A CHANGELOG stated "IR static
peak 5.231 mV"; the number was a literal assigned inside the emitter, and no
measurement produced it. A hardcoded sign-off numeric passes every keyword scan
while the emitter does zero real work.

can_pass assigns the value from the emitter's own parameter and carries the
`# source:` justification the gate reads. can_fail assigns the literal 5.231 and
drops the marker. One assignment differs; the population does not.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "literal verdict keyword"


def _tree(work: Path, emitter: str) -> Path:
    """A minimal plugin subject: one `programs/` holding one emitter. BOTH ARMS
    SHIP THE SAME ONE FILE with the same one `emit_*` function, so the
    denominator the gate walks is 1 either way and the red arm is red because an
    ANSWER changed, never because the corpus vanished."""
    root = F.git_init(work / "subject")
    programs = root / "programs"
    programs.mkdir(parents=True)
    (programs / "_signoff_emit.py").write_text(emitter, encoding="utf-8")
    F.git_commit(root)
    return root


_HONEST = '"""A synthetic sign-off emitter."""\n\n\ndef emit_ir_drop_report(measured_mv):\n    # source: the OpenROAD IR report parsed at runtime by _read_ir_rpt().\n    peak_mv = measured_mv\n    return {"verdict": "PASS", "ir_static_peak_mv": peak_mv}\n'

_FABRICATED = '"""A synthetic sign-off emitter."""\n\n\ndef emit_ir_drop_report(measured_mv):\n    peak_mv = 5.231\n    return {"verdict": "PASS", "ir_static_peak_mv": peak_mv}\n'


def can_pass(work: Path) -> Path:
    """The emitter refuses when it cannot measure."""
    return _tree(work, _HONEST)


def can_fail(work: Path):
    """The same emitter, now reporting a verdict it did not earn."""
    return _tree(work, _FABRICATED), "literal"
