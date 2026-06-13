module TopModule (
    input         clk,
    input         load,
    input  [255:0] data,
    output reg [255:0] q = 256'b0
);
    integer r, c;
    integer rr, cc;
    integer nr, nc;
    reg [3:0] cnt;
    reg [255:0] nextq;

    // cell index helper: row r (0..15), col c (0..15) -> bit r*16 + c
    always @(*) begin
        nextq = 256'b0;
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = 4'd0;
                for (rr = -1; rr <= 1; rr = rr + 1) begin
                    for (cc = -1; cc <= 1; cc = cc + 1) begin
                        if (!(rr == 0 && cc == 0)) begin
                            nr = (r + rr + 16) % 16;
                            nc = (c + cc + 16) % 16;
                            cnt = cnt + q[nr*16 + nc];
                        end
                    end
                end
                // Life rule
                if (cnt == 4'd2)
                    nextq[r*16 + c] = q[r*16 + c];   // unchanged
                else if (cnt == 4'd3)
                    nextq[r*16 + c] = 1'b1;          // born / stays alive
                else
                    nextq[r*16 + c] = 1'b0;          // dies
            end
        end
    end

    always @(posedge clk) begin
        if (load) q <= data;
        else      q <= nextq;
    end
endmodule
