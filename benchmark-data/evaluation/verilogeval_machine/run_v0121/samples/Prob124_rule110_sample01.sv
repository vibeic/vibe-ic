module TopModule (
  input clk,
  input load,
  input [511:0] data,
  output reg [511:0] q
);

  initial q = 512'b0;

  // Three neighbour views (widths normalized to 512):
  wire [511:0] center = q;
  wire [511:0] term_a = {1'b0, q[511:1]};   // prose: q[511:1]
  wire [511:0] term_c = {q[510:0], 1'b0};   // prose: {q[510:0],1'b0}

  always @(posedge clk) begin
    if (load)
      q <= data;
    else
      q <= ~( (term_a & center & term_c)
            | (~term_a & ~center & ~term_c)
            | (term_a & ~center & ~term_c) );
  end

endmodule
