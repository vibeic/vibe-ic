module TopModule(
    input         clk,
    input         load,
    input  [255:0] data,
    output reg [255:0] q = 256'b0
);
    integer r, c, dr, dc, nr, nc;
    reg [3:0] cnt;
    reg [255:0] nq;

    always @(*) begin
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = 0;
                for (dr = -1; dr <= 1; dr = dr + 1) begin
                    for (dc = -1; dc <= 1; dc = dc + 1) begin
                        if (!(dr == 0 && dc == 0)) begin
                            nr = (r + dr + 16) % 16;
                            nc = (c + dc + 16) % 16;
                            cnt = cnt + q[nr*16 + nc];
                        end
                    end
                end
                // 2 -> hold, 3 -> alive, else dead
                if (cnt == 3)            nq[r*16 + c] = 1'b1;
                else if (cnt == 2)       nq[r*16 + c] = q[r*16 + c];
                else                     nq[r*16 + c] = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (load) q <= data;
        else      q <= nq;
    end
endmodule
