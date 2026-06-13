module TopModule (
    input  in1,
    input  in2,
    input  in3,
    output logic out
);

    always @(*)
        out = ~(in1 ^ in2) ^ in3;

endmodule
