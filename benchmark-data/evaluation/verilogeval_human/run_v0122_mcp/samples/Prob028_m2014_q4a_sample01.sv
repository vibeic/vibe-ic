module TopModule (
    input  d,
    input  ena,
    output logic q
);

    always_latch
        if (ena)
            q = d;

endmodule
