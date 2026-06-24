// comparator_3bit — combinational 3-bit magnitude comparator, mutually
// exclusive greater/equal/less outputs.
module comparator_3bit (
    input  wire [2:0] A,
    input  wire [2:0] B,
    output wire       A_greater,
    output wire       A_equal,
    output wire       A_less
);
    assign A_greater = (A > B);
    assign A_equal   = (A == B);
    assign A_less    = (A < B);
endmodule
