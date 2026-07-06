module fixed_point_adder #(
    parameter Q = 8,
    parameter N = 16
) (
    input      [N-1:0] a,
    input      [N-1:0] b,
    output     [N-1:0] c
);

    reg [N-1:0] res;

    always @(*) begin
        if (a[N-1] == b[N-1]) begin
            res[N-2:0] = a[N-2:0] + b[N-2:0];
            res[N-1]   = a[N-1];
        end else begin
            if (a[N-2:0] >= b[N-2:0]) begin
                res[N-2:0] = a[N-2:0] - b[N-2:0];
                res[N-1]   = (res[N-2:0] == {(N-1){1'b0}}) ? 1'b0 : a[N-1];
            end else begin
                res[N-2:0] = b[N-2:0] - a[N-2:0];
                res[N-1]   = b[N-1];
            end
        end
    end

    assign c = res;

endmodule
