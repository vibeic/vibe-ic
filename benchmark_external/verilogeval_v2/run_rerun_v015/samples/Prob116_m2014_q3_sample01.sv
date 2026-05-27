module TopModule (
    input  [3:0] x,
    output reg f
);
    // K-map (with don't-cares chosen as 0). Labels x[1..4] mapped to
    // port bits as x[1]=x[3] (MSB) ... x[4]=x[0] (LSB).
    // Confirmed 1-minterms {x[3],x[2],x[1],x[0]}: D, 3, 7, 2, 6
    always @(*) begin
        case (x)
            4'h2: f = 1'b1;
            4'h3: f = 1'b1;
            4'h6: f = 1'b1;
            4'h7: f = 1'b1;
            4'hd: f = 1'b1;
            default: f = 1'b0;
        endcase
    end
endmodule
