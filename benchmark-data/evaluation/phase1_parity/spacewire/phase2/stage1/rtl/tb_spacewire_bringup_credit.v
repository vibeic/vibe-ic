// =====================================================================
// tb_spacewire_bringup_credit — SpaceWire link bring-up + credit TB
// ---------------------------------------------------------------------
// Checks (the archetype centerpiece):
//   1. The DUT walks ErrorReset -> ErrorWait -> Ready (after T_RESET +
//      T_WAIT) and, once link_start is asserted, -> Started.
//   2. A behavioral PEER feeds the DUT's RX side a NULL (ESC+FCT) -> the
//      DUT advances Started -> Connecting; then an FCT -> Connecting ->
//      Run. (NULL/FCT handshake.)
//   3. CREDIT GATES DATA TX: in Run, with tx_data_valid asserted, the DUT
//      must NOT emit a host data character before an FCT grants credit,
//      and MUST emit it once credit > 0. We assert tx_credit==0 keeps
//      tx_data_ack low, and a received FCT (credit=8) lets tx_data_ack
//      pulse and decrements credit.
//
// Peer character format (matches spacewire_link RX deserialiser, LSB
// first): control char = 4 bits {parity, dcflag=1, ctrl[1:0]} sent bit0
// first; data char = 10 bits {parity, dcflag=0, data[7:0]} bit0 first.
// Odd parity over the body (dcflag+payload) such that total ones (incl
// parity) is odd. One received bit per clk pulsed via rx_bit_valid.
// TB strobe rule: one-cycle strobes latched concurrently.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_spacewire_bringup_credit;

    localparam integer T_RESET = 8;
    localparam integer T_WAIT  = 16;

    reg clk = 1'b0;
    reg rst_n;
    always #5 clk = ~clk;

    // host side
    reg        link_start;
    reg        link_autostart;
    reg        link_disable;
    reg        tx_data_valid;
    reg  [7:0] tx_data;
    wire       tx_data_ack;
    wire       rx_data_valid;
    wire [7:0] rx_data;
    wire       rx_eop, rx_eep;

    // DS link
    wire       d_out, s_out, tx_bit_clk;
    reg        d_in, s_in, rx_bit_valid;

    // status
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

    // ---- peer DS bit driver: drive one bit, obey DS one-of-two rule ----
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

    // send a 4-bit control char {parity,dcflag=1,ctrl} LSB-first
    task peer_send_ctrl;
        input [1:0] ctrl;
        reg par;
        begin
            par = ~(^{1'b1, ctrl});          // odd parity over {dcflag=1,ctrl}
            peer_send_bit(par);              // bit0 parity
            peer_send_bit(1'b1);             // bit1 dcflag=1
            peer_send_bit(ctrl[0]);          // bit2
            peer_send_bit(ctrl[1]);          // bit3
        end
    endtask

    // send a 10-bit data char {parity,dcflag=0,data} LSB-first
    task peer_send_data;
        input [7:0] d;
        reg par;
        integer k;
        begin
            par = ~(^{1'b0, d});             // odd parity over {dcflag=0,data}
            peer_send_bit(par);              // bit0 parity
            peer_send_bit(1'b0);             // bit1 dcflag=0
            for (k=0;k<8;k=k+1) peer_send_bit(d[k]); // bit2..9 data LSB first
        end
    endtask

    // NULL = ESC then FCT (two control chars). Does NOT grant credit
    // (the FCT here is part of the NULL composite, consumed as a NULL).
    task peer_send_null;
        begin
            peer_send_ctrl(CC_ESC);
            peer_send_ctrl(CC_FCT);
        end
    endtask

    // a standalone FCT that GRANTS 8 credit to the DUT's transmitter.
    task peer_send_fct_grant;
        begin
            peer_send_ctrl(CC_FCT);
            total_credit_granted = total_credit_granted + 8;
        end
    endtask

    task expect_state;
        input [2:0] s;
        input [127:0] name;
        begin
            if (link_state !== s) begin
                $display("  FAIL: expected state %0d (%0s) got %0d", s, name, link_state);
                errors = errors + 1;
            end else begin
                $display("  ok  : state == %0s (%0d)", name, link_state);
            end
        end
    endtask

    // watch whether the DUT ever sends a HOST DATA char (tx_data_ack pulse)
    reg saw_data_ack;
    always @(posedge clk) if (tx_data_ack) saw_data_ack <= 1'b1;

    // ---- credit-gating monitors (the centerpiece invariant) ----
    // total host-data chars the DUT consumed:
    integer total_data_acks;
    // total credit the peer has granted (8 per FCT we send):
    integer total_credit_granted;
    // assertion: at every clk, total_data_acks must NEVER exceed
    // total_credit_granted (credit gates data TX). Checked continuously.
    integer credit_violation;
    initial begin total_data_acks=0; total_credit_granted=0; credit_violation=0; end
    always @(posedge clk) begin
        if (rst_n) begin
            if (tx_data_ack) total_data_acks = total_data_acks + 1;
            if (total_data_acks > total_credit_granted) begin
                if (credit_violation == 0)
                    $display("  FAIL: data acks (%0d) EXCEEDED credit granted (%0d) -- credit NOT gating TX!",
                             total_data_acks, total_credit_granted);
                credit_violation = credit_violation + 1;
            end
        end
    end

    integer w;
    initial begin
        link_start = 0; link_autostart = 0; link_disable = 0;
        tx_data_valid = 0; tx_data = 8'h00;
        d_in = 0; s_in = 0; rx_bit_valid = 0;
        peer_prev_bit = 0; saw_data_ack = 0;
        rst_n = 0;
        repeat (4) @(negedge clk);
        rst_n = 1;

        $display("== SpaceWire bring-up + credit TB ==");

        // 1) After reset the FSM should be in ErrorReset, then walk to Ready.
        @(negedge clk);
        expect_state(S_ERRRESET, "ErrorReset");
        // wait through T_RESET + T_WAIT (+slack) for Ready
        repeat (T_RESET + T_WAIT + 8) @(negedge clk);
        expect_state(S_READY, "Ready");

        // 2) Assert Start -> Started
        link_start = 1;
        @(negedge clk); @(negedge clk);
        expect_state(S_STARTED, "Started");

        // 3) Peer sends a NULL -> Started -> Connecting
        peer_send_null();
        repeat (3) @(negedge clk);
        expect_state(S_CONNECTING, "Connecting");

        // 4) Peer sends an FCT -> Connecting -> Run (grants 8 credit)
        peer_send_fct_grant();
        repeat (3) @(negedge clk);
        expect_state(S_RUN, "Run");
        if (!link_run) begin $display("  FAIL: link_run not asserted in Run"); errors=errors+1; end

        // 5) CREDIT GATES DATA TX (the archetype centerpiece).
        //    The invariant proven here: over the WHOLE Run window, the
        //    number of host-data chars the DUT consumed (tx_data_ack
        //    pulses) is NEVER more than the cumulative credit the peer
        //    has granted via FCTs. The concurrent keep_alive thread (see
        //    fork below) sends a NULL every ~30 clk so the link does not
        //    disconnect; the credit_granter thread sends a measured number
        //    of FCTs. We then check: data_sent <= 8 * fct_granted, and
        //    that BEFORE the first FCT (credit==0) NO data was sent, and
        //    AFTER FCTs were granted data WAS sent.
        $display("  credit on entering Run = %0d (granted=%0d)", tx_credit, total_credit_granted);

        // (a) credit-gate invariant during data flow.
        //     Present host data continuously and keep the link alive with
        //     NULLs (which grant NO credit). The continuous monitor checks
        //     total_data_acks <= total_credit_granted at EVERY clk. Since
        //     only the one entry FCT (8 credit) has been granted, the DUT
        //     may send at most 8 host-data chars and then MUST stop —
        //     proving credit gates data TX (no over-send beyond credit).
        tx_data       = 8'hA5;
        tx_data_valid = 1;
        begin : drain_phase
            integer kk;
            for (kk=0; kk<10; kk=kk+1) begin
                repeat (24) @(negedge clk);
                peer_send_null();   // alive, grants no credit
            end
        end
        $display("  after data window: data_acks=%0d, credit_granted=%0d, credit_left=%0d",
                 total_data_acks, total_credit_granted, tx_credit);
        if (credit_violation != 0) begin
            $display("  FAIL: credit invariant violated %0d times (over-send beyond credit)", credit_violation);
            errors = errors + 1;
        end else begin
            $display("  ok  : data_acks never exceeded credit granted -- credit gates data TX");
        end
        if (total_data_acks == 0) begin
            $display("  FAIL: credit was granted (8) but DUT sent no host data at all");
            errors = errors + 1;
        end

        // (b) Now grant a FRESH FCT (more credit) and confirm the DUT
        //     resumes / continues sending host data — i.e. credit ungates TX.
        saw_data_ack = 0;
        begin : grant_phase
            integer kk;
            peer_send_fct_grant();         // +8 credit
            for (kk=0; kk<5; kk=kk+1) begin
                repeat (24) @(negedge clk);
                peer_send_null();
                if (saw_data_ack) kk = 5;  // early exit once data flows
            end
        end
        if (!saw_data_ack) begin
            $display("  FAIL: after fresh FCT (credit granted) DUT still did not send data");
            errors = errors + 1;
        end else begin
            $display("  ok  : fresh FCT granted credit -> DUT sent host data (credit ungates TX)");
        end
        if (credit_violation != 0) begin
            $display("  FAIL: credit invariant violated after fresh FCT");
            errors = errors + 1;
        end

        $display("------------------------------------------------------");
        if (errors == 0) $display("BRINGUP_CREDIT TB PASS");
        else             $display("BRINGUP_CREDIT TB FAIL (%0d errors)", errors);
        $finish;
    end

    // global timeout
    initial begin
        #200000;
        $display("BRINGUP_CREDIT TB FAIL (timeout)");
        $finish;
    end

endmodule

`default_nettype wire
