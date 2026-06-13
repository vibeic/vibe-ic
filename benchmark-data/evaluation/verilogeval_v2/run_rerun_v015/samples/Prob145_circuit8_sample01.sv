module TopModule(
    input  clock,
    input  a,
    output p,
    output q
);
    // p is a positive-level-sensitive latch of 'a' (transparent when clock=1)
    reg p_r;
    always @(*) begin
        if (clock)
            p_r = a;
    end

    // q is a negative-edge-triggered flip-flop sampling p
    reg q_r;
    always @(negedge clock) begin
        q_r <= p_r;
    end

    assign p = p_r;
    assign q = q_r;
endmodule
