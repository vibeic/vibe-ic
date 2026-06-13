module TopModule (
  input clk,
  input [7:0] in,
  output reg [7:0] anyedge
);
    reg [7:0] in_prev = 8'b0;
    initial anyedge = 8'b0;        // deterministic power-up (no reset port)
    always @(posedge clk) begin
        anyedge <= in ^ in_prev;   // 1 where the bit changed since last cycle
        in_prev <= in;
    end
endmodule
