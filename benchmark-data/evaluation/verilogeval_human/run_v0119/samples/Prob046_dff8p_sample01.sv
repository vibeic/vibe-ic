module TopModule (
  input clk,
  input [7:0] d,
  input reset,
  output reg [7:0] q
);
    // negative-edge triggered, active-high synchronous reset to 0x34
    always @(negedge clk) begin
        if (reset)
            q <= 8'h34;
        else
            q <= d;
    end
endmodule
