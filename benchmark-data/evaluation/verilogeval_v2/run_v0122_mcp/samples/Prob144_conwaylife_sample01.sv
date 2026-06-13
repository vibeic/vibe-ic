module TopModule (
    input         clk,
    input         load,
    input  [255:0] data,
    output [255:0] q
);
    reg [255:0] grid;

    // index helper with toroidal wrap (16x16). cell(row,col) = grid[16*row + col]
    function automatic integer idx;
        input integer r;
        input integer c;
        integer rr, cc;
        begin
            rr = (r + 16) % 16;
            cc = (c + 16) % 16;
            idx = rr*16 + cc;
        end
    endfunction

    integer r, c;
    integer cnt;
    reg [255:0] nxt;

    always @(*) begin
        nxt = 256'b0;
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = grid[idx(r-1,c-1)] + grid[idx(r-1,c)] + grid[idx(r-1,c+1)]
                    + grid[idx(r,  c-1)]                    + grid[idx(r,  c+1)]
                    + grid[idx(r+1,c-1)] + grid[idx(r+1,c)] + grid[idx(r+1,c+1)];
                if (cnt == 2)
                    nxt[idx(r,c)] = grid[idx(r,c)];
                else if (cnt == 3)
                    nxt[idx(r,c)] = 1'b1;
                else
                    nxt[idx(r,c)] = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (load) grid <= data;
        else      grid <= nxt;
    end

    assign q = grid;

endmodule
