# Shared interface decisions

The logical TL interface `fabric` has local role `rsp`. Bind its incoming request payload to physical input `bus_req_i` of type `link_types_pkg::request_t`, and its outgoing response payload to physical output `bus_rsp_o` of type `link_types_pkg::response_t`.

The logical EDN interface `entropy` has local role `req`. Bind its outgoing request payload to physical output `entropy_req_o` of type `entropy_types_pkg::request_t`, and its incoming response payload to physical input `entropy_rsp_i` of type `entropy_types_pkg::response_t`. The main and auxiliary clocks remain separate domains even though their declared engineering periods are both 20 ns; no CDC or timing waiver is granted.

Package elaboration does not establish functional, security, CDC, RTL, physical or tapeout qualification.
