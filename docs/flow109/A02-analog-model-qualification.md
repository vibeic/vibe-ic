# A02 analog model qualification component

The general flow entry dispatches `flow109_analog_a02.execute` only for an
explicit A02-to-A02 window. The adapter records the existing
`pdk_analog_completeness_check` inventory result, but accepts neither that
check's file existence alone nor its waiver path as model qualification.

`input/flow109/A02.json` declares a SHA-bound PDK description (including the
exact inventory file for every completeness-check axis), independently
approved requirements, and the exact model, corner, device, deck, and native
measurement names for every required smoke. The initial bounded scope accepts
only self-contained model files and decks: transitive includes, control-shell
commands, inferred corner discovery, topology selection, and sizing are
refused. Requirements need `APPROVED` status, `requirements_owner` authority,
and a source reference. The manifest's smoke set must exactly equal that
frozen requirement set.

Every launch rechecks current qualification, source closure, configuration,
PDK, requirement, model, deck, corner, executable, and input identities.
Actual `ngspice -b` output is retained per smoke. The current consumer requires
return code zero, no fatal model/elaboration diagnostic, and exactly one finite
value for every declared `.measure`; it re-hashes the model, deck, and log
before publication. Missing/stale/unsupported authority refuses before native
launch, while a broken declared model is a native component failure.
The accepted model/deck bytes are copied into the unique attempt and the deck
is rebound to that immutable model copy before ngspice starts. Native runs use
the repository's no-progress supervisor; a stalled smoke is NOT_MEASURED.

A component PASS publishes a hash-bound freeze for the declared model/device
scope only. Both A02 obligation bindings, every G1-G9 dimension, whole-row
acceptance, production-PDK signoff, and benchmark qualification remain
**NOT_MEASURED**.
