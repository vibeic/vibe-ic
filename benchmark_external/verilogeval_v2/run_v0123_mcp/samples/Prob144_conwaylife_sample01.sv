module TopModule (
    input         clk,
    input         load,
    input  [255:0] data,
    output reg [255:0] q
);
    integer r, c;
    reg [3:0] cnt;
    reg [255:0] nq;

    function [7:0] idx;  // map (row,col) with toroidal wrap to bit index
        input integer rr;
        input integer cc;
        integer wr, wc;
        begin
            wr = (rr + 16) % 16;
            wc = (cc + 16) % 16;
            idx = wr*16 + wc;
        end
    endfunction

    always @(*) begin
        for (r = 0; r < 16; r = r + 1) begin
            for (c = 0; c < 16; c = c + 1) begin
                cnt = q[idx(r-1,c-1)] + q[idx(r-1,c)] + q[idx(r-1,c+1)] +
                      q[idx(r,  c-1)] +                  q[idx(r,  c+1)] +
                      q[idx(r+1,c-1)] + q[idx(r+1,c)] + q[idx(r+1,c+1)];
                case (cnt)
                    4'd2: nq[r*16+c] = q[r*16+c];
                    4'd3: nq[r*16+c] = 1'b1;
                    default: nq[r*16+c] = 1'b0;
                endcase
            end
        end
    end

    always @(posedge clk) begin
        if (load) q <= data;
        else      q <= nq;
    end
endmodule
