module TopModule (
  input clk,
  input load,
  input [1:0] ena,
  input [99:0] data,
  output reg [99:0] q
);
  always @(posedge clk) begin
    if (load)
      q <= data;
    else begin
      case (ena)
        2'h1: q <= {q[98:0], q[99]};   // rotate left
        2'h2: q <= {q[0], q[99:1]};    // rotate right
        default: q <= q;
      endcase
    end
  end
endmodule
