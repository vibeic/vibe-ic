"""spec_complete_extract — the GENERAL completeness engine (benchmark-agnostic).

Proves the per-record completeness machinery that drove CVDP 210->229 now serves a
plain Phase-1 design doc (NO cocotb harness): the interface is SUPPLIED (a port
list, as L-docs provide), and every benchmark-convergence width fix (Default-column
param table, param-expression widths, log2ceil, clk/rst/1-bit conventions) applies.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import spec_complete_extract as E  # noqa: E402
import cvdp_complete_extract as C  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

_FIFO_DOC = """Design a synchronous FIFO `my_fifo`.
## Parameters
| Parameter | Description | Default | Constraints |
| `DATA_WIDTH` | data bus width | 8 | >= 1 |
| `DEPTH` | entries | 16 | power of 2 |
## Ports
- `clk`: clock.
- `rst_n`: active-low async reset.
- `wr_en`: write enable.
- `rd_en`: read enable.
- `[DATA_WIDTH-1:0] din`: write data.
- `[DATA_WIDTH-1:0] dout`: read data.
- `full`: FIFO full flag.
- `empty`: FIFO empty flag.
"""


def test_general_doc_no_harness_is_complete():
    spec = E.assess_spec(
        _FIFO_DOC,
        inputs=["clk", "rst_n", "wr_en", "rd_en", "din"],
        outputs=["dout", "full", "empty"],
        module_name="my_fifo")
    assert spec["completeness"] == "COMPLETE", spec["completeness_reason"]
    assert spec["gaps"] == []
    widths = {p["name"]: p["width"] for p in spec["interface"]}
    # the benchmark Default-column width fix resolves DATA_WIDTH=8 for a general doc
    assert widths["din"] == 8 and widths["dout"] == 8
    # clk/rst/control ports are 1-bit by convention
    assert widths["clk"] == 1 and widths["rst_n"] == 1 and widths["full"] == 1


def test_general_doc_missing_data_width_is_gap():
    # a DATA port the doc never sizes -> honest gap, NOT a fabricated width
    doc = ("Design a block `blk`. Ports: `clk`, `data_bus` (the main data path), "
           "`valid_o`.")
    spec = E.assess_spec(doc, inputs=["clk", "data_bus"], outputs=["valid_o"],
                         module_name="blk")
    assert spec["completeness"].startswith("INCOMPLETE")
    assert any("data_bus" in g["detail"] for g in spec["gaps"])
    # clk + valid_o still placed as 1-bit; only data_bus is the gap
    assert any(p["name"] == "clk" and p["width"] == 1 for p in spec["interface"])


def test_no_interface_source_is_spec_absent():
    spec = E.assess_spec("Some prose with no ports.", inputs=[], outputs=[])
    assert spec["completeness"] == "INCOMPLETE_SPEC_ABSENT"


def test_skeleton_iface_passthrough():
    sk = [{"name": "a", "dir": "input", "width": 4, "signed": False,
           "source": "skeleton_header"}]
    spec = E.assess_spec("prose", inputs=[], outputs=[], skeleton_iface=sk)
    assert spec["interface"] == sk and spec["completeness"] == "COMPLETE"


#: The census record — WHICH records resolve COMPLETE over WHICH corpus. The
#: expectation lives THERE, not as an integer literal here: a bare count is
#: invariant under one record arriving and another leaving, and — the reason
#: this file learned it the hard way — a bare count also cannot say whether the
#: CORPUS moved or the READER moved. Both questions are answered by pinning the
#: corpus identity beside the members it produced.
_CENSUS = _PROG / "cvdp_complete_census_baseline.json"

_CVDP_RELPATH = ("_extbench/cvdp_open_v110/"
                 "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


def _cvdp_corpus():
    """(records, census) over the pinned corpus — or an explicit failure saying
    WHICH dimension moved.

    The dataset is external and not version-controlled, so "the count changed"
    is two different events wearing one face. This separates them BEFORE any
    census assertion runs: a byte/record-count mismatch is reported as a corpus
    event, and the member comparison — which would be meaningless over other
    bytes — is never reached. It is a FAILURE and not a skip on purpose: a
    silent skip here is the shape that lets a real regression land green.
    """
    ds = require_corpus(_CVDP_RELPATH)
    if not ds.exists():
        pytest.skip("dataset not present")
    census = json.loads(_CENSUS.read_text())
    pinned = census["corpus"]
    blob = ds.read_bytes()
    recs = [json.loads(l) for l in blob.decode().splitlines() if l.strip()]
    got = (hashlib.sha256(blob).hexdigest(), len(recs))
    want = (pinned["sha256"], pinned["records"])
    assert got == want, (
        f"THE CORPUS MOVED, not the reader chain. {ds} is sha256={got[0]} with "
        f"{got[1]} records; {_CENSUS.name} was measured against sha256={want[0]} "
        f"with {want[1]}. Every census assertion below is a claim about THOSE "
        f"bytes and is not applicable to these. Re-derive the record against the "
        f"new corpus and argue the delta in it — do NOT edit a number to match.")
    return recs, census


def _is_degenerate(spec) -> bool:
    """Does this verdict describe a module with nothing coming IN, or nothing
    going OUT?

    Structural and name-free: it asks the SHAPE of the recovered interface and
    never which design it belongs to, so it applies to a corpus it has never
    seen. `inout` satisfies both directions.
    """
    dirs = {p.get("dir") for p in spec.get("interface", [])}
    return not (dirs & {"input", "inout"}) or not (dirs & {"output", "inout"})


def test_cvdp_adapter_complete_count_is_prompt_context_only():
    """The CVDP adapter reads ONLY input.prompt + input.context (§4.05 compliance:
    the model sees only the submitter-visible spec; the hidden cocotb `dut.<sig>`
    test, the `.env` TOPLEVEL and the golden output are OFF-LIMITS oracle). Over the
    real 302-record dataset the COMPLETE count therefore reflects PROMPT+CONTEXT
    interface recovery — the compliant clean-room baseline, NOT the old
    harness-inflated 255 (which counted records whose interface was recoverable only
    from the cocotb harness).

    ORGANIC-20260703 (cvdp_complete_extract phantom-port + skeleton fix) raised the
    clean-room baseline 215 -> 223, ALL prompt+context-only:
      * +9 — the adapter now parses the PROMPT's own ```verilog module <top>( ANSI
        skeleton (a legitimate input.prompt fact, previously ignored) so a record
        whose full interface is declared in the prompt header resolves COMPLETE
        instead of being mis-read by the prose parser (verified: each of the 9 has a
        2-18 port prompt skeleton — flop/crossbar/image_rotate/…);
      * -1 — `binary_to_gray_0001` was COMPLETE only on PHANTOM ports `wire`/`output`
        (Verilog keywords mis-parsed as port names); the reserved-word guard drops
        them, so its honest verdict is now INCOMPLETE_SPEC_ABSENT.
    Both moves are pure prompt+context correctness — no harness read."""
    recs, census = _cvdp_corpus()
    measured = {r["id"] for r in recs
                if C.extract(r)["completeness"] == "COMPLETE"}
    pinned = set(census["complete_ids"])
    # ORGANIC-20260705: the v1.2.96 harness-read removal replaced the oracle
    # interface path with `_table_interface` (test-case tables) + `_prose_ports`
    # ONLY, silently dropping two common PROMPT interface forms — the markdown
    # Signal/Direction/Width table and the `- `name` (input, N bits):` prose bullet
    # list. Restoring both input-only parsers recovered 223 -> 226 (comparator via
    # the signal-direction table; apb_dsp_unit + sorter via the prose-bullet list),
    # all prompt-sourced, ZERO harness reads, and a strict superset of the 223 set.
    #
    # 2026-07-13 (PR #130 `recover_interface_from_prompt`, cvdp RCA distillation):
    # a "modify existing RTL" prompt that RE-DECLARES its interface in an explicit
    # "Updated Input/Output Interfaces" prose section is now parsed from input.prompt
    # (authoritative over the stale context-RTL header). This recovered 226 -> 228:
    # +apb_gpio_0001 and +packet_controller_0001, BOTH sourced solely from
    # input.prompt (verified: neutralizing recover_interface_from_prompt drops the
    # count back to exactly 226), a strict superset (no COMPLETE lost) and ZERO
    # harness/golden reads. This is the §4.05-compliant clean-room baseline.
    # 228 -> 226 (2026-08-25). `_CTRL_WORD` carried a block of tokens whose own
    # comment said they were "structurally 1-bit in this benchmark's cocotb
    # harnesses" — `money change item crc mode shift interval status priority
    # sensor reload` and the rest. Each names a VALUE, and a value has no width
    # until the spec states one, so an unstated width became a silent 1 with NO
    # gap recorded instead of a reported `width_not_stated`. Two records were
    # scoring COMPLETE on that: `apb_gpio_0001` (one genuinely 1-bit port that
    # now honestly reports a gap) and `modified_booth_mul_0002` (phantom ports
    # parsed out of a results-table header, given a fake width so the record
    # could score complete). 226 is the honest count. Kept EXACT, not relaxed to
    # `>=`, so the next drift is caught the same way this one was.
    #
    # 226 -> 233 (2026-08-26, commit 11bb1cde7, "the four clusters' fixes, and
    # the corpus number the reader chain actually earns"). THE CORPUS DID NOT
    # MOVE. This is the entry that changed the SHAPE of the expectation, so it
    # is worth stating why. The red read as "the corpus grew" — and one record
    # really did grow, `data_bus_controller_0001` gaining `m1_ready`/`s_ready`.
    # But it is COMPLETE on BOTH arms and contributes ZERO to the delta: it
    # gained those ports from the NEW PROSE READER, over the same bytes. The
    # two-arm control settles it — the identical on-disk dataset scores 226
    # under the `fe27b28b7` tree and 233 under this one, so the code moved and
    # the corpus is a constant. 11bb1cde7 measured both arms in its own commit
    # message (226/3/73 vs 233/3/66) and moved the number THERE but not here,
    # which is how main was left red for five days.
    #
    # The number is therefore no longer typed in this file. It is
    # `len(census["complete_ids"])` over `cvdp_complete_census_baseline.json`,
    # which pins the CORPUS IDENTITY beside the MEMBERS it produced — the two
    # facts whose absence made this red unreadable. The arrivals (7, and 0
    # departures — a strict superset) are adjudicated there, 5 earned and 2 not;
    # the 2 that are not earned are held by
    # `test_cvdp_complete_verdict_is_never_degenerate` below, because a count
    # cannot tell a recovery-improvement from a recovery-regression and this one
    # was both at once.
    #
    # RATCHET — EXACT SET, both directions, deliberately NOT `>=`. This
    # population is not monotone-up and must not be made so: 228 -> 226 was an
    # honest DROP that removed two false COMPLETEs, and repairing the two
    # quarantined records would honestly drop 233 -> 231. `>=` would have let
    # every one of those bugs ride.
    missing = sorted(pinned - measured)
    extra = sorted(measured - pinned)
    assert measured == pinned, (
        f"CVDP COMPLETE (prompt+context only) is {len(measured)}; the census "
        f"record pins {len(pinned)}. Records the record expects that this tree "
        f"no longer resolves ({len(missing)}): {missing}; records this tree "
        f"resolves that the record does not know ({len(extra)}): {extra}. The "
        f"corpus is already proven identical, so this is the READER CHAIN. "
        f"Adjudicate each id from input.prompt only (§4.05) and re-derive "
        f"{_CENSUS.name} — a count edited to match is not a measurement.")
    # §4.05: the cocotb harness signal-set block is NO LONGER re-attached; the
    # supplied (prompt+context) interface is echoed in `interface_source` instead.
    s = C.extract(recs[0])
    assert "harness" not in s, "the OFF-LIMITS cocotb harness block must not be re-attached"
    assert "interface_source" in s


def test_cvdp_complete_verdict_is_never_degenerate():
    """A COMPLETE verdict must describe a module someone could actually write.

    The count above cannot express this. It rose 226 -> 233 while carrying, in
    the same move, two records that score COMPLETE on an interface with nothing
    coming in or nothing going out: a decoder recovered as `{i_clk, i_rstb}` —
    clock and reset, zero outputs, while its prompt declares `i_binary_in` and
    `o_one_hot_out` WITH widths — and a GCD recovered as one output and no
    inputs. Both are prompt-stated facts that were missed, i.e.
    INCOMPLETE_EXTRACTION_GAP, not COMPLETE. A count is blind to the difference
    between recovery-improvement and recovery-regression, and 226 -> 233 was
    both at once: +5 earned, +2 not.

    So the count is paired with a floor on the SHAPE of what it counts. The
    floor is structural and name-free (see `_is_degenerate`) and it is a
    QUARANTINE, not a licence: the record lists the 3 known-degenerate ids with
    the reason each is wrong, MAY ONLY SHRINK, and the target is 0. Repairing
    the reader chain is a behaviour change with its own corpus-sweep acceptance
    burden — it would move 233 -> 231 — and is deliberately NOT folded into a
    criterion fix. What this test guarantees meanwhile is that the number can
    never again ratchet a new false COMPLETE in silently.
    """
    recs, census = _cvdp_corpus()
    quarantined = set(census["degenerate_complete"]["ids"])
    measured = set()
    for r in recs:
        s = C.extract(r)
        if s["completeness"] == "COMPLETE" and _is_degenerate(s):
            measured.add(r["id"])
    arrived = sorted(measured - quarantined)
    assert not arrived, (
        f"NEW false COMPLETE ({len(arrived)}): {arrived}. Each scores COMPLETE "
        f"on an interface with no input or no output, so no module can be "
        f"written from it. Either the reader chain regressed, or the verdict "
        f"is right and `_is_degenerate` is too coarse for a shape this corpus "
        f"has now grown — argue which in {_CENSUS.name}. This quarantine may "
        f"only SHRINK; adding a row to make this pass is the failure it exists "
        f"to catch.")
    departed = sorted(quarantined - measured)
    assert not departed, (
        f"{_CENSUS.name} is STALE: {departed} no longer score COMPLETE on a "
        f"degenerate interface. That is the outcome this quarantine wants — "
        f"delete the row(s) so the record states what is true. Reported as a "
        f"failure and not passed over so the floor cannot drift upward by "
        f"accumulating rows nothing measures.")
