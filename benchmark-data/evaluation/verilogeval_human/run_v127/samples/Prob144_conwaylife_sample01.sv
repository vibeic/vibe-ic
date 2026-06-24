module TopModule (
    input clk,
    input load,
    input [255:0] data,
    output reg [255:0] q
);

    // 16x16 toroidal Moore (8-neighbour) cellular automaton.
    // Row-major packing: cell (row i, col j) -> bit i*16+j.
    // BIRTH counts {3} : dead -> alive.
    // SURVIVE counts {2,3} : alive stays alive.

    reg [255:0] nxt;
    integer i, j;
    integer up, dn, lf, rt;        // wrapped neighbour row/col
    integer cnt;                   // live neighbour count (0..8)
    always @(*) begin
        for (i = 0; i < 16; i = i + 1) begin
            for (j = 0; j < 16; j = j + 1) begin
                up = (i + 16 - 1) % 16;
                dn = (i + 1) % 16;
                lf = (j + 16 - 1) % 16;
                rt = (j + 1) % 16;
                cnt =
                    q[up*16 + lf] + q[up*16 + j] + q[up*16 + rt] +
                    q[ i*16 + lf]                + q[ i*16 + rt] +
                    q[dn*16 + lf] + q[dn*16 + j] + q[dn*16 + rt];
                if (q[i*16 + j])
                    nxt[i*16 + j] = ((cnt == 2) || (cnt == 3)) ? 1'b1 : 1'b0;
                else
                    nxt[i*16 + j] = ((cnt == 3)) ? 1'b1 : 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= nxt;
    end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
