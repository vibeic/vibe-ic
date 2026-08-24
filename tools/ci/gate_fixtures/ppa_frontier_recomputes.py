"""`PPA frontier recomputes` — a run that names no promotable design.

WHAT THE DECLARATION CAN AND CANNOT REACH, measured before choosing the
mutation. The dispatcher passes `--candidates <one file>` and no `--frontier`,
and the checker's own header says what that means: "Without `--frontier` the
recomputed document is checked against its own" recomputation. So the document's
`frontier` key is NOT under test through this row — publishing a dominated
candidate there was tried first and returned rc 0, because nothing was comparing
the published list to anything. `PARETO_FRONTIER_DISAGREES` is reachable only
from the `--frontier` form, which this row does not use.

EVERY SHAPE-OF-INPUT MUTATION ROUTES TO rc 2, NOT rc 1. An absent metric, a
missing provenance digest, a non-numeric value, an undeclared objective scope —
all of them are UNDETERMINED codes, and this row is wired through
`run_tolerating_uncheckable`, so a fixture that reached rc 2 would prove only
that the gate noticed it could not look.

THE MUTATION THAT REACHES rc 1: every candidate becomes INFEASIBLE, so the
frontier recomputes to EMPTY. The gate refuses with `PARETO_EMPTY_FRONTIER` and
the sentence "no candidate is both feasible and comparable, so this run names no
promotable design".

THAT IS THE PROPERTY WORTH PINNING. The checker records that an earlier
implementation returned 0 here — "the empty-tree lie at the frontier level: a
promoter reading only the exit code would proceed with nothing". A frontier that
is internally consistent, satisfies every invariant, and names nobody is exactly
the shape a green would be believed over.

ONE VIOLATION, NOT TEN. The CAN-FAIL differs from the CAN-PASS in a single
metric on each candidate — `physical.drc.violations` goes 0 -> 7. Everything
else stays: the same objectives, the same scopes, the same provenance, the same
two comparable axes. A subject that broke several things could refuse for a
reason this fixture does not name, and `gate_fixture_runner` requires the
refusal to carry the declared token.

THE RECORDS ARE SYNTHETIC and the document says so. No search produced these
candidates and no design is described.

chip-AGNOSTIC / PDK-AGNOSTIC: no process, foundry, vendor, tool or product is
named. `stage: post_route` names a point in any flow, and the numbers are round.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "PPA frontier recomputes"

#: Byte-for-byte the path the declaration passes to `--candidates`. The row
#: names ONE document, so the subject has to carry exactly this path or the gate
#: reads nothing and answers about that instead.
_REL = "ppa-crosslayer/records/trials/z23/candidates.json"

_SCOPE = {"stage": "post_route"}
_DIGEST = "sha256:" + "0" * 64


def _m(metric: str, value, unit: str = "1") -> dict:
    return {
        "schema": "vibeic.ppa.metric.v1",
        "metric": metric,
        "status": "MEASURED",
        "unit": unit,
        "value": value,
        "scope": dict(_SCOPE),
        "source": {"path": "reports/synthetic.log", "sha256": _DIGEST,
                   "tool": "synthetic", "parser": "synthetic"},
    }


def _candidate(cid: str, area: float, power: float, *, feasible: bool) -> dict:
    """One proof per default feasibility axis, plus the two objective metrics."""
    return {
        "candidate_id": cid,
        "metrics": [
            _m("timing.setup.wns_ns", 0.10, "ns"),
            _m("timing.hold.wns_ns", 0.05, "ns"),
            _m("timing.drv.violations", 0),
            # THE ONE THAT MOVES between the arms.
            _m("physical.drc.violations", 0 if feasible else 7),
            _m("physical.lvs.verdict", "CLEAN"),
            _m("physical.antenna.violations", 0),
            _m("power.ir.violations", 0),
            _m("reliability.em.violations", 0),
            _m("equivalence.verdict", "PROVEN"),
            _m("area.die.um2", area, "um^2"),
            _m("power.total.mw", power, "mW"),
        ],
    }


def _document(*, feasible: bool) -> dict:
    return {
        "schema": "vibeic.ppa.candidates.v1",
        "synthetic": True,
        "required_views": [dict(_SCOPE)],
        "limits": {"power.ir.worst_drop_v": {"max": 0.18},
                   "reliability.em.worst_ratio": {"max": 1.0}},
        "allow_waivers": False,
        "objectives": [
            {"key": "area", "metric": "area.die.um2", "sense": "min",
             "scope": dict(_SCOPE)},
            {"key": "power", "metric": "power.total.mw", "sense": "min",
             "scope": dict(_SCOPE)},
        ],
        # `a` and `b` are mutually non-dominating (a is smaller in power, b in
        # area); `c` is dominated by both, so a correct recomputation names
        # exactly {a, b} and a fixture that accidentally named all three would
        # not be exercising the domination relation at all.
        "candidates": [
            _candidate("a", 1000.0, 2.0, feasible=feasible),
            _candidate("b", 900.0, 3.0, feasible=feasible),
            _candidate("c", 1100.0, 4.0, feasible=feasible),
        ],
        "frontier": ["a", "b"] if feasible else [],
    }


def _tree(work: Path, name: str, *, feasible: bool) -> Path:
    root = F.git_init(work / name)
    p = root / _REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_document(feasible=feasible), indent=1) + "\n",
                 encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Three comparable candidates; the frontier recomputes to {a, b}."""
    return _tree(work, "subject_pass", feasible=True)


def can_fail(work: Path):
    """Every candidate INFEASIBLE — the frontier is empty and names nobody."""
    root = _tree(work, "subject_fail", feasible=False)
    return root, "PARETO_EMPTY_FRONTIER"
