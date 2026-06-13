module TopModule (
    input  clock,
    input  a,
    output reg p,
    output reg q
);
    // p: transparent latch, captures a while clock is high
    always_latch begin
        if (clock)
            p = a;
    end

    // q: transparent latch, captures p while clock is low
    always_latch begin
        if (!clock)
            q = p;
    end
endmodule
