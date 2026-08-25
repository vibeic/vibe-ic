"""`protocol detector no-misfire matrix` — one benchmark, carrying a second
protocol's structural signature.

WHAT THE GATE IS ASKING, in its own words: every module-level `is_<stem>`
exported by a `<stem>_protocol_synth.py` is run against EVERY benchmark's
content blob and must fire on its OWN benchmark and on no other, modulo the
documented `DERIVED_SIBLING_CROSS_FIRES` allowlist. Both directions of the
cross-fire fall out of the same matrix: a NEW detector firing on an existing
benchmark, and an existing detector firing on a NEW one.

THE ESCAPE IT WAS WRITTEN FOR is contamination of the documents rather than a
bug in the detector: "the Tier-G batch left SENT content in the io_link gold and
Ethernet content in the mdio docs, which gated-parity-0 cannot see". This
fixture reproduces exactly that shape — a benchmark whose documents carry a
foreign protocol's public structural vocabulary alongside their own.

THE SUBJECT IS ONE BENCHMARK, AND BOTH ARMS CARRY IT. The gate prints its two
denominators — `detectors=N  benchmarks=M` — and, since 2026-08-25, returns rc 2
NOT CHECKED when either axis is zero. A fixture that reached red by emptying the
corpus would exercise that refusal and would say nothing about the predicate.
Both arms here present ONE benchmark to the SAME 86 real detectors, loaded from
the real `$PG` (the fixture may choose the input and never the argv). Neither
denominator moves; the ANSWER inside them does.

THE MUTATION IS ADDED CONTENT, AND NOTHING ELSE. The accepted arm is the `lora`
benchmark carrying the committed LoRaWAN blob, so `is_lora` fires on its own
benchmark and nothing else fires — the OWN fire is preserved, which is what
makes the finding about the FOREIGN one. The refused arm appends the committed
SENT blob to the same three L-docs and the same source spec: `is_sent` now fires
on `lora`, which is a foreign fire, rc 1.

DIRECTION. The gate flags a detector firing OUTSIDE its own benchmark, so it is
tripped by ADDING a foreign signature, never by removing the benchmark's own —
deleting the LoRa text would only silence `is_lora`, which the matrix does not
refuse (a detector that fires nowhere is a different finding this gate does not
make).

BOTH BLOBS COME FROM THE REPOSITORY'S OWN COMMITTED FIXTURE MODULE
`programs/tests/fixtures/synthetic_protocol_blobs.py`, so the two arms cannot
drift from the corpus the gate really reads, and no protocol vocabulary is
re-typed here. Those blobs are hand-written public structural specs.

chip-AGNOSTIC: names no IC, vendor, SKU or process — two open protocol
specifications quoted from a fixture this repository already ships.
"""
import json
import sys
from pathlib import Path

GATE = "protocol detector no-misfire matrix"

#: The corpus path the gate's declared argv names, relative to `$PLUGIN`.
_REL = "programs/tests/fixtures/synthetic_benchmark_phase1"

#: Where the committed blobs live, relative to the repository root.
_BLOBS = ("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures")

#: The benchmark under test, and the protocol whose content is smuggled into it.
_OWN = "lora"
_FOREIGN = "sent"


def _blobs():
    """The repository's OWN blob table, never a copy of it."""
    here = Path(__file__).resolve()
    root = here.parents[3]          # tools/ci/gate_fixtures/<f>.py -> repo root
    sys.path.insert(0, str(root / _BLOBS))
    from synthetic_protocol_blobs import SYNTHETIC_BLOBS  # noqa: E402
    return SYNTHETIC_BLOBS


def _tree(work: Path, text: str) -> Path:
    """One benchmark, in the on-disk shape both the superset and gold blobs read."""
    root = work / "subject"
    p1 = root / _REL / _OWN / "phase1"
    for d in ("input_doc", "generated_docs", "claude_extracted"):
        (p1 / d).mkdir(parents=True, exist_ok=True)
    (p1 / "input_doc" / "spec.txt").write_text(text, encoding="utf-8")
    docs = {
        "L1_DATASHEET.json": {"ic_name": "%s Reference" % _OWN.upper(),
                              "spec_text": text},
        "L2_FRS.json": {"functional_requirements": text},
        "L3_CMD_PROTOCOL.json": {"command_protocol": text},
    }
    for d in ("generated_docs", "claude_extracted"):
        for name, body in docs.items():
            (p1 / d / name).write_text(json.dumps(body, indent=2),
                                       encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One benchmark carrying only its own protocol: 86 detectors, 1 benchmark,
    one own-fire, zero foreign fires — rc 0."""
    return _tree(work, _blobs()[_OWN])


def can_fail(work: Path):
    """The same one benchmark, its documents now also carrying a second
    protocol's structural signature. Same two denominators, opposite answer."""
    b = _blobs()
    root = _tree(work, b[_OWN] + "\n" + b[_FOREIGN])
    # The pair test requires the refusal to name THIS mutation, so that an
    # unrelated non-zero exit cannot be mistaken for the check working.
    return root, "is_%s: foreign_fires=['%s']" % (_FOREIGN, _OWN)
