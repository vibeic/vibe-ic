module TopModule(
    input  clock,
    input  a,
    output p,
    output q
);
    // p: positive-level-sensitive latch on a (transparent while clock high).
    reg p_r;
    always @(*) begin
        if (clock) p_r = a;
    end

    // q: negative-edge-triggered flip-flop capturing p.
    reg q_r;
    always @(negedge clock) begin
        q_r <= p_r;
    end

    assign p = p_r;
    assign q = q_r;
endmodule
