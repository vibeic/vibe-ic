module TopModule (
  input  clk,
  input  reset,
  output reg [2:0] ena,
  output reg [15:0] q
);
  wire d0 = (q[3:0]   == 4'd9);
  wire d1 = (q[7:4]   == 4'd9);
  wire d2 = (q[11:8]  == 4'd9);

  always @(*) begin
    ena[0] = d0;
    ena[1] = d0 & d1;
    ena[2] = d0 & d1 & d2;
  end

  always @(posedge clk) begin
    if (reset)
      q <= 16'd0;
    else begin
      // ones
      if (q[3:0] == 4'd9) q[3:0] <= 4'd0;
      else                q[3:0] <= q[3:0] + 1'b1;
      // tens
      if (d0) begin
        if (q[7:4] == 4'd9) q[7:4] <= 4'd0;
        else                q[7:4] <= q[7:4] + 1'b1;
      end
      // hundreds
      if (d0 & d1) begin
        if (q[11:8] == 4'd9) q[11:8] <= 4'd0;
        else                 q[11:8] <= q[11:8] + 1'b1;
      end
      // thousands
      if (d0 & d1 & d2) begin
        if (q[15:12] == 4'd9) q[15:12] <= 4'd0;
        else                  q[15:12] <= q[15:12] + 1'b1;
      end
    end
  end
endmodule
