module TopModule (
    input  [3:0] x,
    output       f
);
    // K-map minterms (x = {x[3],x[2],x[1],x[0]}): 0,1,4,5,6,12,14,15
    assign f = (x == 4'd0)  | (x == 4'd1)  | (x == 4'd4)  | (x == 4'd5)  |
               (x == 4'd6)  | (x == 4'd12) | (x == 4'd14) | (x == 4'd15);
endmodule
