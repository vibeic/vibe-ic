# LAND — staged verification hands the path lint the REAL project root (fix 5)

## What
- `analog_netlist_path_lint.py`: `--project-root` (and run_audit real_root=) —
  containment for the project-internal rung is judged against the named REAL
  project instead of the audited directory, for callers auditing a staging copy.
- `analog_a3_netlist_emit.py`: `verify_with_checkers` gains real_project= and
  passes `--project-root <project>` to the path lint; the emit call threads it.

## Why (measured, u_hawaii_adc round-5b @ v1.14.47 — ONE round after v1.14.47's rung)
A3 verifies its render inside a TemporaryDirectory; the v1.14.47 containment rung
therefore tested /tmp/a3verify_* and the deck's CORRECT binding of the real
project's input/pdk/models/<lib> still read as foreign — same dead-end
(NETLIST_REJECTED_BY_CHECKS -> WAIVE -> A4 blocked), one directory level deeper.

## Falsification (two-tree, base v1.14.47 0c1884ac4)
- pre-fix: 3 RED (flag arm, foreign-path-with-flag arm, A3 integration) +
  1 GREEN (no-flag staging refusal pin, held).
- post-fix: 4/4 new + 8/8 existing path-lint suites GREEN (12/12).

## Doctrine
Chip-AGNOSTIC. The no-flag behavior is unchanged (a staging tree with no named
real root refuses as before); an out-of-root path with the flag still refuses.
Do not land from here — gatekeeper review.
