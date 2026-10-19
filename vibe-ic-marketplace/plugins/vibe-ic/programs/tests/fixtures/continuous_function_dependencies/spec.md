# Mutable dependency specification, frozen before owner implementation

A combinational continuous-call result must observe an input lifecycle change
even when its explicit enable argument stays constant. In the neutral executable
example, enable=1 selects phase 2 until done_a=1, then phase 3 until done_b=1,
then phase 15. A hidden module-state read and an explicit-input implementation
use the identical assertions. No algorithm or external expected-value model is
needed. Icarus must execute the before/after control; compiler success alone is
insufficient.

The existing hygiene owner must diagnose a continuous RHS function whose
resolved mutable module reads are absent from the call's explicit arguments.
Resolve direct reads and unambiguous same-module helper calls. Exclude formal
arguments, function locals, return names, parameters, localparams and enum
constants, strings/comments, field identifiers and sibling-module declarations.
An explicit mutable actual argument already supplies that dependency and must
not be flagged. Procedural always_comb calls are outside this rule.

Recursion, unknown callees, duplicate definitions, macros and unresolved scope
are incomplete analysis, not clean proof and not an automatic rewrite permit.
Keep their limitation visible without installing a new global gate. The rule
must not rewrite arbitrary function signatures or call sites during --fix.
