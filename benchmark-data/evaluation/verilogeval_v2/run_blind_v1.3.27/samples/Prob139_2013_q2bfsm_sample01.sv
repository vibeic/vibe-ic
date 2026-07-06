module TopModule(
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);
    localparam A=4'd0, F=4'd1, X0=4'd2, X1=4'd3, X2=4'd4,
               G0=4'd5, G1=4'd6, GP=4'd7, GZ=4'd8;

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:  next = F;
            F:  next = X0;
            X0: next = x ? X1 : X0;
            X1: next = x ? X1 : X2;
            X2: next = x ? G0 : X0;
            G0: next = y ? GP : G1;
            G1: next = y ? GP : GZ;
            GP: next = GP;
            GZ: next = GZ;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn) state <= A;
        else         state <= next;
    end

    assign f = (state == F);
    assign g = (state == G0) || (state == G1) || (state == GP);

endmodule
