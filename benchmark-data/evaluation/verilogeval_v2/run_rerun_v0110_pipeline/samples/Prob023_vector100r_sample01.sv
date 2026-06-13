module TopModule (
    input  [99:0] in,
    output [99:0] out
);
    integer i;
    reg [99:0] tmp;
    always @(*) begin
        for (i = 0; i < 100; i = i + 1)
            tmp[i] = in[99 - i];
    end
    assign out = tmp;
endmodule
