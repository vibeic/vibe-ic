module TopModule (
  input clk,
  input [7:0] in,
  output reg [7:0] pedge
);
    reg [7:0] in_prev = 8'b0;
    initial pedge = 8'b0;          // deterministic power-up (no reset port)
    always @(posedge clk) begin
        pedge   <= ~in_prev & in;   // 1 where bit went 0 -> 1
        in_prev <= in;
    end
endmodule
