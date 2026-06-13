module fixed_point_adder #(
    parameter Q = 8,
    parameter N = 16
) (
    input  wire [N-1:0] a,
    input  wire [N-1:0] b,
    output wire [N-1:0] c
);

    reg [N-1:0] res;

    always @(*) begin
        // Same sign: add magnitudes, keep common sign
        if (a[N-1] == b[N-1]) begin
            res[N-2:0] = a[N-2:0] + b[N-2:0];
            res[N-1]   = a[N-1];
        end
        // Different sign: subtract smaller magnitude from larger
        else begin
            if (a[N-2:0] > b[N-2:0]) begin
                res[N-2:0] = a[N-2:0] - b[N-2:0];
                res[N-1]   = a[N-1]; // result takes sign of the larger magnitude (a)
            end
            else if (b[N-2:0] > a[N-2:0]) begin
                res[N-2:0] = b[N-2:0] - a[N-2:0];
                res[N-1]   = b[N-1]; // result takes sign of the larger magnitude (b)
            end
            else begin
                // Equal magnitudes, opposite signs -> zero
                res[N-2:0] = {(N-1){1'b0}};
                res[N-1]   = 1'b0;
            end
        end
    end

    assign c = res;

endmodule
