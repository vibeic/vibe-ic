module TopModule (
  input         clk,
  input         reset,
  output [3:1]  ena,
  output [15:0] q
);
  reg [15:0] count;

  wire d0_max = (count[3:0]   == 4'd9);
  wire d1_max = (count[7:4]   == 4'd9);
  wire d2_max = (count[11:8]  == 4'd9);

  wire ena1 = d0_max;
  wire ena2 = d0_max & d1_max;
  wire ena3 = d0_max & d1_max & d2_max;

  always @(posedge clk) begin
    if (reset)
      count <= 16'd0;
    else begin
      // ones digit
      if (d0_max) count[3:0] <= 4'd0;
      else        count[3:0] <= count[3:0] + 4'd1;
      // tens digit
      if (ena1) begin
        if (d1_max) count[7:4] <= 4'd0;
        else        count[7:4] <= count[7:4] + 4'd1;
      end
      // hundreds digit
      if (ena2) begin
        if (d2_max) count[11:8] <= 4'd0;
        else        count[11:8] <= count[11:8] + 4'd1;
      end
      // thousands digit
      if (ena3) begin
        if (count[15:12] == 4'd9) count[15:12] <= 4'd0;
        else                      count[15:12] <= count[15:12] + 4'd1;
      end
    end
  end

  assign q   = count;
  assign ena = {ena3, ena2, ena1};
endmodule
