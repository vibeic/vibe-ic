module TopModule (
  input clk,
  input reset,
  output [2:0] ena,
  output reg [15:0] q
);

  wire [3:0] enable = {q[11:0] == 12'h999, q[7:0] == 8'h99, q[3:0] == 4'h9, 1'b1};
  assign ena = enable[3:1];
  integer i;
  always @(posedge clk) begin
    if (reset) begin
      q <= 0;
    end else begin
      for (i = 0; i < 4; i = i + 1) begin
        if (enable[i]) begin
          if (q[i*4 +: 4] == 9)
            q[i*4 +: 4] <= 0;
          else
            q[i*4 +: 4] <= q[i*4 +: 4] + 1;
        end
      end
    end
  end

endmodule
