# Directed interface decisions
The logical TL responder has distinct request input and response output payloads.
The logical EDN requester has distinct request output and acknowledgment response input payloads.
Both interfaces use simultaneously named unidirectional request and response payloads, never a shared turnaround wire.
For the canonical protocol descriptor, explicitly set `protocol_overview.half_duplex` to `false`.
