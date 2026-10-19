package neutral_pkg;
  typedef struct packed { logic [7:0] data; logic valid; } link_req_t;
  typedef struct packed { logic [15:0] data; logic valid; } link_rsp_t;
  typedef struct packed { logic [9:0] data; logic valid; } transport_h2d_t;
  typedef struct packed { logic [11:0] data; logic valid; } transport_d2h_t;
  typedef logic [4:0] token_t;
  typedef logic [3:0] code_t;
  typedef logic [3:0] flag4_t;
endpackage
package unrelated_pkg;
  typedef logic [8:0] link_req_t;
  typedef logic [16:0] link_rsp_t;
endpackage
