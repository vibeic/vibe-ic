// =====================================================================
// tb_qspi_ctrl_quad — self-checking TB for qspi_ctrl (lane-mode + status)
//
//   Two back-to-back transactions exercising a DIFFERENT lane mode and
//   the no-data command path than the Fast Read TB:
//
//   (1) Write Enable (WREN, 0x06): instruction-only command — 1 lane,
//       no address, no dummy, no data.  [L3/L4 0x06]  Verifies the FSM
//       runs INSTRUCTION -> DONE directly and that the controller drove
//       the correct 8-bit opcode on IO0 (captured by a TB monitor).
//
//   (2) Quad Output Fast Read (0x6B, mode 1-1-4, 8 dummy): instruction +
//       24-bit address on 1 lane, 8 dummy cycles, then 4 data bytes read
//       on FOUR lanes (IO0..IO3).  [L3 read_mode_examples: 0x6B 1-1-4 dummy=8]
//       A quad-capable behavioral flash model presents 4 bits/edge on
//       IO0..IO3; the captured RDATA must equal the known pattern.
//
//   STROBE RULE (v0.1.96 capture): `done` is a 1-clk strobe; latched
//   concurrently in an always block, never polled after a task returns.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_qspi_ctrl_quad;

    localparam integer ADDR_BITS  = 24;
    localparam integer DATA_BYTES = 4;
    localparam integer DATA_BITS  = 8*DATA_BYTES;

    reg         clk = 1'b0;
    reg         rst_n = 1'b0;
    reg  [3:0]  csr_addr;
    reg  [31:0] csr_wdata;
    reg         csr_we, csr_re;
    wire [31:0] csr_rdata;

    wire        sclk, cs_n;
    wire [3:0]  io_out, io_oe;
    reg  [3:0]  io_in;
    wire        busy, done;

    always #5 clk = ~clk;

    qspi_ctrl #(.ADDR_BITS(ADDR_BITS), .DATA_BYTES(DATA_BYTES)) dut (
        .clk(clk), .rst_n(rst_n),
        .csr_addr(csr_addr), .csr_wdata(csr_wdata),
        .csr_we(csr_we), .csr_re(csr_re), .csr_rdata(csr_rdata),
        .sclk(sclk), .cs_n(cs_n),
        .io_out(io_out), .io_oe(io_oe), .io_in(io_in),
        .busy(busy), .done(done)
    );

    // ---- concurrent done latch + count ----
    reg done_seen;
    always @(posedge clk) begin
        if (!rst_n)    done_seen <= 1'b0;
        else if (done) done_seen <= 1'b1;
    end

    // =================================================================
    // WREN opcode monitor: capture the 8 bits the controller drives on
    // IO0 (MOSI) during the instruction phase, sampled on SCLK rising.
    // =================================================================
    reg [7:0] wren_captured;
    reg [3:0] wren_bits;
    reg       prev_sclk_w;
    reg       wren_active;
    always @(posedge clk) begin
        if (!rst_n) begin
            wren_captured <= 8'd0; wren_bits <= 4'd0;
            prev_sclk_w <= 1'b0;  wren_active <= 1'b0;
        end else begin
            prev_sclk_w <= sclk;
            if (cs_n) wren_active <= 1'b0;
            else      wren_active <= 1'b1;
            if (wren_active && sclk && !prev_sclk_w && wren_bits < 4'd8) begin
                wren_captured <= {wren_captured[6:0], io_out[0]};
                wren_bits     <= wren_bits + 4'd1;
            end
        end
    end

    // =================================================================
    // Quad-output flash model (0x6B, 1-1-4).  Frame from the controller:
    //   8 opcode + 24 addr (1 lane) + 8 dummy = 40 SCLK cycles, then
    //   8 quad-data cycles (4 bits/edge) for 4 bytes.  Model drives
    //   IO0..IO3 only during the data window; controller samples on rising.
    // =================================================================
    localparam [31:0] QPATTERN = 32'h5A_C3_0F_96;  // 4 bytes
    localparam integer PRE_DATA_EDGES_Q = 8 + 24 + 8;  // = 40
    integer     q_count;
    reg         prev_sclk_q;
    reg  [3:0]  quad_drive;
    reg  [31:0] quad_sr;

    always @(posedge clk) begin
        if (!rst_n) begin
            q_count <= 0; prev_sclk_q <= 1'b0;
            quad_drive <= 4'd0; quad_sr <= QPATTERN;
        end else begin
            prev_sclk_q <= sclk;
            if (cs_n) begin
                q_count <= 0; quad_sr <= QPATTERN; quad_drive <= 4'd0;
            end else begin
                if (sclk && !prev_sclk_q) q_count <= q_count + 1;
                // present the next nibble just after each falling edge,
                // MSB nibble first, so the controller samples it on the
                // following rising edge.
                if (!sclk && prev_sclk_q && q_count >= PRE_DATA_EDGES_Q) begin
                    quad_drive <= quad_sr[31:28];
                    quad_sr    <= {quad_sr[27:0], 4'b0000};
                end
            end
        end
    end

    // Model drives IO0..IO3 only when the controller released them
    // (io_oe==0) and CS# low; else hi-Z (TB presents 0 elsewhere).
    always @(*) begin
        io_in = 4'b0000;
        if (!cs_n && (io_oe == 4'b0000)) io_in = quad_drive;
    end

    // =================================================================
    // CSR helper tasks
    // =================================================================
    task csr_write(input [3:0] a, input [31:0] d);
        begin
            @(posedge clk); #1;
            csr_addr = a; csr_wdata = d; csr_we = 1'b1;
            @(posedge clk); #1;
            csr_we = 1'b0; csr_wdata = 32'd0;
        end
    endtask

    task csr_read(input [3:0] a);
        begin
            @(posedge clk); #1;
            csr_addr = a; csr_re = 1'b1;
            @(posedge clk); #1;
            csr_re = 1'b0;
            @(posedge clk); #1;
        end
    endtask

    integer timeout;
    integer errors;
    initial begin
        errors = 0;
        csr_addr = 0; csr_wdata = 0; csr_we = 0; csr_re = 0;
        rst_n = 1'b0;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        csr_write(4'd1, 32'd0);   // SPIBR divisor 0 (fast)

        // -------- (1) WREN 0x06: opcode only, no addr/dummy/data --------
        // CMD: opcode=0x06, dummy=0, lane=0, has_addr=0, is_read=0, nbytes=0
        csr_write(4'd2, {8'd0, 8'd0, 1'b0, 1'b0, 2'd0, 4'd0, 8'h06});
        force done_seen = 1'b0; release done_seen;
        csr_write(4'd7, 32'h1);   // START
        timeout = 0;
        while (!done_seen && timeout < 5000) begin @(posedge clk); timeout = timeout + 1; end
        if (!done_seen) begin $display("FAIL: WREN never completed"); errors = errors + 1; end
        $display("[quad] WREN: controller drove opcode 0x%02h on IO0 (exp 0x06)", wren_captured);
        if (wren_captured !== 8'h06) begin
            $display("FAIL: WREN opcode mismatch got 0x%02h exp 0x06", wren_captured);
            errors = errors + 1;
        end

        // -------- (2) Quad Output Fast Read 0x6B, 1-1-4, 8 dummy --------
        // lane=1 (quad data only), has_addr=1, is_read=1, nbytes=4, dummy=8
        @(posedge clk);
        force done_seen = 1'b0; release done_seen;
        csr_write(4'd2, {8'd0, 8'd4, 1'b1, 1'b1, 2'd1, 4'd8, 8'h6B});
        csr_write(4'd3, {8'd0, 24'h12_34_56});  // ADDR
        csr_write(4'd7, 32'h1);   // START
        timeout = 0;
        while (!done_seen && timeout < 20000) begin @(posedge clk); timeout = timeout + 1; end
        if (!done_seen) begin $display("FAIL: Quad read never completed"); errors = errors + 1; end

        csr_read(4'd6);  // RDATA
        $display("[quad] 0x6B 1-1-4 dummy=8 rdata=0x%08h (exp 0x%08h)", csr_rdata, QPATTERN);
        if (csr_rdata !== QPATTERN) begin
            $display("FAIL: quad rdata mismatch got 0x%08h exp 0x%08h", csr_rdata, QPATTERN);
            errors = errors + 1;
        end

        if (errors == 0) $display("QUAD TB PASS");
        else             $display("QUAD TB FAIL (%0d error(s))", errors);
        $finish;
    end

endmodule

`default_nettype wire
