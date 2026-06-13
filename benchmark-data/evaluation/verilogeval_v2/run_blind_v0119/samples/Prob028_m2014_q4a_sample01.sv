module TopModule (
    input      d,
    input      ena,
    output reg q
);
    always @(*)
        if (ena)
            q = d;
endmodule
