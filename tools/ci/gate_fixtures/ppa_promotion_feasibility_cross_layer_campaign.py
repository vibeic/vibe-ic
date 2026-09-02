"""`PPA promotion feasibility (cross-layer campaign)` — one axis violated.

THE RECORD SET IS GENERATED FROM `_ppa.feasibility.DEFAULT_AXES`, not typed.
Every axis the checker requires declares its own `groups` of alternative
requirements, each with a `kind` — `slack_nonneg`, `count_zero`, `verdict_in`,
`limit_max`, `limit_min` — and this fixture emits one satisfying record per
requirement in the first group of each axis. An axis added to the checker
tomorrow is therefore answered here automatically, instead of appearing as a
MISSING metric and sending the fixture dark. Measured while writing it: a
hand-written set naming one axis produced six `MISSING ... [NO_RECORD]` lines for
axes it had never heard of.

THE MUTATION VIOLATES EXACTLY ONE AXIS. `physical.drc.violations` is a
`count_zero` requirement, so moving it from 0 to a positive count is a real
violation of a real requirement and nothing else changes: the candidate stays
complete, every other axis stays satisfied, and the verdict moves FEASIBLE ->
INFEASIBLE with the axis named. A missing metric would also have failed, but as
UNDETERMINED — the gate noticing it could not look, which proves nothing about
whether it can refuse.

`eco_readiness` reports NOT_APPLICABLE here and that is correct rather than
convenient: no design-for-ECO requirement is declared and no `--project` is
given, so the route this design took was never established and the run makes no
ECO-readiness finding. An axis that cannot be decided does not decide the
verdict.

The candidate is SYNTHETIC. The numbers describe no design, the source path
names no run, and no process, foundry, tool or product appears anywhere.
"""
from pathlib import Path
import dataclasses
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                       / "programs"))
from _ppa import feasibility as FE, metrics as M  # noqa: E402

GATE = "PPA promotion feasibility (cross-layer campaign)"

#: Byte-for-byte the directory this row passes to `--corpus`.
#: ASKED OF THE ROW, NEVER RE-TYPED (vibe-ic#2019 fallout). The campaign trees
#: moved to `docs/campaigns/` and this literal did not follow, so the subject
#: was built where the gate no longer looks and the CAN-PASS arm was rejected
#: rc 2 "no corpus at …". `declared_subject_path` reads the `--corpus` this row
#: actually passes, so the fixture and its row cannot disagree.
_TAIL = "ppa-crosslayer"


def _corpus() -> str:
    """This row's corpus path, from the row.

    Resolved lazily: a missing row must fail THIS fixture, not the census that
    imports every fixture module.
    """
    return F.declared_subject_path(GATE, _TAIL)

_RECORD_REL = "records/synthetic_candidates.json"

#: ONE view, declared as `required_views`, so every axis is required at it. The
#: real campaign sets declare a per-axis map; a fixture does not need one, and a
#: smaller declaration is a smaller thing to keep true.
_VIEW = {"stage": "post_route"}

#: The requirement this fixture breaks. A `count_zero` axis, chosen because the
#: violation is unambiguous — a positive count cannot be read as a rounding
#: difference or a corner disagreement.
_BREAK_METRIC = "physical.drc.violations"
_BREAK_VALUE = 7


def _satisfying(req: dict):
    """A value that MEETS this requirement, chosen by its declared kind."""
    kind = req.get("kind")
    if kind == "slack_nonneg":
        return 0.0, "ns"          # zero slack is non-negative: met, not beaten
    if kind == "count_zero":
        return 0, "count"
    if kind == "verdict_in":
        accept = req.get("accept") or ()
        return (accept[0] if accept else "CLEAN"), "verdict"
    if kind == "limit_min":
        return 1.0, "unit"
    # `limit_max` and anything new: a value the declared limit cannot exclude.
    return 0.0, "unit"


def _candidate_set(break_axis: bool) -> dict:
    records, limits = [], {}
    for axis in FE.DEFAULT_AXES:
        spec = dataclasses.asdict(axis)
        groups = spec.get("groups") or []
        # ONE group per axis: the groups are ALTERNATIVES, so satisfying the
        # first satisfies the axis. Emitting all of them would assert more than
        # the checker asks and make the fixture harder to keep true.
        for req in (groups[0] if groups else []):
            value, unit = _satisfying(req)
            if break_axis and req.get("metric") == _BREAK_METRIC:
                value = _BREAK_VALUE
            if req.get("limit_key"):
                limits[req["limit_key"]] = {"max": 1e9, "min": -1e9}
            records.append({
                "schema": M.SCHEMA_ID,
                "metric": req["metric"],
                "status": "MEASURED",
                "unit": unit,
                "value": value,
                "scope": dict(_VIEW),
                "source": {"path": "reports/synthetic.log",
                           "sha256": "sha256:" + "0" * 64,
                           "tool": "synthetic", "parser": "synthetic"},
            })
    return {
        "schema": "vibeic.ppa.candidates.v1",
        "allow_waivers": False,
        "limits": limits,
        "required_views": [dict(_VIEW)],
        "required_views_by_axis": {},
        "candidates": [{"candidate_id": "synthetic",
                        "metrics": records, "waivers": []}],
    }


def _tree(work: Path, break_axis: bool) -> Path:
    root = F.git_init(work / "subject")
    p = root / _corpus() / _RECORD_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_candidate_set(break_axis), indent=2,
                            sort_keys=True) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Every required axis satisfied at the declared view: FEASIBLE, rc 0."""
    root = _tree(work, break_axis=False)
    F.git_commit(root)
    return root


def can_fail(work: Path):
    """One count_zero requirement violated: INFEASIBLE, drc named, rc 1."""
    root = _tree(work, break_axis=True)
    F.git_commit(root)
    # The token has to appear in the refusal — this is the verdict the checker
    # prints for the axis it refused on.
    return root, "FEAS_VIOLATION"
