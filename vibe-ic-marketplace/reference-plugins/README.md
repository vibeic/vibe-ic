# Reference plugins (v0.85 D7 + D8)

Three end-to-end-tested examples — one per plugin layer — that demonstrate
the on-disk shape required by `plugin.yaml` schema v1
(`docs/design/plugin_platform_spec.md`).

| Dir | Layer | What it shows |
|-----|-------|---------------|
| `example-exp/` | `exp` | All four experience sub-payloads in one bundle: K3 entries, PRACTICAL_NOTES, T5 capture, decision_log. |
| `example-ip/`  | `ip`  | Soft-IP (one Verilog file) with full `ip_metadata.yaml` (D8). |
| `example-eda/` | `eda` | Stub for a third-party MCP tool (Cadence/Synopsys-style) including capability + endpoint declaration. |

The CI test `tests/test_reference_plugins.py` packs each of these,
installs into a temp `VIBE_IC_HOME`, verifies the install round-trips
cleanly, and checks the v0.85 spec invariants on each:

- `pack` produces a tarball whose manifest re-validates cleanly.
- `install` extracts to `<VIBE_IC_HOME>/plugins/<ns>/<id>/<ver>/`.
- `list` finds the new plugin.
- `info` shows the manifest fields.
- `uninstall` removes the install directory cleanly.

Adding a new reference plugin:
1. Create a new dir under `reference-plugins/`.
2. Add a `plugin.yaml` matching the schema for the chosen layer.
3. Add the layer-specific payload (k3/, ip files, etc).
4. Append the dir name to `REFERENCE_PLUGINS` in
   `tests/test_reference_plugins.py`.
