module fixed_point_subtractor #(
    parameter Q = 8,
    parameter N = 16
) (
    input      [N-1:0] a,
    input      [N-1:0] b,
    output     [N-1:0] c
);

    reg  [N-1:0] res;
    wire [N-1:0] bneg = {~b[N-1], b[N-2:0]};

    always @(*) begin
        if (a[N-1] == bneg[N-1]) begin
            res[N-2:0] = a[N-2:0] + bneg[N-2:0];
            res[N-1]   = a[N-1];
        end else begin
            if (a[N-2:0] >= bneg[N-2:0]) begin
                res[N-2:0] = a[N-2:0] - bneg[N-2:0];
                res[N-1]   = (res[N-2:0] == {(N-1){1'b0}}) ? 1'b0 : a[N-1];
            end else begin
                res[N-2:0] = bneg[N-2:0] - a[N-2:0];
                res[N-1]   = bneg[N-1];
            end
        end
    end

    assign c = res;

endmodule

// Alias wrapper: the RTLLM benchmark directory leaf spelling differs
// ("substractor") from the canonical spec module name
// ("fixed_point_subtractor"). Emit both spellings so either binds.
module fixed_point_substractor #(
    parameter Q = 8,
    parameter N = 16
) (
    input      [N-1:0] a,
    input      [N-1:0] b,
    output     [N-1:0] c
);

    fixed_point_subtractor #(.Q(Q), .N(N)) u_impl (
        .a(a),
        .b(b),
        .c(c)
    );

endmodule
