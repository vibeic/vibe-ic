"""`PPA head-to-head records (end-to-end campaign)` — the same record, at the corpus this row names.

THE SAME CHECKER IS WIRED THREE TIMES, once per campaign corpus
(`benchmark-data`, `ppa-crosslayer`, `ppa-e2e`), and a fixture must drive the
gate AS THE DISPATCHER DECLARES IT — the declaration for this row passes
`--corpus "$ROOT/docs/campaigns/ppa-e2e"`, so a subject carrying the record anywhere else
would leave this gate reading an EMPTY corpus and answering about that instead
of about the record.

The record itself is `ppa_head_to_head_records`'s, imported rather than copied.
That is deliberate: the original fixture went dark because its record drifted
five schema generations behind the checker, and three independent copies would
have drifted three separate ways. One schema, three corpora.
"""
from pathlib import Path
import sys

# The fixture loader imports these modules BY PATH, so a sibling import is not
# resolvable unless this directory is on `sys.path` first — importable as a
# script is not the same as importable the way the loader loads it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
# `gate_mutation_fixtures` lives one directory up; the loader imports this
# module BY PATH, so the parent is not on `sys.path` unless it is put there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402
import ppa_head_to_head_records as _base  # noqa: E402

GATE = "PPA head-to-head records (end-to-end campaign)"

#: Byte-for-byte the directory the end-to-end row passes to `--corpus`.
#: ASKED OF THE ROW, NEVER RE-TYPED (vibe-ic#2019 fallout). The campaign trees
#: moved to `docs/campaigns/` and this literal did not follow, so the subject
#: was built where the gate no longer looks and the CAN-PASS arm was rejected
#: rc 2 "no corpus at …". `declared_subject_path` reads the `--corpus` this row
#: actually passes, so the fixture and its row cannot disagree.
_TAIL = "ppa-e2e"


def _corpus() -> str:
    """This row's corpus path, from the row.

    Resolved lazily: a missing row must fail THIS fixture, not the census that
    imports every fixture module.
    """
    return F.declared_subject_path(GATE, _TAIL)



def can_pass(work: Path) -> Path:
    """A record this gate must ACCEPT, placed where this row looks."""
    return _base.build_can_pass(work, _corpus())


def can_fail(work: Path):
    """The same record with the opponent tuned by us — refused rc 1, not rc 2."""
    return _base.build_can_fail(work, _corpus())
