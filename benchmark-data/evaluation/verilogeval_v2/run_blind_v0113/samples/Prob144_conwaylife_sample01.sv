module TopModule(
    input         clk,
    input         load,
    input  [255:0] data,
    output reg [255:0] q = 256'b0
);
    // Grid is 16x16, cell(row,col) = q[row*16 + col]. Toroidal wrap on both axes.
    integer r, c;
    integer rr, cc, dr, dc;
    integer cnt;
    reg [255:0] nextq;

    always @(*) begin
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = 0;
                for (dr = -1; dr <= 1; dr = dr + 1) begin
                    for (dc = -1; dc <= 1; dc = dc + 1) begin
                        if (!(dr == 0 && dc == 0)) begin
                            rr = (r + dr + 16) % 16;
                            cc = (c + dc + 16) % 16;
                            cnt = cnt + q[rr*16 + cc];
                        end
                    end
                end
                // Life rules
                if (cnt == 2)
                    nextq[r*16 + c] = q[r*16 + c];
                else if (cnt == 3)
                    nextq[r*16 + c] = 1'b1;
                else
                    nextq[r*16 + c] = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (load) q <= data;
        else      q <= nextq;
    end
endmodule
