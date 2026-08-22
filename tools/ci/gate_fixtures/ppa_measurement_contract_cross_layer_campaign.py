"""`PPA measurement contract (cross-layer campaign)` — the same contract, at the corpus this row names.

`ppa_contract_check.py` is wired three times, once per campaign corpus, and a
fixture must drive the gate AS THE DISPATCHER DECLARES IT: this row passes
`--corpus "$ROOT/ppa-crosslayer"`, so a subject carrying the contract anywhere else
leaves this gate reading an EMPTY corpus and answering about that.

The document is `ppa_measurement_contract`'s, imported rather than copied, and
through it the repository's own `_ppa.contract.build`. One producer, one
schema, three corpora — three hand-maintained copies would drift three ways.
"""
from pathlib import Path
import sys

# The loader imports fixtures BY PATH, so a sibling import does not resolve
# unless this directory is on `sys.path` first.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ppa_measurement_contract as _base  # noqa: E402

GATE = "PPA measurement contract (cross-layer campaign)"

#: Byte-for-byte the directory the cross-layer row passes to `--corpus`.
CORPUS = "ppa-crosslayer"


def can_pass(work: Path) -> Path:
    """A contract this gate must ACCEPT, placed where this row looks."""
    return _base.build_can_pass(work, CORPUS)


def can_fail(work: Path):
    """Its stated digest altered by one character — refused PPA-C-001, rc 1."""
    return _base.build_can_fail(work, CORPUS)
