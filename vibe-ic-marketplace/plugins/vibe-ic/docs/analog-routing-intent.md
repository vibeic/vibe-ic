# Declared A11 routing intent

A11 accepts `routing_intent` in `input/analog_flow.json`, under
`steps.A11` or its existing per-block override. The native physical adapter
passes the declaration to the normal Magic layout producer. Omitting the field
uses the existing planner and emits the same drawing commands.

```json
{
  "steps": {
    "A11": {
      "routing_intent": {
        "version": 1,
        "constraints": [
          {
            "kind": "kelvin",
            "net": "power",
            "force": [{"device": "driver", "terminal": 0}],
            "sense": {"device": "sensor", "terminal": 0},
            "join": {"port": "power"}
          },
          {
            "kind": "width",
            "net": "power",
            "wire_width_um": 0.6,
            "via_cuts": 2
          },
          {
            "kind": "separation",
            "nets": ["power", "control"],
            "spacing_um": 0.5
          }
        ]
      }
    }
  }
}
```

`device` is the A3 SPICE instance name without its leading `x`. `terminal`
is its zero-based SPICE terminal index. A join is either one terminal reference
or `{"port": "name"}` naming the same declared schematic net. These references
resolve through measured PDK gencell labels, not supplied coordinates.

A `kelvin` constraint creates separate force and sense branches. A `star`
constraint replaces `force` and `sense` with `groups`, a list of at least two
nonempty terminal-reference lists. Groups must partition every terminal of the
net except a separately declared terminal join. Repeated membership, missing
terminals and competing topology declarations are refused. The branches may
connect only in the actual declared load contact. Port junctions are physical
pins sized from the PDK via enclosure and branch count. Terminal junctions use
the actual local native contact footprint. A route that cannot fit is refused.
The schematic and exported port names remain unchanged.

`width` declares a per-net minimum wire style and minimum cut count at each
producer-created transition, including pins and branch joins. Placement reserves
the widest required corridor while each net uses its own wire profile. The
primary low-metal declaration is checked against the retained PDK width floors.
Higher planes retain the greater of their own PDK floor and the declared style;
a 0.6 um declaration may therefore produce a 1.64 um upper-plane wire. Cut arrays
contain separate cuts at the PDK pitch. Their enclosing metal may be wider.
Existing native gencell masks and device-area repair polygons retain their own
PDK geometry. A requested wire style that would require an undersized access
neck is refused rather than silently narrowed.

A `separation` constraint chooses either `spacing_um` or the pair
`shield_net` and `layer`. Spacing is measured over the named nets' same-plane
routing, pin and attributable native terminal metal. PDK spacing and
width-dependent rules still apply. Fixed device geometry can make a larger
requested gap impossible.

The bounded shield planner supports a connected shield port between the two
ports on the declared pure routing layer. It extends that existing connected
conductor across the complete parallel projection of the pair. It preserves
original port indices. Contact and cut types cannot substitute for a declared
routing layer. Missing channels, obstacles, unresolved native ownership or a
shield that cannot remain connected cause a named refusal. It does not emit a
floating decorative stripe or substitute spacing for a shield request.

Unknown fields, nonfinite dimensions and invalid references produce
`ROUTING_INTENT_SCHEMA`, `ROUTING_INTENT_ENDPOINT` or
`ROUTING_INTENT_CONFLICT`. Geometry failures name their contract, including
`WIDTH_BELOW_PDK_MINIMUM`, `WIDTH_UNACHIEVED`, `VIA_SITE`, `NO_LEGAL_ROUTE`,
`PREMATURE_JOIN`, `DISCONNECTED_BRANCH`, `SEPARATION`,
`NATIVE_OWNERSHIP_AMBIGUOUS`, `SHIELD_LAYER` and `SHIELD_UNROUTABLE`.
These are producer refusals, not DRC waivers. Normal native DRC and LVS remain
required. The layout provenance includes the declaration and measured plan
controls; it does not claim native signoff.
