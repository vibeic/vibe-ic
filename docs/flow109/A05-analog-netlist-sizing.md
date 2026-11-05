# A05 expert-sized netlist and native operating point

`--entry-step A05 --exit-step A05` consumes current A02 and A04 receipts, an
independently approved sizing/threshold declaration, and the exact typed
model/corner scope. It supports self-contained, project-local model libraries
and explicit `op` testbenches. Unknown, transitive, stale, foreign or
unqualified model dependencies fail closed.

The adapter requires every approved W/L/m value to match the current A04
topology IR, runs the existing `analog_a3_netlist_emit` and retained A3 reader,
checks that substantive device, power/body connectivity and exact corner/model
loads survived, snapshots the complete read set, and runs that snapshot with
native ngspice. A zero exit code alone is insufficient: every approved
operating-point measurement must be present, finite and within its positive
source-owned bounds.

The supported subset does not measure AC gain/noise, transient behavior,
PVT/statistics, G1-G9, full flow qualification, production-PDK signoff or
benchmark PASS. Those remain `NOT_MEASURED`.
