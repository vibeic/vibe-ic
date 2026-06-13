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

  wire roll0 = (d0 == 4'd9);
  wire roll1 = (d1 == 4'd9) & roll0;
  wire roll2 = (d2 == 4'd9) & roll1;

  assign ena = {roll2, roll1, roll0};

  always @(posedge clk) begin
    if (reset) begin
      q <= 16'd0;
    end else begin
      // ones digit
      if (roll0) q[3:0]   <= 4'd0; else q[3:0]   <= d0 + 4'd1;
      // tens digit
      if (roll0) begin
        if (roll1) q[7:4]   <= 4'd0; else q[7:4]   <= d1 + 4'd1;
      end
      // hundreds digit
      if (roll1) begin
        if (roll2) q[11:8]  <= 4'd0; else q[11:8]  <= d2 + 4'd1;
      end
      // thousands digit
      if (roll2) begin
        if (d3 == 4'd9) q[15:12] <= 4'd0; else q[15:12] <= d3 + 4'd1;
      end
    end
  end

endmodule
