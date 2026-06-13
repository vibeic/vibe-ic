module TopModule(
    input  [99:0] in,
    output [99:0] out
);
    integer i;
    reg [99:0] r;
    always @(*) begin
        for (i = 0; i < 100; i = i + 1)
            r[i] = in[99 - i];
    end
    assign out = r;
endmodule
