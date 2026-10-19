# NeutralCore

The module **`packet_bridge`** has the following hardware interfaces defined.

| Signal | Direction | Type | Description |
|---|---|---|---|
| payload_i | input | neutral_pkg::payload_t | Typed incoming payload. |
| ready_o | output | logic | Ready indication. |

The public implementation boundary uses payload_i[8:0]. Its supplied package context defines neutral_pkg::payload_t as a packed structure with a one-bit valid field and an eight-bit data field. A native interface binding must independently measure that type as nine bits; the input is not an authorization to guess flattened widths of arbitrary unknown types.
