module TopModule (
  input clk,
  input reset,
  output [3:1] ena,
  output reg [15:0] q
);

  wire d0_max = (q[3:0]   == 4'd9);
  wire d1_max = (q[7:4]   == 4'd9);
  wire d2_max = (q[11:8]  == 4'd9);

  assign ena[1] = d0_max;
  assign ena[2] = d0_max & d1_max;
  assign ena[3] = d0_max & d1_max & d2_max;

  always @(posedge clk) begin
    if (reset)
      q <= 16'd0;
    else begin
      // ones digit
      if (d0_max) q[3:0] <= 4'd0;
      else        q[3:0] <= q[3:0] + 1'b1;
      // tens digit
      if (ena[1]) begin
        if (d1_max) q[7:4] <= 4'd0;
        else        q[7:4] <= q[7:4] + 1'b1;
      end
      // hundreds digit
      if (ena[2]) begin
        if (d2_max) q[11:8] <= 4'd0;
        else        q[11:8] <= q[11:8] + 1'b1;
      end
      // thousands digit
      if (ena[3]) begin
        if (q[15:12] == 4'd9) q[15:12] <= 4'd0;
        else                  q[15:12] <= q[15:12] + 1'b1;
      end
    end
  end

endmodule
