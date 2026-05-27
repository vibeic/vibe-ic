module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output reg z
);

    // A    : idle until s=1.
    // E0   : first examine cycle (entered from A); current w is sample 1.
    // E1_c : after 1 sample, count c (0/1); current w is sample 2.
    // E2_c : after 2 samples, count c (0/1/2); current w is sample 3.
    // Z/NZ : output cycle (z=1 iff exactly two w were 1); also sample 1 of the
    //        next back-to-back window.
    localparam A    = 4'd0,
               E0   = 4'd1,
               E1_0 = 4'd2,
               E1_1 = 4'd3,
               E2_0 = 4'd4,
               E2_1 = 4'd5,
               E2_2 = 4'd6,
               ZS   = 4'd7,
               NZS  = 4'd8;

    reg [3:0] state, nstate;

    always @(*) begin
        case (state)
            A:    nstate = s ? E0 : A;
            E0:   nstate = w ? E1_1 : E1_0;
            E1_0: nstate = w ? E2_1 : E2_0;
            E1_1: nstate = w ? E2_2 : E2_1;
            E2_0: nstate = w ? NZS : NZS;          // final 0 or 1 -> not two
            E2_1: nstate = w ? ZS  : NZS;          // final 2 or 1
            E2_2: nstate = w ? NZS : ZS;           // final 3 or 2
            ZS:   nstate = w ? E1_1 : E1_0;        // output cycle == sample 1 of next window
            NZS:  nstate = w ? E1_1 : E1_0;
            default: nstate = A;
        endcase
    end

    always @(*)
        z = (state == ZS);

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= nstate;
    end

endmodule
