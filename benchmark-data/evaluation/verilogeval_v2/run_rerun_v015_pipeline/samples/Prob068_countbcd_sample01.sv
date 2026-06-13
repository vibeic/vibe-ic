module TopModule (
  input  clk,
  input  reset,
  output [2:0] ena,
  output reg [15:0] q
);
  wire [3:0] d0 = q[3:0];
  wire [3:0] d1 = q[7:4];
  wire [3:0] d2 = q[11:8];
  wire [3:0] d3 = q[15:12];

  // enable to increment each upper digit: when all lower digits are 9
  wire e0 = (d0 == 4'd9);                          // tens advances
  wire e1 = (d0 == 4'd9) && (d1 == 4'd9);          // hundreds advances
  wire e2 = (d0 == 4'd9) && (d1 == 4'd9) && (d2 == 4'd9); // thousands advances

  assign ena = {e2, e1, e0};

  always @(posedge clk) begin
    if (reset) begin
      q <= 16'd0;
    end else begin
      // ones
      q[3:0]   <= (d0 == 4'd9) ? 4'd0 : d0 + 4'd1;
      // tens
      if (e0) q[7:4]   <= (d1 == 4'd9) ? 4'd0 : d1 + 4'd1;
      // hundreds
      if (e1) q[11:8]  <= (d2 == 4'd9) ? 4'd0 : d2 + 4'd1;
      // thousands
      if (e2) q[15:12] <= (d3 == 4'd9) ? 4'd0 : d3 + 4'd1;
    end
  end
endmodule
