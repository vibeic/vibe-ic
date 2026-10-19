# Explicit Phase-1 interface bindings

## Layer Contract Decision

Original nominal types and logical instance counts belong in L1 as source
facts. The directed, actionable physical interface belongs in L9, whose port
arrays are consumed by conformance and the L17 port-derivation contract.
Expanding an explicitly selected request/response map and measuring a packed
type are finite structural operations, implemented by the producer. Selecting
a package configuration, correcting a source claim and specifying an adapter
are engineering decisions, preserved as input authority. Adapter behavior
still requires implementation and independent verification. The logical bus
declaration and physical member map follow the separation used by IP-XACT;
this capability does not invent a behavioral expansion or new verdict gate.

`plugin_input/interface-bindings.json` is an optional **design input**, consumed
by the normal L9 producer. It supplies a selected shared-package configuration
and explicit engineering choices; it does not supply a PASS, a tool receipt, or
an independent review. L1 remains the record of the original declarations.
Absent or uncovered bindings retain their unresolved widths and logical ports.
The existing L17 consumer remains strict.

Call `interface_bindings.input_contract(project, unbound_l9)` (or the document
runner's `--describe-interface-binding-input`) to obtain the exact current
`input_files` and `interface`. Fill these additional keys:

```json
{
  "schema": "vibeic.phase1-interface-bindings.v1",
  "input_files": {"input/docs/interface.md": "<sha256>"},
  "interface": [],
  "context": {
    "image": "ghcr.io/owner/image@sha256:<64 hex digits>",
    "revision": "<selected provider revision>",
    "files": {"plugin_input/interface_context/types.sv": "<sha256>"},
    "compile_order": ["plugin_input/interface_context/types.sv"],
    "include_dirs": [],
    "defines": [],
    "parameters": {}
  },
  "physical_ports": [
    {"name": "link_req_o", "direction": "output",
     "type_ref": "shared_pkg::link_req_t", "width": 9,
     "basis": [{"file": "input/docs/interface.md", "line": 4,
                "quote": "<verbatim source line>"}]},
    {"name": "link_rsp_i", "direction": "input",
     "type_ref": "shared_pkg::link_rsp_t", "width": 17,
     "basis": [{"file": "input/docs/interface.md", "line": 4,
                "quote": "<verbatim source line>"}]}
  ],
  "logical_bindings": [
    {"source_name": "link", "kind": "req_rsp", "local_role": "req",
     "instance_count": 1, "request_port": "link_req_o",
     "response_port": "link_rsp_i",
     "selected_payload_types": {"request": "shared_pkg::link_req_t",
                                "response": "shared_pkg::link_rsp_t"},
     "basis": [{"file": "input/docs/interface.md", "line": 4,
                "quote": "<verbatim source line>"}]}
  ],
  "decisions": [
    {"id": "explicit-source-correction", "kind": "type_correction",
     "port": "typed_i", "source_type_ref": "misspelled_pkg::value_t",
     "selected_type_ref": "shared_pkg::value_t",
     "original_claim": "<original source claim>",
     "selected_claim": "<explicit selected engineering configuration>",
     "authority": "AGENT_ENGINEERING_CHOICE", "reason": "<reason>",
     "basis": [{"file": "input/docs/interface.md", "line": 7,
                "quote": "<verbatim source line>"}]}
  ]
}
```

`source_conflict` is the other decision kind. It records conflicting source
claims and a selected physical type, without declaring the claims consistent or
silently connecting a separate logical signal. Its quoted basis must include
both type spellings. Each decision addresses an explicitly bound physical port.
Type corrections require the original physical declaration and a matching
explicit decision. An unresolved logical signal is removed from physical port
arrays only by a complete request/response map, retained in the binding ledger.

For `req_rsp`, the original local role controls direction: requester (`req`)
has request output/response input; responder (`rsp`) has request input/response
output. Single-instance bundles are supported; other counts are refused. An
existing physical member must keep its declared direction and type unless an
explicit type correction applies. New member names are engineering choices.
The selected payload types must match both members exactly. The compiler
validates their existence and measured sizes; source-role checks validate
direction. Compiling an authored wrapper alone does not establish direction.
Supported parent-family spellings are `pkg::family` mapped to exactly
`pkg::family_req_t`/`pkg::family_rsp_t`, or
`pkg::family_h2d_t`/`pkg::family_d2h_t`, respectively. Other payload naming
contracts are refused as unsupported. A valid unrelated package/type or a
reversed pair is refused even if its authored widths would compile correctly.

Every context file must be under the fixed `plugin_input/interface_context/`
root, with exact bytes and no symlinks. The file map covers that entire subtree,
including provider/parameter provenance metadata. `compile_order` contains only
package compilation units; includes must also resolve within the pinned file
map. `defines` is an explicit list of `NAME` or `NAME=value` strings. Package
parameters are selected by the pinned source bytes; nonempty `parameters` are
currently refused, since a top-module `-G` flag cannot override a package.
Provider choices (including a shared `top_pkg`) establish the selected package
configuration only; they do not establish equivalence to any reference design.

The producer inspects `EDA_CONTAINER` and its image, requires the selected
immutable digest, and runs a freshly generated interface-only Verilator probe
in that container. It uses at most two build jobs, never imports implementation
RTL, and compares every authored width with the freshly measured `$bits`.
Reports are written under `reports/phase1/interface_binding/`. All validation
and tool execution precede L9 publication. The emitted ledger preserves the
source roster, logical maps, decisions, package hashes, measured types and
execution identity. It is marked `PENDING_INDEPENDENT_D1`; the producer cannot
sign its own work. D1 evidence and Phase-1 input freshness include the manifest
and the fixed context subtree. Changed packages or choices invalidate reuse.
The embedded semantic proof is stable for identical inputs and execution
identity. Full commands, temporary build paths and raw log hashes live in the
separate D1-bound `execution.json`, rather than perturbing the L9 port contract.
