# Structured macro and clock declarations

Phase-1 documents may include a `json` fence containing the existing L9/L8
container names. `tests/fixtures/phase1_local/macro_clock_contract/contract.md`
is a neutral example: a regulator supplies an integrator over a declared
internal net, with two explicitly related clocks.

- `analog_blocks`: each block supplies `type` and an explicit `instances` list.
  Alternatively, `instances` may appear at the root, with each row declaring
  `name`, `block_type`, and `ports`.
- Each port declares `name`, `type`, `direction`, and `net`. Supported types are
  analog, digital, power, ground, clock, and reset; directions are input, output,
  and inout. Nets must resolve to a declared top port, internal wire, or `nets`
  entry. A `nets` entry is a name string or an object with `name`.
- `clock_groups`: each row declares `name`, a list of at least two distinct
  `clocks`, and `relationship` (synchronous, asynchronous, or exclusive).

The normal L9 emitter produces typed `ports`, `port_map`, `connections`, and
`internal_wires`. Only explicitly supplied `master` and `placement` fields
are forwarded. No physical view, location, regulator terminal identity, or
clock relationship is selected from a macro or net name. Clock-group data
alone does not authorize SDC timing cuts.

Missing or conflicting declarations leave named records in
`declared_instance_refusals` or `declared_clock_group_refusals`. Conflicting
identities are removed, rather than selecting the first or last declaration.
L5 blocks whose typed instance count is incomplete also receive an unresolved
record; a block count alone cannot create an instance name or terminal map.
Existing document-table and timing extraction behavior remains supported.
This addition projects structured fields without extending prose inference.
