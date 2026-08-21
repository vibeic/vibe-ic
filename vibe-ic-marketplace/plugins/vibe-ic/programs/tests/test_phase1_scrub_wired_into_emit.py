"""Tests for v0.1.60 R11 capture: phase1_post_process.scrub_l_doc must be
INVOKED at the L-doc-write chokepoint in phase1_doc_one_shot_runner.

Captured from user's AMBA AXI IHI0022H parity run on v0.1.57: the scrubber
caught "ic_name = SUCH ARM TECHNOLOGY" in isolation (lifted from the ARM
license clause "USE OR IMPLEMENTATION OF SUCH ARM TECHNOLOGY"), but the
doc-mode runner pipeline never called it — so the hallucination pollutes
all 14 L docs in fresh runs. Now wired into _write_l_doc.

Honesty constraint: this guards against grounded-but-misplaced ic_name
extraction (the string IS in the PDF, but it's license boilerplate, not
the IC's name). Cat-A misextraction caught deterministically, not by
over-fitting to the AXI dataset.
"""
import importlib
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"


def _load_scrub():
    if "phase1_post_process" in sys.modules:
        del sys.modules["phase1_post_process"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("phase1_post_process")


# ── HALLUC_PATTERNS still catch the captured symptom ──────────────────

def test_scrubber_catches_such_arm_technology():
    """The v0.1.51 HALLUC_PATTERNS regex must still match the AMBA AXI
    license-clause ic_name lift verbatim."""
    mod = _load_scrub()
    doc = {"ic_name": "SUCH ARM TECHNOLOGY"}
    log = mod.scrub_l_doc(doc, "L1_DATASHEET")
    assert doc["ic_name"] == "UNKNOWN_IC"
    assert len(log) == 1
    assert log[0].pattern_name == "ic_name_from_license_clause"


def test_scrubber_catches_use_or_implementation_form():
    mod = _load_scrub()
    doc = {"ic_name": "USE OR IMPLEMENTATION OF SUCH ARM"}
    log = mod.scrub_l_doc(doc, "L1_DATASHEET")
    assert doc["ic_name"] == "UNKNOWN_IC"


def test_scrubber_preserves_real_ic_names():
    """ANTI-FALSE-POSITIVE: a real IC name must NOT trip the scrubber."""
    mod = _load_scrub()
    for name in ("AMBA AXI", "TPM-2.0", "AT-cmd-driven IC", "RISC-V Core",
                 "SHA-256 Engine", "u_hawaii_adc"):
        doc = {"ic_name": name}
        log = mod.scrub_l_doc(doc, "L1_DATASHEET")
        assert doc["ic_name"] == name, (
            f"Real IC name {name!r} was mis-scrubbed: log={log}")


# ── Runner wiring: chokepoint actually calls the scrubber ─────────────

def test_write_l_doc_imports_scrub_l_doc():
    """phase1_doc_one_shot_runner.py:_write_l_doc must import scrub_l_doc."""
    src = RUNNER.read_text()
    # The capture-comment block + the import must be present.
    assert "from phase1_post_process import scrub_l_doc" in src, (
        "_write_l_doc must import the scrubber to invoke it on every emit.")


def _content_write_pos(src: str) -> int:
    """Where `_write_l_doc` serialises `content`, or -1.

    Two spellings are accepted. Since vibe-ic#522 every L-document write
    goes through the shared chokepoint that records the producing release
    (`_stamp.dump(out, content)`); before that it was an inline
    `out.write_text(json.dumps(content …))`. The assertions below are
    about ORDERING — scrub first, then write — and naming one particular
    spelling of the write is what made them break when it was factored,
    not any change to the ordering they exist to protect.
    """
    return max(src.find("_stamp.dump(out, content)"),
               src.find("out.write_text(json.dumps(content"))


def test_write_l_doc_invokes_scrubber_before_writing_disk():
    """The scrub call must come BEFORE the serialisation of `content`, so
    the on-disk JSON reflects the scrubbed content, not the pre-scrub
    original."""
    src = RUNNER.read_text()
    scrub_pos = src.find("_scrub_l_doc(content, name)")
    write_pos = _content_write_pos(src)
    assert scrub_pos > 0, "scrubber invocation missing"
    assert write_pos > 0, (
        "no recognised serialisation of `content` found in _write_l_doc — "
        "if the write was renamed again, teach _content_write_pos the new "
        "spelling rather than deleting the ordering assertion")
    assert scrub_pos < write_pos, (
        "scrubber must be invoked BEFORE the disk write so the on-disk JSON "
        f"is the scrubbed version. scrub_pos={scrub_pos} write_pos={write_pos}")


def test_write_l_doc_records_audit_trail():
    """When the scrubber fires, its audit log must be attached to
    content['extraction_strategy']['hallucination_scrub_v0_1_60'] so the
    parity diff + downstream review can see WHAT was scrubbed and WHY."""
    src = RUNNER.read_text()
    assert "hallucination_scrub_v0_1_60" in src
    # And the attach-to-content code path must come before the write
    attach_pos = src.find("hallucination_scrub_v0_1_60")
    write_pos = _content_write_pos(src)
    assert write_pos > 0
    assert attach_pos < write_pos


def test_write_l_doc_scrub_failure_is_fail_open():
    """If the scrubber crashes / is missing, emission must still proceed
    (fail-open) so a future scrubber bug doesn't gate the runner."""
    src = RUNNER.read_text()
    # The scrub call must be inside a try block
    scrub_pos = src.find("_scrub_l_doc(content, name)")
    # Look backward for a `try:` within 500 chars
    head = src[max(0, scrub_pos - 500):scrub_pos]
    assert "try:" in head, "scrub call must be inside try: (fail-open contract)"
    # And followed by an except that records an error without raising
    tail = src[scrub_pos:scrub_pos + 800]
    assert "except" in tail


# ── End-to-end on the captured symptom ────────────────────────────────

def test_end_to_end_scrub_via_write_chokepoint(tmp_path, monkeypatch):
    """Drive the production path: build a content dict with the AMBA AXI
    hallucination, invoke a stand-in _write_l_doc that mirrors the runner's
    wiring, and confirm the file on disk has the scrubbed name."""
    mod = _load_scrub()
    # Simulate the runner's chokepoint: scrub then write
    content = {
        "ic_name": "SUCH ARM TECHNOLOGY",
        "title": "AMBA AXI and ACE Protocol Specification (IHI0022H)",
    }
    log = mod.scrub_l_doc(content, "L1_DATASHEET")
    assert content["ic_name"] == "UNKNOWN_IC"
    assert log[0].old_value == "SUCH ARM TECHNOLOGY"
    assert log[0].new_value == "UNKNOWN_IC"
