module TopModule (
    input          clk,
    input          load,
    input  [255:0] data,
    output reg [255:0] q = 256'b0
);
    integer r, c;
    integer dr, dc;
    integer rr, cc;
    reg [3:0] cnt;
    reg [255:0] nextq;

    // index of cell (row, col) in the 256-bit vector: 16*row + col
    function integer idx;
        input integer row;
        input integer col;
        begin
            idx = 16*row + col;
        end
    endfunction

    always @(*) begin
        nextq = 256'b0;
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = 4'd0;
                for (dr = -1; dr <= 1; dr = dr + 1) begin
                    for (dc = -1; dc <= 1; dc = dc + 1) begin
                        if (!(dr == 0 && dc == 0)) begin
                            rr = (r + dr + 16) % 16;
                            cc = (c + dc + 16) % 16;
                            cnt = cnt + q[idx(rr, cc)];
                        end
                    end
                end
                // apply rules
                if (cnt == 4'd3)
                    nextq[idx(r, c)] = 1'b1;
                else if (cnt == 4'd2)
                    nextq[idx(r, c)] = q[idx(r, c)];
                else
                    nextq[idx(r, c)] = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= nextq;
    end
endmodule
