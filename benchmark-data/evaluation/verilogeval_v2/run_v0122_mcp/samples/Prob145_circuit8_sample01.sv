module TopModule (
    input  clock,
    input  a,
    output p,
    output q
);
    // p: transparent high latch of a (follows a when clock=1, holds when clock=0)
    reg p_r;
    always_latch begin
        if (clock) p_r = a;
    end

    // q: negative-edge flip-flop capturing p
    reg q_r;
    always @(negedge clock) begin
        q_r <= p_r;
    end

    assign p = p_r;
    assign q = q_r;

endmodule
