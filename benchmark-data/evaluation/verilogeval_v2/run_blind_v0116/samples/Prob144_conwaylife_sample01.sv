module TopModule (
    input         clk,
    input         load,
    input  [255:0] data,
    output reg [255:0] q = 256'b0
);
    integer r, c;
    integer rr, cc;
    integer i, j;
    reg [3:0] cnt;
    reg [255:0] nextq;

    // helper: index of cell (row, col) with wrap-around on a 16x16 torus
    function integer idx;
        input integer row;
        input integer col;
        integer wr, wc;
        begin
            wr = (row + 16) % 16;
            wc = (col + 16) % 16;
            idx = wr*16 + wc;
        end
    endfunction

    always @(*) begin
        nextq = 256'b0;
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = 4'd0;
                for (i = -1; i <= 1; i = i + 1) begin
                    for (j = -1; j <= 1; j = j + 1) begin
                        if (!(i == 0 && j == 0))
                            cnt = cnt + q[idx(r+i, c+j)];
                    end
                end
                // birth/survival rules
                if (cnt == 4'd3)
                    nextq[r*16+c] = 1'b1;
                else if (cnt == 4'd2)
                    nextq[r*16+c] = q[r*16+c];
                else
                    nextq[r*16+c] = 1'b0;
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
