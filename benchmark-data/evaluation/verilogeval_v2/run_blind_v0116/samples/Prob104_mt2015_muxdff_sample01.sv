module TopModule (
    input  clk,
    input  L,
    input  q_in,
    input  r_in,
    output reg Q = 0
);
    // 2:1 mux (L selects r_in else q_in) feeding a D flip-flop
    always @(posedge clk) begin
        Q <= L ? r_in : q_in;
    end
endmodule
