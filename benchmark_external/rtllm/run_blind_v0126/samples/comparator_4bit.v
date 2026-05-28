module comparator_4bit (
    input  [3:0] A,
    input  [3:0] B,
    output       A_greater,
    output       A_equal,
    output       A_less
);
    // Subtraction A - B: borrow indicates A < B
    wire [4:0] diff;
    assign diff = {1'b0, A} - {1'b0, B};

    wire borrow = diff[4];          // borrow occurred -> A < B
    wire zero   = (diff[3:0] == 4'b0);

    assign A_less    = borrow;
    assign A_equal   = (~borrow) & zero;
    assign A_greater = (~borrow) & (~zero);
endmodule
