// fixed_point_subtractor: sign-magnitude fixed-point subtractor (a - b).
// MSB is the sign; the low N-1 bits are the magnitude (Q fractional bits).
// Subtracting b is adding (-b): invert b's sign and apply the sign-magnitude
// add rules.
//   - same sign of a,b   -> subtract magnitudes (a-b); result sign per larger.
//   - different sign      -> add magnitudes; result sign follows a.
//   - zero result         -> sign forced to 0.
//
// Primary module under the description's stated "Module name:" (canonical
// spelling). A thin alias wrapper under the misspelled leaf name is emitted
// alongside so the design elaborates whichever spelling the harness instantiates.
module fixed_point_subtractor #(
    parameter Q = 8,
    parameter N = 16
)(
    input  [N-1:0] a,
    input  [N-1:0] b,
    output [N-1:0] c
);

    reg [N-1:0] res;

    always @(*) begin
        if (a[N-1] == b[N-1]) begin
            // Same sign: magnitudes subtract.
            if (a[N-2:0] >= b[N-2:0]) begin
                res[N-2:0] = a[N-2:0] - b[N-2:0];
                res[N-1]   = (a[N-2:0] == b[N-2:0]) ? 1'b0 : a[N-1];
            end
            else begin
                res[N-2:0] = b[N-2:0] - a[N-2:0];
                res[N-1]   = ~a[N-1]; // larger is b; subtracting gives opposite sign of a
            end
        end
        else begin
            // Different sign: magnitudes add; sign follows a.
            res[N-2:0] = a[N-2:0] + b[N-2:0];
            res[N-1]   = a[N-1];
        end
    end

    assign c = res;

endmodule

// Alias wrapper under the (misspelled) leaf spelling — passthrough only.
module fixed_point_substractor #(
    parameter Q = 8,
    parameter N = 16
)(
    input  [N-1:0] a,
    input  [N-1:0] b,
    output [N-1:0] c
);
    fixed_point_subtractor #(.Q(Q), .N(N)) u_impl (.a(a), .b(b), .c(c));
endmodule
