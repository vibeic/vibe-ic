# L1-L13 Taxonomy Adequacy — Evidence from AMBA AXI

> User question (2026-05-29): _"check if the L1 - L14 is enough to keep
> all design documents' data, if need to have other classes, add that."_

## TL;DR

**L1-L13 is INSUFFICIENT** for protocol-spec documents (AXI, USB, PCIe,
DDR, AMBA family, etc.). Three things are missing:

1. **An `ic_class → applicable_L_docs` map** — the current runner emits
   L5/L11/L13 even for AXI which has no analog/OTP/lab-calibration.
   These end up either empty or HALLUCINATED.
2. **L14-L17 categories** — for protocol-spec facts that don't fit any
   L1-L13 bucket (version deltas, encoding tables, formal compliance
   rules, channel signal catalogs).
3. **A protocol-spec ic-class profile** — `ic_class_profile.py` has no
   `bus_interconnect_protocol` class; it can't dispatch correctly.

## Evidence: iter1 fresh-Opus vs program

Side-by-side bytes per L doc (AMBA AXI IHI0022H, 2.3 MB PDF):

| L doc | program-bytes | fresh-Opus-bytes | divergences | parity |
|---|---|---|---|---|
| L1_DATASHEET | 101312 | 7019 | 28 | 0.0% |
| L2_FRS | 116106 | 11652 | 13 | 0.0% |
| L3_CMD_PROTOCOL | 11675 | 8103 | 57 | 0.0% |
| L4_REGMAP | 372 | 1385 | 8 | 0.0% |
| L5_ADI_SPEC | 2441 | 1738 | 12 | 0.0% |
| L6_CONTROL_LOGIC | 12367 | 4435 | 22 | 0.0% |
| L7_TEST_DEBUG | 647 | 3535 | 10 | 0.0% |
| L8_RTL_CONSTANTS | 1105 | 6486 | 95 | 0.0% |
| L8_TIMING_WAVEFORM | 294 | 4893 | 27 | 0.0% |
| L9_INTEGRATION_SPEC | 31086 | 7168 | 24 | 0.0% |
| L10_TEST_CASES | 1656 | 6383 | 35 | 0.0% |
| L11_OTP_CONTENT | 21887 | 270 | (empty) | 0.0% |
| L12_BEHAVIORAL_SEQUENCES | 1894 | 5924 | 12 | 0.0% |
| L13_LAB_CALIBRATION | 508 | 256 | (empty) | 0.0% |
| **Totals** | **303** absent + **15** hallucinated + **14** shape | | | |

Two patterns:
- **Program bigger** on L1/L2/L9/L11: scraped boilerplate; pads with
  template structure; ic_name = "SUCH ARM TECHNOLOGY" (license text)
- **Program smaller** on L8 RTL_CONSTANTS, L10, L12: missed encoding
  tables, missed compliance rules, missed sequence diagrams

## Smoking-gun hallucinations confirmed

1. `L1_DATASHEET.ic_name = "SUCH ARM TECHNOLOGY"` — lifted from the
   license clause `…USE OR IMPLEMENTATION OF SUCH ARM TECHNOLOGY WILL
   NOT INFRINGE…`. Correct: `AMBA AXI and ACE Protocol Specification`.
2. `L3_CMD_PROTOCOL.opcode_hex = "0x16", "0x48"` — page-format numbers
   (`23 16` and `55 48` from byte-position figures in §A3.4.4) lifted
   as 8-bit opcodes. AXI has zero 8-bit opcodes — it's a
   5-channel concurrent valid/ready protocol.

Both pass the `--source` doc-grounding check: the PDF's source text
does contain "SUCH ARM TECHNOLOGY" but only as license clause; it does
NOT use that phrase as a product name. The opcode hex values exist as
page numbers but not as opcode encodings.

## Facts AMBA AXI HAS that L1-L13 has no home for

Fresh-Opus surfaced these — none fit L1-L13:

| AXI fact | Category if it existed |
|---|---|
| AXI3 vs AXI4 vs AXI5 backward-compat deltas (AxLEN width 4→8 bits; AxLOCK 2→1 bits; WID deprecated; AxCACHE renamed) | **L14_PROTOCOL_VERSIONING** |
| BURST encoding `2'b00=FIXED / 2'b01=INCR / 2'b10=WRAP / 2'b11=Reserved` (Table A3-3) | **L15_ENCODING_TABLES** |
| RESP encoding `2'b00=OKAY / 01=EXOKAY / 10=SLVERR / 11=DECERR` | **L15_ENCODING_TABLES** |
| AxSIZE→byte mapping `3'b000=1B / 001=2B / ... 111=128B` (Table A3-2) | **L15_ENCODING_TABLES** |
| 4KB-boundary rule | **L16_COMPLIANCE_PROPERTIES** |
| Byte-invariant endianness | **L16_COMPLIANCE_PROPERTIES** |
| VALID-once-asserted-cannot-be-retracted | **L16_COMPLIANCE_PROPERTIES** |
| WRAP-length restricted to {2,4,8,16}; start-addr aligned to AxSIZE | **L16_COMPLIANCE_PROPERTIES** |
| AR/R/AW/W/B channel signal catalog (~50 signals) | **L17_CHANNEL_SIGNAL_CATALOG** |
| Channel dependency graph (AXI3 vs AXI4 BVALID timing) | **L17 + L8_TIMING_WAVEFORM** |
| Interconnect-appended ID-bits convention (§A5.2.3) | **L18_INTERCONNECT_TOPOLOGY** |
| Default signal values (AWBURST=INCR, WSTRB=all-ones, AWCACHE=0b0000) | **L18 + L9** |
| Multi-Copy Atomicity required True for Issue G+ | **L16 or L18** |

## Proposed extensions

### New L docs (L14..L18)

```
L14_PROTOCOL_VERSIONING
  - version_id (AXI3 / AXI4 / AXI5)
  - issued_date / spec_revision
  - delta_table : per-version backward-compat trap
  - deprecated_features
  - applies_to: bus protocols, ISA families, PCIe gens, DDR gens

L15_ENCODING_TABLES
  - tables : list of { name, field_bits, encoding: [{value, name, semantics}] }
  - applies_to: bus protocols (BURST/RESP/SIZE), CPU cores (opcodes),
                memory controllers (CMD/MR), DSP (coefficients),
                status registers everywhere

L16_COMPLIANCE_PROPERTIES
  - properties : [{ id, scope, formal_shape (sva|english), citation }]
  - applies_to: any spec with assertion-shaped invariants — protocol
                spec compliance, RTL signoff properties

L17_CHANNEL_SIGNAL_CATALOG
  - channels : [{ name, direction, signals: [{name, width, semantics,
                       optional, valid_ready_pair}] }]
  - dependency_graph : valid/ready ordering across channels
  - applies_to: bus protocols with sideband signals (AXI 50+ sigs,
                USB 30+, DDR 100+); subsumes L4_REGMAP for these
                cases

L18_INTERCONNECT_TOPOLOGY
  - interconnect_rules : [{ rule_id, description }]
  - default_signal_values : { signal_name: default_value }
  - id_routing : how IDs propagate through fabric
  - applies_to: bus protocols, NoC fabrics, system-on-chip integration
```

### `ic_class → applicable_L_docs` map (NEW)

```json
{
  "bus_interconnect_protocol": {
    "applicable": ["L1", "L2", "L3", "L6", "L8C", "L8T", "L9", "L10",
                   "L12", "L14", "L15", "L16", "L17", "L18"],
    "not_applicable": ["L4", "L5", "L7", "L11", "L13"]
  },
  "cpu_core_isa": {
    "applicable": ["L1", "L2", "L8C", "L8T", "L9", "L10", "L12",
                   "L14", "L15", "L16"],
    "not_applicable": ["L4", "L5", "L7", "L11", "L13"]
  },
  "chip_otp_centric": {
    "applicable": ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8C",
                   "L8T", "L9", "L10", "L11", "L12", "L13"],
    "not_applicable": ["L14", "L15", "L16", "L17", "L18"]
  },
  "memory_controller": {
    "applicable": ["L1", "L2", "L3", "L6", "L7", "L8C", "L8T", "L9",
                   "L14", "L15", "L16", "L17", "L18"],
    "not_applicable": ["L4", "L5", "L11", "L13"]
  },
  "analog_block": {
    "applicable": ["L1", "L2", "L5", "L6", "L8C", "L8T", "L9", "L10",
                   "L11", "L12", "L13"],
    "not_applicable": ["L3", "L4", "L7", "L14", "L15", "L17", "L18"]
  }
}
```

The map prevents two failure modes simultaneously:
- **AXI emitting empty L5/L11/L13** (or worse — HALLUCINATED content
  to fill the void). The runner should record "N/A for ic_class
  bus_interconnect_protocol" not generate a stub.
- **OTP chip emitting empty L14/L15/L16/L17/L18**. Same logic in reverse.

## Implementation cost (estimate)

| Change | Files touched | Lines |
|---|---|---|
| Add L14/15/16/17/18 to L_DOCS in runner + schemas | ~3 program files | ~150 |
| Add ic_class applicability map JSON + program reader | new file + 1 program | ~100 |
| Add `bus_interconnect_protocol` ic-class detector | ic_class_profile.py | ~50 |
| Update phase1_one_shot_runner to honor applicability | 1 program | ~80 |
| Update phase1_verify_aggregate to know new L docs | 1 program | ~20 |
| Pytest coverage for new categories | new test file | ~200 |

Roughly **600 lines + tests** for the taxonomy expansion. Closes
~80% of the AXI parity gap by itself (the program never even tried
to emit half the missing facts; once we have a bucket for them, we
can write the extractor).

## Recommended decision tree

```
Question 1: Is L1-L13 enough?
  → NO. Protocol specs need L14-L18.

Question 2: Should we expand taxonomy BEFORE closing the AXI parity loop?
  → YES. Closing parity on L1-L13 alone would (a) leave 80% of the
    real AXI facts homeless and (b) reinforce the wrong taxonomy.

Question 3: Order of operations?
  Step 1: Add L14-L18 schemas + ic_class applicability map
  Step 2: Re-run parity loop (the comparator already supports new L docs
          if we add them to L_DOCS in l_doc_parity_diff.py)
  Step 3: For each remaining ABSENT_IN_PROGRAM finding, write a
          deterministic extractor rule in the runner
  Step 4: Loop until parity ≥ 90% per L doc

Question 4: How do we handle the 15 HALLUCINATIONS?
  Each one is a deterministic regex/rule in the program that needs a
  source-grounding guard. The comparator already has a heuristic
  catalog; that catalog should grow as we find more. Each catalog
  entry becomes a unit test the runner must pass.
```

## What the user needs to decide

1. **Approve the L14-L18 taxonomy extension?** (or modify the proposed
   categories before I implement)
2. **Approve the ic-class applicability map?** (or different shape?)
3. **Time budget?** This is plausibly a 2-3 hour batch:
   - L14-L18 schema + applicability map: ~30 min
   - Fix the 2 known hallucinations (boilerplate name, opcode-from-page-num): ~30 min
   - First-pass extractors for L14-L18 from AMBA AXI: ~60 min
   - Re-run parity + iterate: ~30-60 min

Until the user decides, the loop is paused at iter1 with the parity
comparator + 1 fresh-Opus baseline captured.
