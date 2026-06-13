module TopModule (
  input         clk,
  input         reset,
  output [2:0]  ena,
  output reg [15:0] q
);
  wire d0_max = (q[3:0]   == 4'd9);
  wire d1_max = (q[7:4]   == 4'd9);
  wire d2_max = (q[11:8]  == 4'd9);

  // enable for digit1 when ones rolls over; digit2 when ones&tens roll over; etc.
  assign ena[0] = d0_max;
  assign ena[1] = d0_max & d1_max;
  assign ena[2] = d0_max & d1_max & d2_max;

  always @(posedge clk) begin
    if (reset)
      q <= 16'd0;
    else begin
      // ones digit
      q[3:0] <= d0_max ? 4'd0 : q[3:0] + 4'd1;
      // tens digit
      if (ena[0])
        q[7:4] <= d1_max ? 4'd0 : q[7:4] + 4'd1;
      // hundreds digit
      if (ena[1])
        q[11:8] <= d2_max ? 4'd0 : q[11:8] + 4'd1;
      // thousands digit
      if (ena[2])
        q[15:12] <= (q[15:12] == 4'd9) ? 4'd0 : q[15:12] + 4'd1;
    end
  end
endmodule
