#!/usr/bin/env python3
"""The L8_TIMING_WAVEFORM schema, as the emitters write it (R-0915-153).

WHY THIS EXISTS. `internal_vs_external_timing_check` certifies "this L8 carries
no half-duplex protocol timing" (NOT_APPLICABLE_BY_STRUCTURE). Three rounds of
deciding that by WORDS (key-name tokens, then a whole-document probe) traded a
false FAIL for a false NABS each time. R-0915-153 decides it by SCHEMA: the
escape fires only when the protocol-timing containers are empty AND every other
top-level key is one an emitter declares NON-protocol. An unknown key is not
evidence of absence, so the gate's own check() runs (fail closed).

WHERE EACH NAME COMES FROM. Keys are imported from the emitter that writes them
wherever that emitter names them; the rest are the literal keys of the base
emitter's own document (`phase1_doc_one_shot_runner.gen_l8_timing_waveform_doc`
and `_write_l_doc`). `test_l8_timing_schema_is_the_emitters` runs those emitters
and fails if they write a key this module does not declare.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import l_doc_generator_stamp as _stamp          # noqa: E402  `_generator`
import l8_clock_reset_waveform_emit as _crw      # noqa: E402  clock/reset view
import l8_doc_clock_freq_synth as _clk           # noqa: E402  clock records

#: Containers that CARRY protocol timing when non-empty
#: (`gen_l8_timing_waveform_doc`: the three canonical lists, plus the RX/TX
#: `timing_groups` and its `symbol_directionality`, which it pops to the root).
PROTOCOL_TIMING_CONTAINERS = ("timing_windows", "timing_constants", "waveforms",
                              "timing_groups", "symbol_directionality")

#: Keys an emitter declares carry NO protocol timing.
NON_PROTOCOL_KEYS = frozenset({
    # identity — gen_l8_timing_waveform_doc
    "schema_version", "doc_class", "ic_name",
    # provenance — _write_l_doc, and the generator stamp
    "extraction_evidence", "source_documents", "source_documents_derivation",
    _stamp.STAMP_KEY,
    # clocking — l8_doc_clock_freq_synth and l8_clock_reset_waveform_emit
    *_clk._CLOCK_LIST_KEYS, _clk.SCALAR_KEY, _crw.L8_KEY,
    "clock_groups",  # explicit clock relationships, not protocol timing
    "reset_strategy",  # declared startup/reset transport, not protocol timing
    # IC class tag — the phase-1 class detector
    "class_path",
})

#: The keys whose VALUE names a row of a protocol-timing table (its identity
#: label). MEASURED over the 101 corpus L8s: list records lead with `name`
#: (215), `parameter` (22) and `field` (7); `symbol` / `signal` are the WaveDrom
#: and per-symbol spellings. `literal`, `source`, `extraction_strategy` are
#: provenance, not identity. ONE definition, read by the step-2 gate's family
#: detector (R-0915-164, review w0z2lp3a7).
RECORD_LABEL_KEYS = ("name", "symbol", "signal", "parameter", "field")
