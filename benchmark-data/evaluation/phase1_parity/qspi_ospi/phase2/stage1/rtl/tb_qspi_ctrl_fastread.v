// =====================================================================
// tb_qspi_ctrl_fastread — self-checking TB for qspi_ctrl
//   Transaction: Fast Read (0x0B), mode 1-1-1, 24-bit address, 8 dummy
//   cycles, 4 read data bytes.  [L3 read_mode_examples: 0x0B 1-1-1 dummy=8]
//
//   A simple behavioral SPI-flash slave model lives in the TB.  It:
//     - watches CS#/SCLK,
//     - shifts in the 8-bit opcode + 24-bit address on IO0 (MOSI),
//     - waits 8 dummy SCLK cycles,
//     - then shifts a known data pattern OUT on IO1 (MISO), MSB-first,
//       sampled by the controller on the rising edge (mode-0).
//   The captured RDATA CSR must equal the model's pattern => PASS.
//
//   STROBE RULE (v0.1.96 capture): `done` is a 1-clk strobe; we latch it
//   concurrently in an always block, never poll after a task returns.
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_qspi_ctrl_fastread;

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

    // ---- 10 ns clock ----
    always #5 clk = ~clk;

    // ---- DUT ----
    qspi_ctrl #(.ADDR_BITS(ADDR_BITS), .DATA_BYTES(DATA_BYTES)) dut (
        .clk(clk), .rst_n(rst_n),
        .csr_addr(csr_addr), .csr_wdata(csr_wdata),
        .csr_we(csr_we), .csr_re(csr_re), .csr_rdata(csr_rdata),
        .sclk(sclk), .cs_n(cs_n),
        .io_out(io_out), .io_oe(io_oe), .io_in(io_in),
        .busy(busy), .done(done)
    );

    // ---- concurrent done latch (STROBE RULE) ----
    reg done_seen;
    always @(posedge clk) begin
        if (!rst_n)      done_seen <= 1'b0;
        else if (done)   done_seen <= 1'b1;
    end

    // =================================================================
    // Behavioral SPI-flash slave model (Fast Read 0x0B, 1-1-1).
    // Drives IO1 (MISO) only; samples IO0 (MOSI) on SCLK rising edge.
    // =================================================================
    localparam [31:0] FLASH_PATTERN = 32'hA5_3C_F0_69;  // 4 bytes, byte0 first
    integer       fl_bit;          // bit position being shifted out (MSB-first across 4 bytes)
    integer       sclk_count;      // SCLK rising edges since CS# fell
    reg           prev_sclk;
    reg           miso_drive;      // current MISO level the model presents
    reg  [31:0]   flash_sr;        // model output shift register

    // The Fast Read frame from the controller is:
    //   8 opcode + 24 address + 8 dummy = 40 SCLK cycles, THEN
    //   32 data cycles where the model drives MISO.
    localparam integer PRE_DATA_EDGES = 8 + 24 + 8;   // = 40

    always @(posedge clk) begin
        if (!rst_n) begin
            sclk_count <= 0;
            prev_sclk  <= 1'b0;
            miso_drive <= 1'b0;
            flash_sr   <= FLASH_PATTERN;
        end else begin
            prev_sclk <= sclk;
            if (cs_n) begin
                sclk_count <= 0;
                flash_sr   <= FLASH_PATTERN;
                miso_drive <= 1'b0;
            end else begin
                // rising edge of SCLK
                if (sclk && !prev_sclk) begin
                    sclk_count <= sclk_count + 1;
                end
                // After PRE_DATA_EDGES, the model presents data MSB-first.
                // The controller samples MISO on the rising edge, so the
                // model updates MISO just after each falling edge.
                if (!sclk && prev_sclk) begin   // falling edge
                    if (sclk_count >= PRE_DATA_EDGES) begin
                        miso_drive <= flash_sr[31];
                        flash_sr   <= {flash_sr[30:0], 1'b0};
                    end
                end
                // Present the FIRST data bit right when the data window opens
                // (on the falling edge that ends the last dummy cycle).
                if (!sclk && prev_sclk && (sclk_count == PRE_DATA_EDGES)) begin
                    miso_drive <= FLASH_PATTERN[31];
                    flash_sr   <= {FLASH_PATTERN[30:0], 1'b0};
                end
            end
        end
    end

    // Model drives IO1 (MISO) only when the controller has released it
    // (io_oe[1]==0) and CS# is low; otherwise hi-Z (TB drives 0 elsewhere).
    always @(*) begin
        io_in = 4'b0000;
        if (!cs_n && !io_oe[1]) io_in[1] = miso_drive;
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
            @(posedge clk); #1;  // registered rdata settles
        end
    endtask

    // =================================================================
    // Stimulus
    // =================================================================
    integer timeout;
    initial begin
        csr_addr = 0; csr_wdata = 0; csr_we = 0; csr_re = 0;
        rst_n = 1'b0;
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        // Program a fast SCLK (divisor 0 => toggle each clk) and the command.
        csr_write(4'd1, 32'd0);                       // SPIBR divisor = 0
        // CMD: opcode=0x0B, dummy=8, lane=0(single), has_addr=1, is_read=1, nbytes=4
        //  [7:0]=0x0B [11:8]=8 [13:12]=0 [14]=1 [15]=1 [23:16]=4
        csr_write(4'd2, {8'd0, 8'd4, 1'b1, 1'b1, 2'd0, 4'd8, 8'h0B});
        csr_write(4'd3, {8'd0, 24'hAB_CD_EF});        // ADDR
        // launch
        csr_write(4'd7, 32'h1);                       // START

        // Wait for completion via the concurrent latch.
        timeout = 0;
        while (!done_seen && timeout < 20000) begin
            @(posedge clk); timeout = timeout + 1;
        end

        if (!done_seen) begin
            $display("FAIL: command never completed (timeout)");
            $finish;
        end

        // Read back the captured data.
        csr_read(4'd6);   // RDATA

        $display("[fastread] opcode=0x0B addr=0xABCDEF dummy=8  rdata=0x%08h (exp 0x%08h)",
                 csr_rdata, FLASH_PATTERN);

        if (csr_rdata == FLASH_PATTERN) begin
            $display("FASTREAD TB PASS");
        end else begin
            $display("FAIL: rdata mismatch got 0x%08h exp 0x%08h", csr_rdata, FLASH_PATTERN);
        end
        $finish;
    end

endmodule

`default_nettype wire
