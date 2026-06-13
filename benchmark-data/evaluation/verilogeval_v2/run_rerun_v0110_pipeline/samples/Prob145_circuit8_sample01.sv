module TopModule (
    input      clock,
    input      a,
    output reg p,
    output reg q
);
    // p: latch transparent while clock is high (follows a); holds while clock low.
    always @(*) begin
        if (clock) p = a;
    end

    // q: captures p on the falling edge of clock.
    always @(negedge clock) begin
        q <= p;
    end
endmodule
