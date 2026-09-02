"""`PPA ablation records (within-project)` — an arm this project did not tune.

WHAT THE TWO DOCUMENT KINDS MEAN, because the mutation is exactly the seam
between them. `vibeic.ppa.comparison.v2` is a HEAD-TO-HEAD: its whole claim is a
win over an opponent, so it REQUIRES a baseline arm declaring
`tuned_by_this_project: false`, and `ppa_head_to_head_check` then applies the
fairness conditions to it — the opponent gets its tuning budget, the stages
match, the corners match. `vibeic.ppa.ablation.v1` is a WITHIN-PROJECT
ABLATION: every arm is a configuration this project chose, so it requires EVERY
arm to declare `true`, and none of the fairness conditions apply because there
is no opponent to be fair to.

THE MUTATION IS ONE BOOLEAN. The record keeps its kind, its `claim_scope`, both
arms, both `ppa` blocks and every number. One arm stops declaring
`tuned_by_this_project: true`.

THAT IS THE DEFECT WORTH PINNING, and the checker names it separately from the
other schema violations for the same reason: a document holding an untuned arm
IS a head-to-head, and filing it here is how a comparison ESCAPES the fairness
conditions. It is the one mis-filing that makes a weaker claim look like a
stronger one, and from the outside the file still reads as a legitimate
measurement.

WHY NOT `minItems` (one arm instead of two). It refuses too, but it refuses as
a shape error that any reader spots; nobody ever shipped a one-armed ablation
believing it. The boolean is the one that ships.

THE RECORD IS SYNTHETIC and says so. No ablation stands behind these numbers and
none is implied — the real one in this repository is
`ppa-crosslayer/records/ablations/ablation_pnr_only_vs_crosslayer.json`, and a
fixture must never be mistaken for evidence.

chip-AGNOSTIC / PDK-AGNOSTIC: no process, foundry, vendor, tool or product is
named; the arms are identified by the LAYER a search was allowed to move at,
which is the thing this kind of document isolates.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "PPA ablation records (within-project)"

#: The declaration passes `--corpus "$ROOT/docs/campaigns/ppa-crosslayer"`, so the document has
#: to sit under that directory or the gate reads an absent corpus and answers
#: about THAT instead of about this record.
#: ASKED OF THE ROW, NEVER RE-TYPED (vibe-ic#2019 fallout). The campaign trees
#: moved to `docs/campaigns/` and this literal did not follow, so the subject
#: was built where the gate no longer looks and the CAN-PASS arm was rejected
#: rc 2 "no corpus at …". Spelling the new prefix here would buy exactly one
#: more move. `declared_subject_path` reads the `--corpus`/argument this row
#: actually passes, so the fixture and its row cannot disagree.
#: THE ROW NAMES A DIRECTORY, THE FIXTURE OWNS WHAT SITS UNDER IT. This row
#: passes `--corpus <dir>`, not a file, so only the dir half may be asked of
#: it; `records/ablations/` is this fixture's own choice of where a within-
#: project ablation is filed, and the gate selects on the DOCUMENT rather than
#: on the path, so nothing downstream depends on the sub-path being any
#: particular string.
_CORPUS_TAIL = "ppa-crosslayer"
_UNDER = "records/ablations/fixture_ablation.json"


def _rel() -> str:
    """Resolved lazily: a missing row must fail THIS fixture, not the census
    that imports every fixture module."""
    return f"{F.declared_subject_path(GATE, _CORPUS_TAIL)}/{_UNDER}"


def _arm(flow: str, role: str, area: float, *, tuned: bool) -> dict:
    return {
        "flow": flow,
        "role": role,
        "config_source": "synthetic fixture — no run stands behind this",
        "tuned_by_this_project": tuned,
        "measurement_basis": "post_route_sta",
        "ppa": {
            "area_um2": area,
            "worst_slack_ns": 0.10,
            "total_power_mw": 1.0,
        },
    }


def _document(*, both_tuned: bool) -> dict:
    return {
        "schema": "vibeic.ppa.ablation.v1",
        "claim_scope": "within_project",
        "isolates": ("what a search allowed to move above the place-and-route "
                     "layer adds over one confined to it — synthetic"),
        "synthetic": True,
        "arms": [
            _arm("fixture-pnr-only", "ablated", 1000.0, tuned=True),
            _arm("fixture-cross-layer", "full", 900.0, tuned=both_tuned),
        ],
    }


def _tree(work: Path, name: str, *, both_tuned: bool) -> Path:
    root = F.git_init(work / name)
    p = root / _rel()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_document(both_tuned=both_tuned), indent=1,
                            ensure_ascii=False) + "\n", encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Two arms, both this project's own: a legitimate within-project ablation."""
    return _tree(work, "subject_pass", both_tuned=True)


def can_fail(work: Path):
    """One arm declares it was NOT tuned here — that document is a head-to-head."""
    root = _tree(work, "subject_fail", both_tuned=False)
    return root, "tuned_by_this_project"
