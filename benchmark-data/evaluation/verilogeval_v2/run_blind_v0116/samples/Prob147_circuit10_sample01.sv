module TopModule (
    input  clk,
    input  a,
    input  b,
    output q,
    output state
);
    reg sr;   // the single flip-flop

    always @(posedge clk) begin
        if (a == b)
            sr <= a;     // both 0 -> 0, both 1 -> 1
        // else hold
    end

    assign state = sr;
    assign q     = a ^ b ^ sr;
endmodule
