"""`step FAIL bubbles up` — an inner FAIL that no waiver and no roll-up names.

THE GATE'S OWN CLAIM is doctrine rule #4: a `reports/**/*.json` declaring
`verdict: FAIL` must reach the step's verdict, "either by being explicitly
waived in `waivers.json`, or by causing the parent step's `pass.flag` to be
absent". `audit()` grants acknowledgment by exactly two routes — (a) a
`waivers.json` entry whose text names the report by IDENTITY, (b) a
`reports/orchestrator/` or `reports/audit/` JSON recording the matching FAIL —
and everything else is `STEP_FAIL_NOT_BUBBLED`.

THE SUBJECT IS A CORPUS, BECAUSE THAT IS WHAT THE DISPATCHER DECLARES. The gate
is wired at `run "step FAIL bubbles up" ... --corpus "$ROOT/benchmark-data/ic"
--corpus-may-be-absent`, so the subject is a git repository carrying published
run trees under `benchmark-data/ic`. The PROJECT mode of the same program is
wired under a DIFFERENT label ("inner FAILs reach the verdict (...)"), whose
argument is a bash loop variable — a separate debt entry, and not reachable
from here, because a fixture may choose the INPUT and never the ARGV.

WHAT CORPUS MODE ACCEPTS. It is a RATCHET, not a cleanliness check: the sweep
is compared against `programs/step_internal_fail_bubble_up_baseline.json`, and
BOTH `now > base` and `now < base` are rc 1. So the only subject this gate
accepts is one that stands EXACTLY at the recorded ceiling, and the fixture
reads that ceiling from the register the gate itself reads rather than pinning
a literal that the register — which may only shrink — is free to move under it.

THE PASSING SPECIMEN IS NOT VACUOUS, AND A CLEAN TREE WOULD HAVE BEEN. A corpus
whose reports declare no FAIL at all takes the `saw_any_fail is False` branch:
the gate accepts it without the acknowledgment matcher ever running, which is
this repo's "detector that never says no". So the accepted subject carries REAL
inner FAILs and exercises BOTH acknowledgment routes:

    reference_design/v1_acknowledged_run
        4 reports carry a verdict; 2 of them declare FAIL
          stage_alpha/inner_gate_alpha -> route (a), the waivers.json entry
          stage_beta/inner_gate_gamma  -> route (b), the orchestrator roll-up
        0 findings
    reference_design/v1_recorded_ceiling_run
        <ceiling> report(s), each a FAIL that nothing names
        <ceiling> findings

The denominator the gate prints over that subject is `2 published run
tree(s), 2 with a reports/ tree` — 1 and 1 when a recorded ceiling of 0
drops the second run rather than inventing an acknowledged-only
ceiling. Break the matcher in either direction and this specimen moves:
acknowledge-nothing takes the sweep to ceiling+2, acknowledge-everything
takes it to 0. Both are rc 1.

THE MUTATION BREAKS EXACTLY ONE CONDITION — THE ACKNOWLEDGMENT OF ONE REPORT.
`waivers.json` loses its single `waived_steps` entry, the one naming
`inner_gate_alpha`. Everything else is BYTE-IDENTICAL to the accepted subject:
the same run trees, the same report files, the same verdicts (no FAIL is added
and none is moved), the same `_doc` in the same `waivers.json`, the same
orchestrator roll-up — so `inner_gate_gamma` stays acknowledged by route (b),
and the ceiling run is untouched. That is what makes the refusal attributable:
the two specimens differ only in whether one FAIL is acknowledged, so the gate
cannot be refusing because a FAIL exists, because a report appeared, or because
the corpus changed shape.

WHY NOT MUTATE A `PASS` REPORT INTO A `FAIL`. That also yields one
unacknowledged FAIL, but it changes the population of FAIL reports as well as
the acknowledgment, so a gate that merely counted FAIL reports and never read
`waivers.json` would refuse it and be recorded as discriminating. Holding the
verdicts fixed is what makes the acknowledgment the only variable.

chip-AGNOSTIC / PDK-AGNOSTIC: every name written into the subject describes the
SHAPE of the evidence (a design, a run, a stage, an inner gate). No foundry,
process node, SKU, vendor, tool or product is named, and the tree is built at
run time rather than stored.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "step FAIL bubbles up"

#: The corpus root the dispatcher names, relative to the subject repository.
CORPUS_REL = Path("benchmark-data/ic")

#: The register the gate ratchets against. NOT redirected at the fixture: it
#: lives beside the gate's own code, exactly as `$PG` does.
BASELINE = "step_internal_fail_bubble_up_baseline.json"

_ACK_RUN = "reference_design/v1_acknowledged_run"
_CEILING_RUN = "reference_design/v1_recorded_ceiling_run"


def recorded_ceiling() -> int:
    """`findings_total` from the register the gate compares the sweep against.

    Read rather than pinned. The register MAY ONLY SHRINK, so a literal here
    would turn a legitimate repair of the published corpus into a red fixture
    and send the next reader to debug the specimen instead of the gate.

    0 on an unreadable or malformed register — that is a state the gate answers
    for itself (`[NOT CHECKED] no baseline`, rc 2), and the fixture must not
    hide it behind a guess.
    """
    try:
        doc = json.loads((F.PROGRAMS / BASELINE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = doc.get("findings_total") if isinstance(doc, dict) else None
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _report(name: str, verdict: str) -> dict:
    return {"gate": name, "verdict": verdict,
            "detail": "a step-internal sub-gate report written by the flow"}


def _build(work: Path, name: str, *, waive_alpha: bool) -> Path:
    root = F.git_init(work / name)
    corpus = root / CORPUS_REL
    run = corpus / _ACK_RUN

    # Two FAILs and two PASSes: the population `audit()` walks. The two FAILs
    # are the reason this specimen is not vacuous — each takes one of the two
    # acknowledgment routes.
    _write_json(run / "reports/stage_alpha/inner_gate_alpha.json",
                _report("inner_gate_alpha", "FAIL"))
    _write_json(run / "reports/stage_alpha/inner_gate_beta.json",
                _report("inner_gate_beta", "PASS"))
    _write_json(run / "reports/stage_beta/inner_gate_gamma.json",
                _report("inner_gate_gamma", "FAIL"))
    _write_json(run / "reports/stage_beta/inner_gate_delta.json",
                _report("inner_gate_delta", "PASS"))

    # Route (b). `_bubbled_corpus` keeps only lines that carry the word FAIL,
    # so the report's identity and the verdict must sit on the SAME line.
    _write_json(run / "reports/orchestrator/step_roll_up.json", {
        "gate": "step_roll_up",
        "verdict": "FAIL",
        "unresolved": [
            "reports/stage_beta/inner_gate_gamma.json declares FAIL, so the "
            "parent step withheld its pass.flag",
        ],
    })

    # Route (a). THE ONE THING THE MUTATION REMOVES. `_doc` deliberately names
    # no report, so dropping the entry drops the whole acknowledgment and
    # nothing else.
    _write_json(run / "waivers.json", {
        "_doc": "Waivers recorded for this run tree; each entry names the "
                "one report it acknowledges.",
        "waived_steps": ([{
            "id": 7,
            "reason": "inner_gate_alpha declares FAIL and the step owner "
                      "accepted it for this run",
            "ticket": "fixture-acknowledged-inner-fail",
            "evidence": "reports/stage_alpha/inner_gate_alpha.json",
        }] if waive_alpha else []),
    })

    # The recorded ceiling, held by a SECOND run so the acknowledgment
    # demonstration above stays at zero findings and can be read on its own.
    for i in range(recorded_ceiling()):
        _write_json(
            corpus / _CEILING_RUN /
            f"reports/stage_alpha/unnamed_inner_fail_{i + 1}.json",
            _report(f"unnamed_inner_fail_{i + 1}", "FAIL"))

    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Both inner FAILs acknowledged, so the sweep stands at the ceiling."""
    return _build(work, "subject_pass", waive_alpha=True)


def can_fail(work: Path):
    """One waiver entry removed: `inner_gate_alpha` is now named by nothing."""
    root = _build(work, "subject_fail", waive_alpha=False)
    return root, "unacknowledged step-internal FAILs GREW"
