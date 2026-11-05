# Native mixed-signal M3/M4 programs

The analog and mixed-signal native programs remain available while their
rows are being connected to the general runner's tool adapters.

`mixed_signal_m3_run PROJECT --top TOP --json AUDIT` runs the declared L22
scenarios when `input/mixed_signal/native.json` supplies supported native
inputs. Icarus runs the actual digital wrapper, ngspice measures the analog
response, and a second wrapper run consumes the measured feedback. Supported
post-layout interfaces use the extracted circuit, routed SPEF and the actual
PDK driver models. OpenSTA measures interface timing when its inputs exist.
Without supported native inputs the program writes NOT_MEASURED results.

Receiver-noise declarations contain a model path, a list of dependency paths,
the two-port subcircuit, bias, temperature, frequency band and numeric criteria.
Ngspice supplies the complete frequency spectrum and integrated noise scalar;
the reader checks the grid and independently integrates the spectrum. The
original limits and the 8 GiB native memory ceiling remain unchanged.

The program writes the co-simulation result, interface SI result and
`reports/analog/mixed_signal/m3_run.json`. That ordinary run report records
native output paths and tool exit codes. Readers recompute measurements from
the native outputs. There are no input/output hash rosters, model hashes,
receipt identity checks or timestamp qualification. Missing measurements
remain NOT_MEASURED and measured failures remain FAIL. Component results
retain their declared scope and do not establish full-design coverage.

`mixed_signal_signoff_run PROJECT --top TOP --json AUDIT` runs the merged-top
physical checks and derives readiness from M1, native M2 structural results,
M3 co-simulation and interface measurements, and actual DRC/LVS/antenna/density
counts. Each required physical count retains its original zero limit. Missing
required native data prevents readiness. A passing M2 structural result alone
does not establish electrical or dynamic behavior.

`--check-only` reads existing native results without running tools. Audit
outputs cannot overwrite design inputs or native results. M4 recomputes its
readiness from the native measurements; it does not compare cached signoff
hashes or use a previous readiness assertion as an input.
