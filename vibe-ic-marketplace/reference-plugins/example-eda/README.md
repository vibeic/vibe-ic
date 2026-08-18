# example-eda — Reference EDA tool plugin

This is a **stub** demonstrating the L_eda plugin shape. A real EDA plugin
would also ship a binary or a Python adapter that implements the MCP
tool named in `plugin.yaml: eda.mcp_tool_name`.

In v0.85, install this plugin only registers its metadata in
`~/.vibe-ic/plugins/...`. The MCP server's tool-discovery extension
(v1.0 work) is what wires the registered tool into the 33-step flow.
