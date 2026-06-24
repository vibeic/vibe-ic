// serial2parallel: collect 8 serial bits (MSB-first) into dout_parallel and
// pulse dout_valid when the word is complete. Active-low rst_n, posedge clk.
//
// Counter takes N+1 = 9 distinct values 0..8: the 8 data bits shift in while
// cnt is 0..7, the counter then advances to the DEDICATED terminal value 8,
// and on that cnt==8 cycle dout_valid is registered high and the assembled
// word is presented (one cycle beyond the last bit). din_valid qualifies the
// shift/increment; a paused din_valid HOLDS the count (it does not reset it),
// and the valid is NOT gated on din_valid, so a TB that streams 8 bits then
// keeps clocking while it waits for dout_valid always sees the pulse.
// MSB-first idiom: each new bit enters at the LSB end and the register shifts
// LEFT, so the FIRST received bit ends up at the MSB.
module serial2parallel (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       din_serial,
    input  wire       din_valid,
    output reg  [7:0] dout_parallel,
    output reg        dout_valid
);

    localparam N = 8;

    reg [3:0] cnt;          // 4-bit per spec; spans 0..8
    reg [7:0] shift_reg;    // assembly register

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt           <= 4'd0;
            shift_reg     <= 8'd0;
            dout_parallel <= 8'd0;
            dout_valid    <= 1'b0;
        end else begin
            dout_valid <= 1'b0;                 // default: single-cycle pulse
            if (cnt == N) begin
                dout_parallel <= shift_reg;     // present the assembled word
                dout_valid    <= 1'b1;
                if (din_valid) begin
                    shift_reg <= {shift_reg[6:0], din_serial}; // start next frame
                    cnt       <= 4'd1;
                end else begin
                    cnt <= 4'd0;
                end
            end else if (din_valid) begin
                shift_reg <= {shift_reg[6:0], din_serial};     // shift in (MSB-first)
                cnt       <= cnt + 4'd1;
            end
            // else (din_valid low, cnt!=N): HOLD count and shift_reg
        end
    end

endmodule
