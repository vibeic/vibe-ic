# Positional Magic seal-ring providers

The native die-finishing producer supports the PDK's positional generator API
`width height target_dir [-outer] [-keep]` in addition to the existing two
KLayout forms. Technology availability and caller support are separate:
discovering a provider does not mean a ring has been generated or qualified.
Multiple discovered providers require explicit selection. An unknown Magic
interface is a named refusal, never technology-derived not-applicable.

Select a script through the existing CLI/bridge/declaration precedence. If the
PDK has no conventional KLayout generator, discovery also checks the PDK's
`libs.tech/magic/seal_ring_generator/*seal*ring*.py` family. No process name
selects an invocation form; the provider's own declared interface does.

Unlike a KLayout script that accepts an input GDS, this API produces a standalone
ring. The native adapter invokes that original provider in a unique working
directory, imports its complete output hierarchy under the original design top,
and records the source files, arguments and input/output digests. It draws no
ring and removes no PDK shapes. Only the declared ring instance is translated;
the original chip geometry and hierarchy are checked for preservation.

## Geometry authority

The existing `die_size()` authority remains the built/whole DIE: explicit CLI
dimensions, provider target, routed/other DEF DIEAREA, then the declaration.
Those dimensions are not silently reused as a Magic frame. A positional provider
requires this explicit object in the existing bridge
`input/pdk/bridge/signoff_config.json`:

```json
{
  "die_finishing": {
    "magic_geometry": {
      "size_convention": "outer",
      "provider_size_um": [512, 768],
      "offset_um": [0, 0]
    }
  }
}
```

These are neutral API examples, not a physically qualified project choice.
`provider_size_um` must contain two positive finite numbers; `offset_um` must
contain two finite numbers representable on the input GDS grid. No booleans,
numeric strings, additional keys or unspecified defaults are accepted.
`size_convention=outer` passes `-outer`; `chip` preserves the provider's default
chip-area convention. `--magic-geometry` accepts the same JSON object and records
that CLI authority. Missing/invalid authority refuses before invocation.

The provider frame, complete generated envelope, ring offset, original core/pad
placement, and declared whole-DIE geometry are different facts. Fiducials or
other PDK shapes may extend beyond a marker frame; translation cannot change
their width. Choose frame/offset/inset explicitly and measure the resulting
whole GDS. This capability does not pick those values for an existing project.

## Scope of acceptance

The original `sealring_verify` still verifies output geometry, marker and hollow
annulus; the existing producer writes the finished DEF only after acceptance.
`die_finishing_check` consumes that real report. `general_precheck` still compares
the complete GDS extent/origin with the unchanged whole-DIE declaration. A good
ring can therefore correctly fail the separate size check.

The raw provider GDS, working files, stdout/stderr and provider source directory
manifest are retained. Existing libraries, tools and dynamic dependencies
outside that directory remain the selected runtime image's responsibility;
the manifest is not a claim to trace arbitrary filesystem reads. Different
provider/input GDS database units are currently refused rather than implicitly
scaled. Generation/import acceptance does not establish DRC, LVS, IR/EM, ESD
capacity, manufacturing acceptance, or whole-IC/release qualification.
