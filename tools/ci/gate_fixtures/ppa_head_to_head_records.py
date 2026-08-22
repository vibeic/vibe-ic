"""`PPA head-to-head records` — a record that rigs the opponent it beat.

THE MUTATION IS THE CLAIM, NOT THE FILE. The record stays present, stays named
so the checker's own glob finds it, keeps both arms, keeps all three axes and
keeps numbers that are favourable to us. One boolean changes: the baseline stops
declaring `tuned_by_this_project: false`.

That is deliberately the refusal (#1121 constraint 2, C3) whose absence is
hardest to notice from the outside, because the record still reads like a win.
Every other direction — a missing axis, an unreadable file, an empty corpus —
routes to the checker's UNDETERMINED path, and this gate is wired through the
uncheckable channel, so a fixture that reached rc 2 would prove only that the
gate noticed it could not look. The mutation has to leave the gate a corpus it
CAN read and change the answer inside it.

The records are SYNTHETIC and say so in the file. No head-to-head has been run
(that is the whole of #1121), and a fixture must never be mistaken for evidence
of one — `synthetic: true` and the flow names are placeholders, not results.

chip-AGNOSTIC / PDK-AGNOSTIC: `pdk` here is a placeholder token the checker only
ever compares to the OTHER arm's copy of itself; it names no real process.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

# THE DIGEST IS DERIVED FROM THE CHECKER'S OWN CANONICALISER, never typed into
# this file. `check_contract_identity` recomputes `digest_of(body)` and refuses
# rc 1 when the stated identity is not the real one, so a hardcoded hash here
# would be a stale pin that goes wrong the first time the body is edited — and
# it would fail as CONTRACT_HASH_WRONG, which reads like a defect in the gate
# rather than in this fixture.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                       / "programs"))
from _ppa import canonical_json as _cj  # noqa: E402
from _ppa import benchmark as _bench  # noqa: E402

GATE = "PPA head-to-head records"

#: The identity of the PROBLEM, declared per arm so the checker can COMPARE the
#: two rather than read one heading and assume it covered both.
_DESIGN = {
    "spec_sha256": "0" * 64,
    "pdk": "PDK_PLACEHOLDER",
    "clock_target_ns": 10.0,
    "corners": ["corner_a", "corner_b"],
}


#: A stated value for each scope key the checker requires. Anything not named
#: here still gets a value from `_SCOPE_FALLBACK`, and that is deliberate: the
#: keys are read from `_bench.REQUIRED_SCOPE` rather than typed out, so a new
#: required key added to the checker tomorrow appears in this fixture
#: automatically instead of sending it dark with SCOPE_INCOMPLETE. That is the
#: state this file was found in — a CAN-PASS input the gate could no longer
#: accept, which reads as a broken gate rather than as a stale fixture.
#:
#: Generic tokens only: none of these names a process, a foundry or a product.
_SCOPE_VALUES = {
    "stage": "post_route",
    "mode": "functional",
    "process": "typical",
    "voltage_v": 1.0,
    "temperature_c": 25.0,
    "rc_corner": "typical",
    "check": "setup",
    "activity_basis": "simulation_activity",
}
_SCOPE_FALLBACK = "declared_placeholder"


def _scope(axis: str) -> dict:
    """Every key the checker requires for `axis`, each carrying a stated value.

    BOTH ARMS GET THE SAME SCOPE, which the checker enforces as SCOPE_DIVERGED:
    two numbers taken under different conditions are different metrics.

    `null` and `""` are refused by name (SCOPE_SENTINEL) because two of them
    compare EQUAL and would buy a parity nobody measured — so the fallback is a
    stated token and never an empty one.
    """
    return {k: _SCOPE_VALUES.get(k, _SCOPE_FALLBACK)
            for k in _bench.REQUIRED_SCOPE[axis]}


def _metric(axis: str, value: float) -> dict:
    """The canonical metric record: a number that says what it is.

    A bare float is the v1 shape and the checker still reads it, but it carries
    no status and no scope, so it routes to UNDETERMINED — and this gate is
    wired through the uncheckable channel, where UNDETERMINED proves only that
    the gate noticed it could not look.
    """
    return {"value": value, "status": _bench.COMPARABLE_STATUS,
            "scope": _scope(axis)}


def _feasibility() -> dict:
    """Both arms answered the same feasibility question, and both passed it.

    SMALLER AREA WITH VIOLATIONS IS NOT SMALLER — an arm that did not close is
    not the cheaper one, so the checker refuses a comparison where feasibility
    is NOT_CHECKED. Both arms get the identical object, which is also what the
    parity rule wants: a campaign that ran more checks is held to more, and two
    arms asked different questions were not compared.

    The check NAMES come from `_bench.FEASIBILITY_FLOOR` and the clean spelling
    for a verdict-shaped check from `_bench.VERDICT_CLEAN`, so neither is typed
    here. A check added to the floor tomorrow appears in this fixture instead of
    sending it dark — the same reason `_scope` reads `REQUIRED_SCOPE`.
    """
    checks = {}
    for name in _bench.FEASIBILITY_FLOOR:
        accept = _bench.VERDICT_CLEAN.get(name)
        if accept:
            # A verdict-shaped check: LVS answers "do these two circuits match",
            # which is not a population, so a count would be a type error.
            checks[name] = {"verdict": accept[0], "status": _bench.CHECK_CLEAN}
        else:
            # Count AND status, which must agree — the count is the measurement
            # and the status beside it is an assertion, and the checker reports
            # any disagreement rather than picking the flattering one.
            checks[name] = {"violations": 0, "status": _bench.CHECK_CLEAN}
    return {"checks": checks}


def _contract() -> dict:
    """The problem identity, carried as a body plus the hash OF that body.

    BOTH ARMS GET THE SAME OBJECT, which is the whole point of the check: the
    identity is proven by hash rather than by a shared heading, so two arms that
    solved different problems cannot pass by both saying "same design".

    The body is `_DESIGN` itself, so `design` and `contract.body` cannot state
    one problem twice and differently — the checker refuses that as
    CONTRACT_CONTRADICTS_DESIGN over the intersection of PROBLEM_FIELDS, and
    every one of those four fields lives in `_DESIGN`.
    """
    body = dict(_DESIGN)
    return {"sha256": _cj.digest_of(body), "body": body}


def _record(baseline_tuned_by_us: bool) -> dict:
    return {
        "synthetic": True,
        "note": ("SYNTHETIC gate fixture, not a measurement. No head-to-head "
                 "has been run; these numbers describe no design."),
        "arms": [
            {
                "flow": "subject-under-test",
                "role": "subject",
                "design": dict(_DESIGN),
                # NO AUTO-TUNER ON EITHER ARM, stated rather than left
                # blank. "we do not know whether the opponent was
                # allowed to tune" is the state the condition exists to
                # end, so ABSENCE is refused while an honest
                # `supported: false` passes. This is a different
                # question from `tuned_by_this_project`, which is about
                # whose CONFIG the arm ran.
                "tuning": {"supported": False, "performed": False},
                "feasibility": _feasibility(),
                "contract": _contract(),
                "measurement_basis": "post_route_sta",
                "config_source": "this project",
                "tuned_by_this_project": True,
                "ppa": {
                    "area_um2": _metric("area_um2", 1000.0),
                    "timing_wns_ns": _metric("timing_wns_ns", -0.10),
                    "power_mw": _metric("power_mw", 5.0),
                },
            },
            {
                "flow": "baseline-under-test",
                "role": "baseline",
                "design": dict(_DESIGN),
                # NO AUTO-TUNER ON EITHER ARM, stated rather than left
                # blank. "we do not know whether the opponent was
                # allowed to tune" is the state the condition exists to
                # end, so ABSENCE is refused while an honest
                # `supported: false` passes. This is a different
                # question from `tuned_by_this_project`, which is about
                # whose CONFIG the arm ran.
                "tuning": {"supported": False, "performed": False},
                "feasibility": _feasibility(),
                "contract": _contract(),
                "measurement_basis": "post_route_sta",
                "config_source": "upstream default configuration, unmodified",
                # The one bit the mutation moves.
                "tuned_by_this_project": baseline_tuned_by_us,
                "ppa": {
                    "area_um2": _metric("area_um2", 1200.0),
                    "timing_wns_ns": _metric("timing_wns_ns", -0.30),
                    "power_mw": _metric("power_mw", 6.0),
                },
            },
        ],
    }


#: The checker's corpus glob is `**/*head_to_head*.json`, so the NAME is part of
#: the fixture: a record the glob does not match is a record the gate never
#: sees, and the fixture would then be measuring the empty corpus instead.
#:
#: The DIRECTORY is part of it too. The declaration reads `--corpus
#: "$ROOT/benchmark-data"`, so the subject must carry that tree or the gate
#: resolves to "no corpus here" and answers about the corpus rather than about
#: the record. Placing it correctly is also what keeps `$VIBE_IC_BENCHMARK_DATA`
#: from steering the fixture if a developer happens to have it set: the named
#: root wins whenever it carries a corpus of its own.
#: The corpus directory THIS gate's declaration names. The same checker is
#: wired three times over three different corpora — `benchmark-data`,
#: `ppa-crosslayer`, `ppa-e2e` — and a fixture must drive the gate AS THE
#: DISPATCHER DECLARES IT, so the campaign variants are sibling modules that
#: reuse this record and only move the directory. The schema lives in ONE place
#: on purpose: it is a five-generation drift in exactly this record that sent
#: the original fixture dark, and three copies would have drifted three ways.
CORPUS = "benchmark-data"
_RECORD_REL = "records/first_head_to_head.json"


def _record_path(root: Path, corpus: str) -> Path:
    return root / corpus / _RECORD_REL


def _tree(work: Path, baseline_tuned_by_us: bool,
          corpus: str = CORPUS) -> Path:
    root = F.git_init(work / "subject")
    p = _record_path(root, corpus)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_record(baseline_tuned_by_us), indent=2) + "\n",
                 encoding="utf-8")
    return root


def build_can_pass(work: Path, corpus: str) -> Path:
    """The CAN-PASS subject, for whichever corpus a variant's gate names."""
    root = _tree(work, baseline_tuned_by_us=False, corpus=corpus)
    F.git_commit(root)
    return root


def build_can_fail(work: Path, corpus: str):
    """The CAN-FAIL subject: the same record with the opponent tuned by us."""
    root = _tree(work, baseline_tuned_by_us=False, corpus=corpus)
    F.git_commit(root)
    p = _record_path(root, corpus)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["arms"][1]["tuned_by_this_project"] = True
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    F.git_commit(root, "mutate")
    return root, "tuned_by_this_project"


def can_pass(work: Path) -> Path:
    """A record the gate must ACCEPT: same problem on both arms, all three axes,
    no collapsed scalar, the baseline on its own upstream defaults."""
    return build_can_pass(work, CORPUS)


def can_fail(work: Path):
    """The same record, with the opponent tuned by us.

    The numbers are untouched and still favourable, which is the point: this is
    the direction of dishonesty a head-to-head has room for, and the record
    carries no other sign of it.
    """
    return build_can_fail(work, CORPUS)
