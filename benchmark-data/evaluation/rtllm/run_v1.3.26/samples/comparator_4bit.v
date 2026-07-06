module comparator_4bit (
    input  [3:0] A,
    input  [3:0] B,
    output       A_greater,
    output       A_equal,
    output       A_less
);
    wire [4:0] diff;

    assign diff = {1'b0, A} - {1'b0, B};

    assign A_less    = diff[4];
    assign A_equal   = (~diff[4]) & (diff[3:0] == 4'd0);
    assign A_greater = (~diff[4]) & (diff[3:0] != 4'd0);
endmodule
