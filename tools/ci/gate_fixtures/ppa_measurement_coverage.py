"""`PPA measurement coverage` — an expected measurement with no record at all.

THE DENOMINATOR IS THE POINT. Coverage computed from the records alone can only
ever be 100%, because the rows it would report missing are exactly the rows that
are not there to iterate over — the checker says so itself and refuses a bundle
that declares no `expected` list. So the subject carries the denominator WITH
the records, which is what `_ppa.metrics.bundle` exists to produce.

THE MUTATION REMOVES ONE RECORD AND LEAVES THE EXPECTATION STANDING. Two
(metric, scope) pairs are expected; the CAN-PASS answers both, the CAN-FAIL
answers one. That is the defect this gate exists to catch: a report of the
remaining rows asserts nothing about the missing one, and a coverage gap becomes
an implied zero.

A PARTIAL gap rather than an empty record set, deliberately. An empty numerator
would still refuse here, but it is one edit away from looking like the vacuous
corpus every other gate in this family treats as "nothing was validated" — and a
fixture whose failure could be mistaken for an empty population is a fixture that
stops proving what it claims. One record present and one absent cannot be read
that way.

The bundle is built by the repository's own producer and its schema ids are read
from `_ppa.metrics` rather than typed, so a schema rename reaches this fixture
instead of sending it dark.

The records are SYNTHETIC. No PPA run stands behind them; the numbers describe
no design. chip-AGNOSTIC / PDK-AGNOSTIC: the scope names a stage and nothing
else, and no process, foundry, tool or product is named.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                       / "programs"))
from _ppa import metrics as M  # noqa: E402

GATE = "PPA measurement coverage"

#: Byte-for-byte the path this row passes to `--coverage`. The declaration names
#: a FILE and not a corpus directory, so the subject has to carry exactly this
#: path: anywhere else and the gate reads nothing and answers about that.
#: ASKED OF THE ROW, NEVER RE-TYPED (vibe-ic#2019 fallout). The campaign trees
#: moved to `docs/campaigns/` and this literal did not follow, so the subject
#: was built where the gate no longer looks and the CAN-PASS arm was rejected
#: rc 2 "no corpus at …". Spelling the new prefix here would buy exactly one
#: more move. `declared_subject_path` reads the `--corpus`/argument this row
#: actually passes, so the fixture and its row cannot disagree.
_BUNDLE_TAIL = "ppa-crosslayer/records/trials/b000/records_flat.json"


def _bundle_rel() -> str:
    """Resolved lazily: a missing row must fail THIS fixture, not the census
    that imports every fixture module."""
    return F.declared_subject_path(GATE, _BUNDLE_TAIL)

#: Two (metric, scope) pairs. The CAN-PASS records both; the CAN-FAIL records
#: only the first and leaves the second expected and unanswered.
_PAIRS = (
    ("area.die.um2", {"stage": "floorplan"}, 1000.0),
    ("area.die.um2", {"stage": "post_route"}, 1100.0),
)


def _record(metric: str, scope: dict, value: float) -> dict:
    """One canonical metric record. `status: MEASURED` REQUIRES a `value` — the
    checker refuses NO_VALUE otherwise, and a status that claims a measurement
    while carrying no number is the invented-number shape this family refuses
    everywhere."""
    return {
        "schema": M.SCHEMA_ID,
        "metric": metric,
        "status": "MEASURED",
        "unit": "um^2",
        "value": value,
        "scope": dict(scope),
        "source": {"path": "reports/synthetic.log",
                   "sha256": "sha256:" + "0" * 64,
                   "tool": "synthetic", "parser": "synthetic"},
    }


def _bundle(records_kept: int) -> dict:
    index = M.MetricIndex()
    for metric, scope, value in _PAIRS[:records_kept]:
        index.add(_record(metric, scope, value))
    # `expected` is ALWAYS both pairs — that is what makes the missing one
    # visible instead of silently shrinking the denominator to match.
    return M.bundle(index, expected=[{"metric": m, "scope": dict(s)}
                                     for m, s, _ in _PAIRS])


def _tree(work: Path, records_kept: int) -> Path:
    root = F.git_init(work / "subject")
    p = root / _bundle_rel()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_bundle(records_kept), indent=2, sort_keys=True)
                 + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Every expected measurement answered: 2 expected, 2 covered, rc 0."""
    root = _tree(work, len(_PAIRS))
    F.git_commit(root)
    return root


def can_fail(work: Path):
    """One expectation left with no record: 2 expected, 1 covered, 1 ABSENT."""
    root = _tree(work, len(_PAIRS) - 1)
    F.git_commit(root)
    # The token must appear in the refusal, which is how the pair test knows the
    # gate refused for THIS mutation rather than by coincidence.
    return root, "NO RECORD AT ALL"
