# Professional byte-memory signature cases

The Tier3 professional expert hook can verify an explicitly declared L10
memory-signature case. An arbitrary expert hook is not automatically classified
as a memory-signature model. The generator does not infer expected memory values
or memory port roles from Python source, port names, or testbench filenames.

Keep the existing `L10_TEST_CASES.json` case list and author this typed category
from design INPUT. For example, `fields.test_cases` can contain:

```json
{
  "id": "signature_result",
  "category": "memory_signature",
  "interface": {
    "clock": "clk",
    "edge": "posedge",
    "write_enable": "wr",
    "active_level": 1,
    "write_address": "addr",
    "write_data": "data"
  },
  "expected_bytes": {"32": 0, "33": 0, "34": 0, "35": 0}
}
```

`id` names the same expert `@cocotb.test()` coroutine. `expected_bytes` is a
nonempty map of decimal **byte addresses** to integer byte values0..255.
Zero is an expected result. This map is separate from the existing `expected`
field, whose numeric vector semantics bind values to top-level output ports.
Duplicate numeric addresses, unknown roles, unresolved widths, and missing
expectations are refused.

The supported interface is synchronous external byte storage: at each declared
clock edge it commits the transaction present immediately before DUT sequential
updates. The clock is a real one-bit L9 input at the current selected edge;
write-enable is a one-bit L9 output with declared active level0 or1; write-data
is an eight-bit output; write-address is an unsigned concrete byte-address
output. Other protocols, handshakes, masks, and wider writers are not measured
by this observer and are refused rather than truncated.

Author the behavioral stimulus, actual external memory model, completion, and
final memory comparisons in `expert_reference_tb.py`. `professional_tb_gen`
preserves that authored file and generates a portable wrapper around each
selected coroutine. The wrapper observes the declared clock/write/address/data
ports, records actual committed bytes, and asserts that every expected address
received a write and its last committed byte equals the unchanged expectation.
Keep final memory comparisons: the observer supplements the expert reference.

The original Step4 runner executes the bundle under Icarus/cocotb. Missing zero
stores, partial stores, redirected addresses, and wrong data fail native JUnit
and the original professional consumer. The consumer also requires the current
typed contract, passing native JUnit, and the matching per-case observation.
Absent/incomplete contracts or observations return NOT_CHECKED/rc2; the runner
returns NOT_MEASURED for a contract it cannot resolve before launch.

For each model, retain a complete-write positive execution and actual omitted-
store controls, including zero-valued bytes. The neutral regression uses the
original producer, native simulator, and consumer. This capability does not
claim full instruction-set coverage, reset retention, original issue owner
validation, or physical signoff. Non-memory classes retain their existing
reference contract; unclassified expert hooks carry no signature-verification
claim.
