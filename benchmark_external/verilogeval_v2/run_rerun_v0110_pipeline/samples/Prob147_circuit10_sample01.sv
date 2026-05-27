module TopModule (
    input      clk,
    input      a,
    input      b,
    output     q,
    output reg state
);
    // state = carry flip-flop (majority of a, b, state); q = a ^ b ^ state.
    always @(posedge clk) begin
        state <= (a & b) | (a & state) | (b & state);
    end

    assign q = a ^ b ^ state;
endmodule
