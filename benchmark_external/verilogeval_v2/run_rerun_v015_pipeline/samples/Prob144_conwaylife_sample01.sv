module TopModule (
    input          clk,
    input          load,
    input  [255:0] data,
    output [255:0] q
);
    reg [255:0] grid;
    reg [255:0] nextgrid;

    integer ri;
    integer ci;
    integer dr;
    integer dc;
    integer rr;
    integer cc;
    integer cnt;

    always @(*) begin
        for (ri = 0; ri < 16; ri = ri + 1) begin
            for (ci = 0; ci < 16; ci = ci + 1) begin
                cnt = 0;
                for (dr = -1; dr <= 1; dr = dr + 1) begin
                    for (dc = -1; dc <= 1; dc = dc + 1) begin
                        if (!(dr == 0 && dc == 0)) begin
                            rr = (ri + dr + 16) % 16;
                            cc = (ci + dc + 16) % 16;
                            cnt = cnt + grid[rr*16 + cc];
                        end
                    end
                end
                if (cnt == 2)
                    nextgrid[ri*16 + ci] = grid[ri*16 + ci]; // unchanged
                else if (cnt == 3)
                    nextgrid[ri*16 + ci] = 1'b1;             // born / stays alive
                else
                    nextgrid[ri*16 + ci] = 1'b0;             // dies
            end
        end
    end

    always @(posedge clk) begin
        if (load) grid <= data;       // active-high synchronous load
        else      grid <= nextgrid;   // advance one timestep
    end

    assign q = grid;
endmodule
