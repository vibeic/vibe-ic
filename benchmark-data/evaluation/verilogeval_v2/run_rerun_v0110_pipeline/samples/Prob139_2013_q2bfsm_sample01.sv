module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);
    localparam A      = 4'd0,  // reset state
               SF     = 4'd1,  // f=1 for one cycle
               B      = 4'd2,  // looking for first 1 of 1,0,1
               B1     = 4'd3,  // saw 1
               B2     = 4'd4,  // saw 1,0
               G1     = 4'd5,  // g=1, first y observation
               G2     = 4'd6,  // g=1, second y observation
               GHOLD  = 4'd7,  // g=1 permanently
               GOFF   = 4'd8;  // g=0 permanently
    reg [3:0] state;

    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else begin
            case (state)
                A:  state <= SF;          // resetn de-asserted: next edge -> f pulse
                SF: state <= B;           // after f pulse, begin monitoring x
                B:  state <= x ? B1 : B;
                B1: state <= x ? B1 : B2; // saw 1; on 0 -> B2 (10)
                B2: state <= x ? G1 : B;  // saw 10; on 1 -> detected 101
                G1: state <= y ? GHOLD : G2;
                G2: state <= y ? GHOLD : GOFF;
                GHOLD: state <= GHOLD;
                GOFF:  state <= GOFF;
                default: state <= A;
            endcase
        end
    end

    assign f = (state == SF);
    assign g = (state == G1) || (state == G2) || (state == GHOLD);
endmodule
