// Dual-edge triggered flip-flop, FPGA-legal realization.
// A real dual-edge flop would need always @(posedge clk or negedge clk),
// which is illegal. Instead use two single-edge flops muxed by clock LEVEL:
//   qp captures d on the rising edge,
//   qn captures d on the falling edge,
//   q presents qp while clk is high (the value just latched on posedge) and
//   qn while clk is low (the value just latched on negedge).
// This makes q change just after EACH clock edge, matching a dual-edge flop.
module TopModule (
  input clk,
  input d,
  output reg q
);

  reg qp, qn;

  always @(posedge clk)
    qp <= d;

  always @(negedge clk)
    qn <= d;

  always @(*)
    q = clk ? qp : qn;

endmodule
