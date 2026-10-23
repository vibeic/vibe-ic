# Default analog A01–A19 execution

The analog rows in `flow/flow109.json` dispatch to the existing native
producers through `programs/analog_native_flow.py`. Both front doors use the
same implementation:

```sh
python3 programs/analog_one_shot_runner.py /path/to/project \
  --flow 109 --entry-step A01 --exit-step A19 \
  --pdk ihp-sg13g2 --container my-eda --execution-workers 2

# A bounded post-layout statistical execution; count is per RC style.
python3 programs/analog_one_shot_runner.py /path/to/project \
  --flow 109 --entry-step A15 --exit-step A15 --blocks regulator \
  --post-mc-samples 2 --pdk ihp-sg13g2 --container my-eda

python3 programs/vibe_ic_one_shot_runner.py /path/to/project \
  --flow 109 --flow109-manifest /path/to/project/manifest.json \
  --entry-step A04 --exit-step A07 --route ic --container my-eda
```

The whole-flow front door requires its existing resolved feature manifest.
Its windows follow the complete flow's interleaved row order: a window from
A01 to A19 also selects digital and mixed-signal rows. Use the analog runner
for an analog-only A01–A19 pass, or select a contiguous analog window through
the whole-flow front door.
Native analog execution does not require a tool qualification registry.
Other flow owners retain their own admission behavior. The legacy A1–A9
runner remains available with `--flow 70` (the default).

Use the project's existing `phase3/analog/analog_block_list.json`, L-docs,
per-block `spec.json`, `topology.json`, netlist and testbench. Optional
execution settings belong in `input/analog_flow.json`:

```json
{
  "pdk": "ihp-sg13g2",
  "container": "my-eda",
  "workers": 2,
  "features": {
    "analog_testability": false,
    "analog_trim": false,
    "analog_statistics": true,
    "digital_physical": true
  },
  "steps": {
    "A15": {"samples": 100}
  }
}
```

The actual container image is inspected and passed to nested native tools.
Mount the project and plugin programs at the same absolute paths inside that
container. Native commands use the image's login environment, including its
model-library search paths. Tools which launch LibreLane also need their
existing Docker access.

| Rows | Existing production work |
| --- | --- |
| A01–A05 | Specification extraction, declared model smoke decks, testability/trim applicability, topology, netlist and native OP |
| A06–A10 | DUT/testbench checks, nominal measurements, PVT, statistical models and calibration |
| A11–A16 | Layout, native DRC/LVS, PEX, post-layout measurements, post-layout statistics and supplied reliability reports |
| A17–A19 | GDS/LEF/Liberty/Verilog packaging, applicable analog top implementation and block signoff aggregation |

Each block advances through its own chain. A long simulation or missing
measurement in another block does not prevent independent work. An analog
window through the whole-flow front door uses the same block scheduler.
Native errors, simulator residual failures and measured specification
violations remain failures. Missing source measurements, reports or native
producers remain `NOT_MEASURED`; an explicit design feature can make a row
`NOT_APPLICABLE`. In particular, clean DRC/LVS does not supply missing ERC,
and Vout alone does not establish LDO dropout, Iq or PSRR.

Commands, exit codes, logs, measurements and output hashes are retained under
`reports/analog_native/run-*/`. `reports/analog_native/status.json` points to
the current accumulated state. Bounded reruns retain other rows only while
their consumed inputs and recorded outputs still match. A window's exit code
comes from that window: 0 for PASS, 1 for FAIL, 2 for NOT_MEASURED. Its results
do not establish whole-IC acceptance.

Source-owned mission decks and native thermal, EM or aging reports can be
supplied through per-step settings. Missing foundry data or unsupported
native producers are reported directly. A19 requires the actual delivery
views and prior native results; it cannot sign off an empty package.

A06/A07 can consume explicit native studies from the block's
`measurement_studies.json` (or `config.blocks.<name>.measurement_studies`):

```json
[
  {"testbench": "/path/to/source-load.sp",
   "bindings": "/path/to/op-measurements.json",
   "result": "/path/to/completed-study/result.json"}
]
```

`analog_bound_measurements.py` emits and runs the declared OP/DC/AC analysis.
The testbench owns circuit, stimulus and load; bindings select actual native
expressions, units and analysis points. A retained result is reusable only
while its DUT, model/include closure, template, bindings, generated deck,
native log and capture bytes match. Cached JSON cannot replace values from
the native transcript or hide a simulator failure. Unsupported or unmeasured
requirements remain visible even when some studies succeed.

A14 may reuse a matching OP study as PRE and derive POST from that same
template and bindings. A15 consumes those generated POST decks. This keeps
load and stimulus consistent across pre-layout, post-layout and statistical
measurements. The `--post-mc-samples` count is per extraction style and does
not itself establish statistical population coverage.

Block-subset windows retain other blocks' valid results and their original
producer context. A17 reports its actual characterization scope separately:
DC power and interface views do not establish unmeasured timing arcs.

Native operation inventory assigns each declared operation to its actual primary engine once. Python remains an admitted orchestration engine; an empty Python `engine_steps` list means that the EDA operation belongs to the named native engine, rather than counting the same operation again as Python.
