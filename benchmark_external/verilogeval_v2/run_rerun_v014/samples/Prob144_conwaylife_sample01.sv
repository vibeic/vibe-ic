module TopModule (
    input              clk,
    input              load,
    input      [255:0] data,
    output reg [255:0] q
);

    integer i, j;
    integer ni, nj;
    integer di, dj;
    integer cnt;
    reg [255:0] next_q;

    always @(*) begin
        for (i = 0; i < 16; i = i + 1) begin
            for (j = 0; j < 16; j = j + 1) begin
                cnt = 0;
                for (di = -1; di <= 1; di = di + 1) begin
                    for (dj = -1; dj <= 1; dj = dj + 1) begin
                        if (!(di == 0 && dj == 0)) begin
                            ni = (i + di + 16) % 16;
                            nj = (j + dj + 16) % 16;
                            cnt = cnt + q[ni*16 + nj];
                        end
                    end
                end
                if (cnt == 2)
                    next_q[i*16 + j] = q[i*16 + j];
                else if (cnt == 3)
                    next_q[i*16 + j] = 1'b1;
                else
                    next_q[i*16 + j] = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= next_q;
    end

endmodule
