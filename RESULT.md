# Native Yosys Step14 handoff

Fix commit: `40675b478f0ee609fac6fb6c4767d1cdded65cc2`

Parent: `f4eed5fa5ba36fb08936ef402abe7538592238de`
Tree: `802ff0f2c98c06da08713367cbb43b001045ffa5`
Branch: `next/native-pyosys-101010`

The native producer now adds the current `COMMANDS` digest to every new
`Yosys.Synthesis` receipt at the existing `librelane_contract.run_chain`
receipt seam. The Step14 consumer recognises LibreLane's direct
`yosys -y .../synthesize.py -- --config-in ...` invocation only when the
receipt binds `COMMANDS`, `invocation.log`, `config.json`, and `extra.json`.
It judges pass order from the receipt-bound executed Yosys log, using the
bound synthesis config to resolve `setundef -zero`; wrapper names or copied
source text cannot certify order. Old receipts without `COMMANDS` stay
`NOT_CHECKED` and are never retrofitted.

The retained native evidence is:

`/home/reyerchu/codex_tasks/runs/subservient-librelane-local-r1/native-project-r2/phase3/librelane/02-yosys-synthesis/{COMMANDS,invocation.log,config.json,vibeic_receipt.json}`

That receipt currently lacks `sha256.COMMANDS`, so the checker correctly
reports `NOT_CHECKED` (`native_receipt_without_recipe`). Reading its existing
log directly identifies one real violation: `OPT_CLEAN` after `HILOMAP`.
The pinned image's executed source is
`/usr/local/lib/python3.12/dist-packages/librelane/scripts/pyosys/synthesize.py`
(sha256 `b37a0d1042f9972fd704a4321d8f6331ec0f397f13d0942734f892eec3913327`)
from image
`ghcr.io/vibeic/vibeic-eda@sha256:79957120d37804ae0d23144307c5c166dcb609831326f19f2edb8729fe807cfe`.
No 8HD-D files or external fork sources were changed; the producer hook is
the plugin's existing `librelane_contract.py` seam.

Validation:

- Host focused run: **103 passed** across the checker, Step14 receipt, and
  LibreLane contract modules.
- Pinned image (`--skip`, 4 CPUs, 8 GiB): **36 passed** for the checker,
  Step14 receipt, and synthesis receipt-binding test; Step14 wiring control:
  **5 passed**.
- The broader pinned LibreLane contract module had 3 unrelated LOCAL-provider
  failures because bubblewrap user namespaces are unavailable in this image;
  those failures are environmental, not this change.

Remaining blocker: a fresh native synthesis must run with this producer to
publish a `COMMANDS`-bound receipt before Step14 can measure the retained
8HD-3 run. This branch does not claim native or whole-flow PASS.
