// program-SOLVED transparent D latch (explicit, intentional); deterministic.
module TopModule (
    input d,
    input ena,
    output reg q
);
    always @(*) if (ena) q = d;
endmodule
