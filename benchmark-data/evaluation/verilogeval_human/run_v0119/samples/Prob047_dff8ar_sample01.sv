module TopModule (
  input clk,
  input [7:0] d,
  input areset,
  output reg [7:0] q
);
    // positive-edge triggered, active-high ASYNCHRONOUS reset to 0
    always @(posedge clk or posedge areset) begin
        if (areset)
            q <= 8'd0;
        else
            q <= d;
    end
endmodule
