module TopModule (
    input  in1,
    input  in2,
    output out
);

    // in2 has a bubble (inversion) into the AND gate
    assign out = in1 & ~in2;

endmodule
