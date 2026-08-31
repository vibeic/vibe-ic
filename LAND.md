# LAND — path lint accepts the project's own staged PDK copy (u_hawaii_adc fix 4)

## What
`analog_netlist_path_lint.py`: `_is_whitelisted` gains a project-internal rung —
an absolute include that resolves INSIDE the project tree is accepted and STATED
(new INFO finding `PROJECT_INTERNAL_ABSOLUTE_PATH`), never silent. Canonical
/foss/pdks/ unchanged; any absolute path outside both stays refused (pin held).

## Why (measured, u_hawaii_adc round-5 @ v1.14.46)
Two shipped rules force the binding this lint refused:
`pdk_analog_completeness_check` REQUIRES input/pdk/** (a run stands on input/
alone) and the availability resolver PREFERS the staged copy, so A3 binds
`<project>/input/pdk/models/<lib>` — then this lint rejects the render
(NON_WHITELISTED_ABSOLUTE_PATH x3), A3 dead-ends in NETLIST_REJECTED_BY_CHECKS
-> WAIVE, A4 blocked. An author obeying both rules had no legal output: a
completeness gate and a portability lint enforcing OPPOSITE bindings.

## Falsification (two-tree, base v1.14.46 8c4e4c5ff)
- pre-fix: positive arm RED (staged-copy deck refused), foreign-path + canonical
  pins GREEN.
- post-fix: 3/3 new + existing test_analog_netlist_path_lint 5/5 GREEN.

## Doctrine
Chip-AGNOSTIC (path containment vs the project root; no PDK/vendor literal).
Degrades loudly (INFO marker on every accepted project-internal binding).
Do not land from here — gatekeeper review.
