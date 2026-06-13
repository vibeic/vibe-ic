module TopModule(
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // Count of consecutive 1s seen so far (saturating).
    // ones = number of consecutive 1s ending at the most-recent input bit.
    // States: 0..6 ones, plus ERR (>=7 ones, latched until a 0).
    localparam ERR = 7;

    reg [2:0] ones;     // 0..6 normal, 7 = error
    reg disc_r, flag_r, err_r;

    // Next consecutive-ones value
    reg [2:0] ones_n;
    always @(*) begin
        if (in) begin
            if (ones == ERR)      ones_n = ERR;        // stay in error
            else if (ones == 6)   ones_n = ERR;        // 7th one -> error
            else                  ones_n = ones + 3'd1;
        end else begin
            ones_n = 3'd0;                              // a 0 resets the run
        end
    end

    // Output conditions: detected on the 0 that terminates a run.
    // disc: run of exactly 5 ones then 0  (ones==5 && in==0)
    // flag: run of exactly 6 ones then 0  (ones==6 && in==0)
    // err : 7 or more ones (entering / staying in ERR while in==1)
    always @(posedge clk) begin
        if (reset) begin
            ones   <= 3'd0;
            disc_r <= 1'b0;
            flag_r <= 1'b0;
            err_r  <= 1'b0;
        end else begin
            ones   <= ones_n;
            disc_r <= (ones == 3'd5) && (in == 1'b0);
            flag_r <= (ones == 3'd6) && (in == 1'b0);
            err_r  <= (ones == ERR || ones == 3'd6) && (in == 1'b1);
        end
    end

    assign disc = disc_r;
    assign flag = flag_r;
    assign err  = err_r;
endmodule
