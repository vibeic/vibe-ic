// =====================================================================
// tb_hdlc_loopback — TX->RX loopback self-checking testbench
// ---------------------------------------------------------------------
// Frames a known payload with the TX framer, captures the serialised
// bitstream (opening flag + zero-stuffed payload+FCS + closing flag)
// off tx_bit/tx_bit_valid, feeds it bit-for-bit into the RX deframer,
// and asserts:
//   (1) the recovered payload bytes == the loaded payload,
//   (2) fcs_ok == 1 (FCS-16 residue matched),
//   (3) rx_len == payload length,
//   (4) the captured body bitstream contains NO accidental 0x7E flag
//       between the two real flags (proves zero-bit insertion worked).
// PASS prints "LOOPBACK TB PASS"; any mismatch prints FAIL and $finish.
//
// Strobe rule: frame_valid is a 1-clk pulse — a concurrent always-block
// latches it (and fcs_ok/rx_len) the instant it asserts, never polled.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_hdlc_loopback;
    localparam integer MAXB = 8;
    localparam integer IDXW = 4;

    reg               clk = 1'b0;
    reg               rst_n = 1'b0;

    // TX side
    reg  [IDXW-1:0]   tx_len   = 0;
    reg  [7:0]        tx_wdata = 0;
    reg  [IDXW-1:0]   tx_waddr = 0;
    reg               tx_we    = 0;
    reg               tx_start = 0;
    wire              tx_busy;
    wire              tx_done;
    wire              tx_bit;
    wire              tx_bit_valid;

    // RX side
    reg               rx_bit       = 1'b1;
    reg               rx_bit_valid = 1'b0;
    reg  [IDXW-1:0]   rx_raddr     = 0;
    wire [7:0]        rx_rdata;
    wire [IDXW-1:0]   rx_len;
    wire              frame_valid;
    wire              fcs_ok;
    wire              rx_abort;
    wire              rx_idle;
    wire              rx_overrun;

    hdlc_core #(.MAX_PAYLOAD_BYTES(MAXB), .IDXW(IDXW)) dut (
        .clk(clk), .rst_n(rst_n),
        .tx_len(tx_len), .tx_wdata(tx_wdata), .tx_waddr(tx_waddr),
        .tx_we(tx_we), .tx_start(tx_start), .tx_busy(tx_busy), .tx_done(tx_done),
        .tx_bit(tx_bit), .tx_bit_valid(tx_bit_valid),
        .rx_bit(rx_bit), .rx_bit_valid(rx_bit_valid),
        .rx_raddr(rx_raddr), .rx_rdata(rx_rdata), .rx_len(rx_len),
        .frame_valid(frame_valid), .fcs_ok(fcs_ok),
        .rx_abort(rx_abort), .rx_idle(rx_idle), .rx_overrun(rx_overrun)
    );

    always #5 clk = ~clk;

    // ---- concurrent capture of the 1-clk frame_valid pulse ----------
    reg        seen_valid = 1'b0;
    reg        cap_fcs_ok = 1'b0;
    reg [IDXW-1:0] cap_len = 0;
    always @(posedge clk) begin
        if (frame_valid && !seen_valid) begin
            seen_valid <= 1'b1;
            cap_fcs_ok <= fcs_ok;
            cap_len    <= rx_len;
        end
    end

    // ---- capture the serialised TX bitstream ------------------------
    reg [0:255] cap_bits;          // up to 256 captured wire bits
    integer     cap_n = 0;
    always @(posedge clk) begin
        if (tx_bit_valid && (cap_n < 256)) begin
            cap_bits[cap_n] <= tx_bit;
            cap_n           <= cap_n + 1;
        end
    end

    // ---- payload under test -----------------------------------------
    reg [7:0] payload [0:3];
    integer   plen = 4;
    integer   i, k;
    integer   errors = 0;
    integer   ones, flag_inside;

    task load_byte(input [IDXW-1:0] a, input [7:0] d);
        begin
            @(posedge clk); #1; tx_waddr = a; tx_wdata = d; tx_we = 1'b1;
            @(posedge clk); #1; tx_we = 1'b0;
        end
    endtask

    initial begin
        payload[0] = 8'hC0;   // address
        payload[1] = 8'h03;   // control (UI-ish)
        payload[2] = 8'hAA;   // info
        payload[3] = 8'h55;   // info

        // reset
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        // load payload
        for (i = 0; i < plen; i = i + 1) load_byte(i[IDXW-1:0], payload[i]);

        // launch framer
        @(posedge clk); #1; tx_len = plen[IDXW-1:0]; tx_start = 1'b1;
        @(posedge clk); #1; tx_start = 1'b0;

        // wait for TX to finish serialising
        wait (tx_done == 1'b1);
        @(posedge clk);
        repeat (2) @(posedge clk);   // let the last capture settle

        $display("[TB] captured %0d serial bits", cap_n);

        // ---- check no accidental 0x7E flag inside the body ----------
        // The body is between the opening flag (bits 0..7) and the
        // closing flag (last 8 bits).  An accidental flag = 6 ones in a
        // row anywhere in the body would be a stuffing failure.
        flag_inside = 0;
        ones = 0;
        for (k = 8; k < cap_n - 8; k = k + 1) begin
            if (cap_bits[k]) begin
                ones = ones + 1;
                if (ones >= 6) flag_inside = 1;   // 6+ ones => a 0x7E could form
            end else begin
                ones = 0;
            end
        end
        if (flag_inside) begin
            $display("[TB] FAIL: body bitstream has 6+ consecutive ones (zero-insertion broke)");
            errors = errors + 1;
        end else begin
            $display("[TB] OK: no 6-ones run in body (zero-bit insertion verified)");
        end

        // ---- feed the captured bitstream into the deframer ----------
        // Precede with idle ones so the hunt starts cleanly.
        rx_bit = 1'b1; rx_bit_valid = 1'b0;
        repeat (4) @(posedge clk);
        for (k = 0; k < cap_n; k = k + 1) begin
            @(posedge clk); #1;
            rx_bit       = cap_bits[k];
            rx_bit_valid = 1'b1;
        end
        @(posedge clk); #1;
        rx_bit_valid = 1'b0;
        rx_bit       = 1'b1;
        repeat (4) @(posedge clk);

        // ---- check recovery -----------------------------------------
        if (!seen_valid) begin
            $display("[TB] FAIL: frame_valid never asserted");
            errors = errors + 1;
        end else begin
            if (!cap_fcs_ok) begin
                $display("[TB] FAIL: fcs_ok=0 (FCS residue mismatch)");
                errors = errors + 1;
            end
            if (cap_len !== plen[IDXW-1:0]) begin
                $display("[TB] FAIL: rx_len=%0d expected %0d", cap_len, plen);
                errors = errors + 1;
            end
            for (i = 0; i < plen; i = i + 1) begin
                @(posedge clk); rx_raddr = i[IDXW-1:0];
                @(posedge clk);
                if (rx_rdata !== payload[i]) begin
                    $display("[TB] FAIL: byte[%0d]=%02h expected %02h", i, rx_rdata, payload[i]);
                    errors = errors + 1;
                end else begin
                    $display("[TB] byte[%0d]=%02h OK", i, rx_rdata);
                end
            end
        end

        if (errors == 0)
            $display("LOOPBACK TB PASS  (payload C0 03 AA 55 round-tripped, fcs_ok=%0b, len=%0d)",
                     cap_fcs_ok, cap_len);
        else
            $display("LOOPBACK TB FAIL  (%0d errors)", errors);
        $finish;
    end

    // global timeout
    initial begin
        #200000;
        $display("LOOPBACK TB FAIL  (timeout)");
        $finish;
    end
endmodule

`default_nettype wire
