# Contributing — NEW_IC_CLASS

This is a focused per-topic guide. For the umbrella partner-plugin layout
+ submission workflow, see [`CONTRIBUTING_PARTNER_PLUGIN.md`](./CONTRIBUTING_PARTNER_PLUGIN.md).

## What you ship

| File (in your partner plugin) | Role |
|---|---|
| `programs/<class>_rtl_gen.py` | Deterministic RTL generator |
| `tools/protocol_tb/<class>_reference_tb.v` | Reference TB used by the Phase 2 runner |
| (optional) `programs/<class>_class_profile.py` | Detection rules |

## Register the class

Append to `plugins/vibe-ic/programs/ic_class_registry.json`:

```json
{
  "name": "<class>_<subclass>",
  "synonyms": ["<class>", "<alias>"],
  "rtl_gen": "<class>_rtl_gen.py",
  "rtl_gen_args": [],
  "reference_tb": "tools/protocol_tb/<class>_reference_tb.v",
  "detect_markers": {
    "L2": ["<keyword>"],
    "L3": ["<keyword>"]
  },
  "min_marker_score": 2,
  "default_top": "chip_top",
  "fallback_skill": "spec-to-rtl",
  "owner_plugin": "partner-<vendor>-<class>"
}
```

`phase2_one_shot_runner` consults this registry at runtime — adding the entry is the only cross-plugin change needed.

## chip-AGNOSTIC requirement

Your generator MUST emit RTL parameterised by L1-L27 docs only. NO references to specific vendor PDFs / xlsx columns / pin numbers in the generator code. Encode chip-specific values in the L docs themselves.

## Testing

Provide a small example project under `templates/<your-plugin>-example/<chip-name>/input/docs/` so reviewers can `/vibe-ic-phase2 templates/<your-plugin>-example/<chip-name>/` and confirm your generator runs end-to-end.
