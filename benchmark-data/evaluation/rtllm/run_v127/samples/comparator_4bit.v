// comparator_4bit — combinational 4-bit magnitude comparator via subtraction
// borrow. Mutually exclusive greater/equal/less outputs.
module comparator_4bit (
    input  wire [3:0] A,
    input  wire [3:0] B,
    output wire       A_greater,
    output wire       A_equal,
    output wire       A_less
);
    wire [4:0] diff = {1'b0, A} - {1'b0, B};   // diff[4] = borrow (A < B)
    assign A_less    = diff[4];
    assign A_equal   = (A == B);
    assign A_greater = ~A_less & ~A_equal;
endmodule
