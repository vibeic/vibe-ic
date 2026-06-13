module TopModule(
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    // One-bit memory (carry). Serial full-adder behaviour:
    //   q     = a ^ b ^ state   (sum)
    //   state = carry-out = majority(a, b, state)
    reg state_r;

    always @(posedge clk) begin
        state_r <= (a & b) | (a & state_r) | (b & state_r);
    end

    assign state = state_r;
    assign q     = a ^ b ^ state_r;
endmodule
