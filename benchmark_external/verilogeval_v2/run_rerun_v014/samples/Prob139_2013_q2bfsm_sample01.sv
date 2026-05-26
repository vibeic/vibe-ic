module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    localparam A    = 4'd0;  // reset state
    localparam B    = 4'd1;  // f = 1 for one cycle
    localparam SX0  = 4'd2;  // x-monitor: no useful prefix
    localparam SX1  = 4'd3;  // x-monitor: saw "1"
    localparam SX2  = 4'd4;  // x-monitor: saw "10"
    localparam G0   = 4'd5;  // g = 1, first y-check cycle
    localparam G1   = 4'd6;  // g = 1, second y-check cycle
    localparam GON  = 4'd7;  // g = 1 permanently
    localparam GOFF = 4'd8;  // g = 0 permanently

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:    next = B;
            B:    next = SX0;
            SX0:  next = x ? SX1 : SX0;
            SX1:  next = x ? SX1 : SX2;
            SX2:  next = x ? G0  : SX0;
            G0:   next = y ? GON : G1;
            G1:   next = y ? GON : GOFF;
            GON:  next = GON;
            GOFF: next = GOFF;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else
            state <= next;
    end

    assign f = (state == B);
    assign g = (state == G0) || (state == G1) || (state == GON);

endmodule
