module fixed_point_subtractor #(
    parameter Q = 8,
    parameter N = 16
) (
    input  wire [N-1:0] a,
    input  wire [N-1:0] b,
    output wire [N-1:0] c
);

    reg [N-1:0] res;

    // Subtraction a - b implemented as a + (-b):
    // Treat b as having an inverted sign, then reuse add-by-sign logic.
    always @(*) begin
        // Effective sign of the second operand is inverted (subtraction).
        // Same effective sign (a.sign == ~b.sign) -> add magnitudes
        if (a[N-1] != b[N-1]) begin
            // a and b have different stored signs -> after negating b they match -> add magnitudes
            res[N-2:0] = a[N-2:0] + b[N-2:0];
            res[N-1]   = a[N-1];
        end
        else begin
            // a and b have the same stored sign -> after negating b they differ -> subtract magnitudes
            if (a[N-2:0] > b[N-2:0]) begin
                res[N-2:0] = a[N-2:0] - b[N-2:0];
                res[N-1]   = a[N-1];
            end
            else if (b[N-2:0] > a[N-2:0]) begin
                res[N-2:0] = b[N-2:0] - a[N-2:0];
                res[N-1]   = ~b[N-1]; // sign flips to the negated-b side
            end
            else begin
                // Equal magnitudes -> result is zero, sign forced to 0
                res[N-2:0] = {(N-1){1'b0}};
                res[N-1]   = 1'b0;
            end
        end
    end

    assign c = res;

endmodule
