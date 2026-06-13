module TopModule (
    input          clk,
    input          load,
    input  [255:0] data,
    output reg [255:0] q
);
    // q[r*16 + c] is cell at row r (0..15), col c (0..15). Toroidal wrap.
    integer r, c, dr, dc, rr, cc;
    reg [3:0] cnt;
    reg [255:0] nq;

    always @(*) begin
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = 4'd0;
                for (dr = -1; dr <= 1; dr = dr + 1) begin
                    for (dc = -1; dc <= 1; dc = dc + 1) begin
                        if (!(dr == 0 && dc == 0)) begin
                            rr = (r + dr + 16) % 16;
                            cc = (c + dc + 16) % 16;
                            cnt = cnt + q[rr*16 + cc];
                        end
                    end
                end
                if (cnt == 4'd2)
                    nq[r*16 + c] = q[r*16 + c];   // stays the same
                else if (cnt == 4'd3)
                    nq[r*16 + c] = 1'b1;          // becomes/stays alive
                else
                    nq[r*16 + c] = 1'b0;          // dies
            end
        end
    end

    always @(posedge clk) begin
        if (load) q <= data;
        else      q <= nq;
    end
endmodule
