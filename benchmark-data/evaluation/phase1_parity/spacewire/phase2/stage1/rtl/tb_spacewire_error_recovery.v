// =====================================================================
// tb_spacewire_error_recovery — SpaceWire link error-recovery TB
// ---------------------------------------------------------------------
// Checks:
//   1. Bring the DUT up to Run (ErrorReset->...->Run) via the NULL/FCT
//      handshake, accumulating TX credit.
//   2. PARITY error: inject a character with a deliberately WRONG parity
//      bit while in Run. The FSM must raise err_parity and return to
//      ErrorReset, and tx_credit must reset to 0.
//   3. Re-bring-up after the parity error to confirm recovery works.
//   4. DISCONNECT error: bring up to Run again, then stop all peer
//      activity (no received bits). After the disconnect timeout the FSM
//      must raise err_disconnect and return to ErrorReset, credit reset.
//
// Peer format identical to tb_spacewire_bringup_credit (LSB-first;
// 4-bit control / 10-bit data; odd parity). peer_send_bad_parity_ctrl
// flips the parity bit to force a parity error.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_spacewire_error_recovery;

    localparam integer T_RESET = 8;
    localparam integer T_WAIT  = 16;

    reg clk = 1'b0;
    reg rst_n;
    always #5 clk = ~clk;

    reg        link_start, link_autostart, link_disable;
    reg        tx_data_valid;
    reg  [7:0] tx_data;
    wire       tx_data_ack;
    wire       rx_data_valid;
    wire [7:0] rx_data;
    wire       rx_eop, rx_eep;
    wire       d_out, s_out, tx_bit_clk;
    reg        d_in, s_in, rx_bit_valid;
    wire [2:0] link_state;
    wire       link_run;
    wire [6:0] tx_credit;
    wire [2:0] rx_outstanding_fct;
    wire       err_disconnect, err_parity, err_escape, err_credit;

    localparam [2:0] S_ERRRESET=0, S_ERRWAIT=1, S_READY=2,
                     S_STARTED=3, S_CONNECTING=4, S_RUN=5;
    localparam [1:0] CC_FCT=2'b00, CC_EOP=2'b01, CC_EEP=2'b10, CC_ESC=2'b11;

    spacewire_link #(.T_RESET(T_RESET), .T_WAIT(T_WAIT), .RX_BUF_CHARS(16)) dut (
        .clk(clk), .rst_n(rst_n),
        .link_start(link_start), .link_autostart(link_autostart),
        .link_disable(link_disable),
        .tx_data_valid(tx_data_valid), .tx_data(tx_data), .tx_data_ack(tx_data_ack),
        .rx_data_valid(rx_data_valid), .rx_data(rx_data),
        .rx_eop(rx_eop), .rx_eep(rx_eep),
        .d_out(d_out), .s_out(s_out), .tx_bit_clk(tx_bit_clk),
        .d_in(d_in), .s_in(s_in), .rx_bit_valid(rx_bit_valid),
        .link_state(link_state), .link_run(link_run),
        .tx_credit(tx_credit), .rx_outstanding_fct(rx_outstanding_fct),
        .err_disconnect(err_disconnect), .err_parity(err_parity),
        .err_escape(err_escape), .err_credit(err_credit)
    );

    integer errors = 0;

    // Sticky monitors: error flags are cleared by the DUT when it reaches
    // ErrorReset, so latch them the instant they assert (one-cycle strobes
    // latched concurrently, per the TB strobe rule). Cleared by the TB
    // between phases via clear_error_latches.
    reg seen_parity, seen_disconnect, seen_escape, seen_credit;
    always @(posedge clk) begin
        if (err_parity)     seen_parity     <= 1'b1;
        if (err_disconnect) seen_disconnect <= 1'b1;
        if (err_escape)     seen_escape     <= 1'b1;
        if (err_credit)     seen_credit     <= 1'b1;
    end
    task clear_error_latches;
        begin
            seen_parity=0; seen_disconnect=0; seen_escape=0; seen_credit=0;
        end
    endtask

    reg peer_prev_bit;
    task peer_send_bit;
        input b;
        begin
            @(negedge clk);
            if (b == peer_prev_bit) s_in = ~s_in; else s_in = s_in;
            d_in = b;
            peer_prev_bit = b;
            rx_bit_valid = 1'b1;
            @(negedge clk);
            rx_bit_valid = 1'b0;
        end
    endtask

    task peer_send_ctrl;
        input [1:0] ctrl;
        reg par;
        begin
            par = ~(^{1'b1, ctrl});
            peer_send_bit(par);
            peer_send_bit(1'b1);
            peer_send_bit(ctrl[0]);
            peer_send_bit(ctrl[1]);
        end
    endtask

    // control char with deliberately WRONG parity (flips the parity bit)
    task peer_send_ctrl_badparity;
        input [1:0] ctrl;
        reg par;
        begin
            par = ~(^{1'b1, ctrl});
            peer_send_bit(~par);            // <-- corrupted parity
            peer_send_bit(1'b1);
            peer_send_bit(ctrl[0]);
            peer_send_bit(ctrl[1]);
        end
    endtask

    task peer_send_null;
        begin
            peer_send_ctrl(CC_ESC);
            peer_send_ctrl(CC_FCT);
        end
    endtask

    // bring the DUT all the way up to Run
    task bring_up_to_run;
        begin
            // wait for Ready
            repeat (T_RESET + T_WAIT + 10) @(negedge clk);
            link_start = 1;
            @(negedge clk); @(negedge clk);
            // NULL -> Connecting
            peer_send_null();
            repeat (3) @(negedge clk);
            // FCT -> Run (grants credit)
            peer_send_ctrl(CC_FCT);
            repeat (3) @(negedge clk);
        end
    endtask

    task expect_state;
        input [2:0] s;
        input [127:0] name;
        begin
            if (link_state !== s) begin
                $display("  FAIL: expected %0s(%0d) got %0d", name, s, link_state);
                errors = errors + 1;
            end else begin
                $display("  ok  : state == %0s", name);
            end
        end
    endtask

    initial begin
        link_start=0; link_autostart=0; link_disable=0;
        tx_data_valid=0; tx_data=8'h00;
        d_in=0; s_in=0; rx_bit_valid=0; peer_prev_bit=0;
        seen_parity=0; seen_disconnect=0; seen_escape=0; seen_credit=0;
        rst_n=0;
        repeat (4) @(negedge clk);
        rst_n=1;

        $display("== SpaceWire error-recovery TB ==");

        // ---- Phase 1: bring up to Run ----
        bring_up_to_run();
        expect_state(S_RUN, "Run (initial bring-up)");
        if (tx_credit == 7'd0) begin
            $display("  FAIL: no credit after bring-up"); errors=errors+1;
        end else
            $display("  ok  : credit after bring-up = %0d (>0)", tx_credit);

        // ---- Phase 2: inject a PARITY error in Run ----
        $display("  -- injecting parity error in Run --");
        clear_error_latches();
        peer_send_ctrl_badparity(CC_FCT);   // corrupted control char
        repeat (4) @(negedge clk);
        if (!seen_parity) begin
            $display("  FAIL: parity error not flagged on corrupted char"); errors=errors+1;
        end else
            $display("  ok  : err_parity asserted (latched)");
        // FSM must have returned toward ErrorReset; credit must reset.
        // (it may already be walking ErrorReset->ErrorWait by now)
        if (link_state == S_RUN) begin
            $display("  FAIL: still in Run after parity error"); errors=errors+1;
        end else
            $display("  ok  : left Run after parity error (state=%0d)", link_state);
        if (tx_credit != 7'd0) begin
            $display("  FAIL: credit not reset after error (=%0d)", tx_credit); errors=errors+1;
        end else
            $display("  ok  : tx_credit reset to 0 after error");

        // give the FSM time to settle back into the ErrorReset/ErrorWait cycle
        link_start = 0;
        repeat (4) @(negedge clk);
        // it should be cycling through the reset/wait/ready handshake again
        if (link_state == S_ERRRESET || link_state == S_ERRWAIT ||
            link_state == S_READY) begin
            $display("  ok  : FSM back in bring-up handshake (state=%0d) after error", link_state);
        end else begin
            $display("  FAIL: unexpected state %0d after parity error", link_state);
            errors = errors + 1;
        end

        // ---- Phase 3: confirm RECOVERY — re-bring-up to Run ----
        $display("  -- re-bring-up after parity error --");
        bring_up_to_run();
        expect_state(S_RUN, "Run (recovered)");
        if (tx_credit == 7'd0) begin
            $display("  FAIL: no credit after recovery"); errors=errors+1;
        end else
            $display("  ok  : credit restored after recovery = %0d", tx_credit);

        // ---- Phase 4: DISCONNECT error — stop all peer activity in Run ----
        $display("  -- injecting disconnect (peer goes silent) in Run --");
        clear_error_latches();
        // stop sending any bits; wait past the disconnect timeout
        repeat (T_WAIT*2 + 20) @(negedge clk);
        if (!seen_disconnect) begin
            $display("  FAIL: disconnect not flagged after silence"); errors=errors+1;
        end else
            $display("  ok  : err_disconnect asserted after peer silence (latched)");
        if (tx_credit != 7'd0) begin
            $display("  FAIL: credit not reset after disconnect (=%0d)", tx_credit); errors=errors+1;
        end else
            $display("  ok  : tx_credit reset to 0 after disconnect");
        if (link_state == S_RUN) begin
            $display("  FAIL: still in Run after disconnect"); errors=errors+1;
        end else
            $display("  ok  : left Run after disconnect (state=%0d)", link_state);

        $display("------------------------------------------------------");
        if (errors == 0) $display("ERROR_RECOVERY TB PASS");
        else             $display("ERROR_RECOVERY TB FAIL (%0d errors)", errors);
        $finish;
    end

    initial begin
        #300000;
        $display("ERROR_RECOVERY TB FAIL (timeout)");
        $finish;
    end

endmodule

`default_nettype wire
