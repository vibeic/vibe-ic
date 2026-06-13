module TopModule (
    input      clock,
    input      a,
    output reg p,
    output reg q
);

    // p is a flip-flop sampling 'a' on the positive edge of clock.
    always @(posedge clock) begin
        p <= a;
    end

    // q is a flip-flop sampling 'p' on the negative edge of clock.
    always @(negedge clock) begin
        q <= p;
    end

endmodule
