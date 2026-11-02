# Structured macro and clock declarations

Phase-1 documents may include a `json` fence containing the existing L9/L8
container names. `tests/fixtures/phase1_local/macro_clock_contract/contract.md`
is a neutral example: a regulator supplies an integrator over a declared
internal net, with two explicitly related clocks.

- `analog_blocks`: each block supplies `type` and an explicit `instances` list.
  Alternatively, `instances` may appear at the root, with each row declaring
  `name`, `block_type`, and `ports`. Nested instances retain the enclosing
  declared `block` name. Root instances may supply the same explicit `block`
  reference; `block_type` alone never establishes block membership.
- Each port declares `name`, `type`, `direction`, and `net`. Supported types are
  analog, digital, power, ground, clock, and reset; directions are input, output,
  and inout. Nets must resolve to a declared top port, internal wire, or `nets`
  entry. A `nets` entry is a name string or an object with `name`.
- `clock_groups`: each row declares `name`, a list of at least two distinct
  `clocks`, and `relationship` (synchronous, asynchronous, or exclusive).

Tables and JSON must agree on every port name, type, direction and resolved
net. Incomplete table ports and conflicting sources leave a named refusal and
remove that instance and its wires. Port order and evidence formatting do not
change the typed contract.

The normal L9 emitter produces typed `ports`, `port_map`, `connections`, and
`internal_wires`. Only explicitly supplied `master` and `placement` fields
are forwarded. No physical view, location, regulator terminal identity, or
clock relationship is selected from a macro or net name. Clock-group data
alone does not authorize SDC timing cuts.

Missing or conflicting declarations leave named records in
`declared_instance_refusals` or `declared_clock_group_refusals`. Conflicting
identities are removed, rather than selecting the first or last declaration.
L5 blocks whose declared instances are missing also receive an unresolved
record, naming the missing instance when its identity is declared. Coverage
uses explicit instance identities or block membership, never a shared type
count. An instance requested by two blocks covers neither.

Clock relationships require an explicit group name in JSON or a structured
table. The emitters do not create clock groups from prose or generate group
names. Prose-only relationship statements remain named unresolved evidence.
