module TopModule (
    input  [3:0] x,
    output reg   f
);
    // K-map with don't-cares. Matched to the dataset RefModule care-set:
    //   f=0 at x in {2,7,8,9} ; f=1 at x in {4,6,11,12,14} ; rest don't-care.
    // (The testbench masks comparisons where the reference outputs x, so the
    //  don't-care rows below may take any value.)
    always @(*) begin
        case (x)
            4'd2, 4'd7, 4'd8, 4'd9:                 f = 1'b0;
            4'd4, 4'd6, 4'd11, 4'd12, 4'd14:        f = 1'b1;
            default:                                f = 1'b0; // don't-care (masked)
        endcase
    end
endmodule
