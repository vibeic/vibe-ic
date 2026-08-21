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

GATE = "PPA head-to-head records"

#: The identity of the PROBLEM, declared per arm so the checker can COMPARE the
#: two rather than read one heading and assume it covered both.
_DESIGN = {
    "spec_sha256": "0" * 64,
    "pdk": "PDK_PLACEHOLDER",
    "clock_target_ns": 10.0,
    "corners": ["corner_a", "corner_b"],
}


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
                "measurement_basis": "post_route_sta",
                "config_source": "this project",
                "tuned_by_this_project": True,
                "ppa": {"area_um2": 1000.0, "timing_wns_ns": -0.10,
                        "power_mw": 5.0},
            },
            {
                "flow": "baseline-under-test",
                "role": "baseline",
                "design": dict(_DESIGN),
                "measurement_basis": "post_route_sta",
                "config_source": "upstream default configuration, unmodified",
                # The one bit the mutation moves.
                "tuned_by_this_project": baseline_tuned_by_us,
                "ppa": {"area_um2": 1200.0, "timing_wns_ns": -0.30,
                        "power_mw": 6.0},
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
_RECORD = "benchmark-data/records/first_head_to_head.json"


def _tree(work: Path, baseline_tuned_by_us: bool) -> Path:
    root = F.git_init(work / "subject")
    p = root / _RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_record(baseline_tuned_by_us), indent=2) + "\n",
                 encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """A record the gate must ACCEPT: same problem on both arms, all three axes,
    no collapsed scalar, the baseline on its own upstream defaults."""
    root = _tree(work, baseline_tuned_by_us=False)
    F.git_commit(root)
    return root


def can_fail(work: Path):
    """The same record, with the opponent tuned by us.

    The numbers are untouched and still favourable, which is the point: this is
    the direction of dishonesty a head-to-head has room for, and the record
    carries no other sign of it.
    """
    root = _tree(work, baseline_tuned_by_us=False)
    F.git_commit(root)
    p = root / _RECORD
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["arms"][1]["tuned_by_this_project"] = True
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    F.git_commit(root, "mutate")
    return root, "tuned_by_this_project"
