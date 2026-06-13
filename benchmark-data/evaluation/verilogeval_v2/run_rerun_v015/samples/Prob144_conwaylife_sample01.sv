module TopModule(
    input          clk,
    input          load,
    input  [255:0] data,
    output [255:0] q
);
    reg [255:0] q_r;

    // index helper: cell at row r, col c -> bit r*16 + c, with wrap-around
    function [7:0] count_neighbors;
        input [255:0] grid;
        input integer r;
        input integer c;
        integer dr, dc, rr, cc;
        reg [7:0] cnt;
        begin
            cnt = 0;
            for (dr = -1; dr <= 1; dr = dr + 1) begin
                for (dc = -1; dc <= 1; dc = dc + 1) begin
                    if (!(dr == 0 && dc == 0)) begin
                        rr = (r + dr + 16) % 16;
                        cc = (c + dc + 16) % 16;
                        cnt = cnt + grid[rr*16 + cc];
                    end
                end
            end
            count_neighbors = cnt;
        end
    endfunction

    integer i, j;
    reg [255:0] next_q;
    reg [7:0] n;

    always @(*) begin
        for (i = 0; i < 16; i = i + 1) begin
            for (j = 0; j < 16; j = j + 1) begin
                n = count_neighbors(q_r, i, j);
                if (n == 2)
                    next_q[i*16 + j] = q_r[i*16 + j];
                else if (n == 3)
                    next_q[i*16 + j] = 1'b1;
                else
                    next_q[i*16 + j] = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (load) q_r <= data;
        else      q_r <= next_q;
    end

    assign q = q_r;
endmodule
