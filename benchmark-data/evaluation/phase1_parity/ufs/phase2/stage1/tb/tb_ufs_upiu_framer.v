// =====================================================================
// tb_ufs_upiu_framer.v  —  self-checking TB for the UFS UPIU framer
// ---------------------------------------------------------------------
// Three directed tests:
//   T1  BUILD : program a Command UPIU header, build it, capture the 12
//               emitted bytes, compare to the golden wire layout.
//   T2  PARSE : stream a known Response UPIU header in, check every
//               parsed field + parse_valid==1 (valid txn type).
//   T3  PARSE-INVALID : stream a header with a reserved/invalid txn type
//               (6'h0A) and confirm parse_valid==0.
// PASS only if all checks pass; prints a final verdict line.
// =====================================================================

`timescale 1ns/1ps
`default_nettype none

module tb_ufs_upiu_framer;

    localparam integer HDR = 12;

    reg         clk = 1'b0;
    reg         rst = 1'b1;

    reg         reg_we;
    reg  [3:0]  reg_addr;
    reg  [15:0] reg_wdata;

    reg         build_start;
    wire [7:0]  tx_byte;
    wire        tx_valid;
    wire        build_done;

    reg  [7:0]  rx_byte;
    reg         rx_valid;
    wire        parse_done;
    wire        parse_valid;

    wire [5:0]  p_txn_type;
    wire [7:0]  p_flags;
    wire [7:0]  p_lun;
    wire [7:0]  p_task_tag;
    wire [3:0]  p_iid;
    wire [3:0]  p_cmd_set_type;
    wire [7:0]  p_query_func;
    wire [7:0]  p_response;
    wire [7:0]  p_status;
    wire [7:0]  p_ehs_len;
    wire [7:0]  p_dev_info;
    wire [15:0] p_data_seg_len;
    wire        busy;

    integer errors = 0;
    integer i;

    // captured build output
    reg [7:0] cap [0:HDR-1];
    integer   cap_n;

    // golden Command UPIU (T1)
    reg [7:0] gold [0:HDR-1];

    // ------------------------------------------------------------------
    ufs_upiu_framer #(.HDR_BYTES(HDR)) dut (
        .clk(clk), .rst(rst),
        .reg_we(reg_we), .reg_addr(reg_addr), .reg_wdata(reg_wdata),
        .build_start(build_start), .tx_byte(tx_byte), .tx_valid(tx_valid),
        .build_done(build_done),
        .rx_byte(rx_byte), .rx_valid(rx_valid),
        .parse_done(parse_done), .parse_valid(parse_valid),
        .p_txn_type(p_txn_type), .p_flags(p_flags), .p_lun(p_lun),
        .p_task_tag(p_task_tag), .p_iid(p_iid), .p_cmd_set_type(p_cmd_set_type),
        .p_query_func(p_query_func), .p_response(p_response), .p_status(p_status),
        .p_ehs_len(p_ehs_len), .p_dev_info(p_dev_info),
        .p_data_seg_len(p_data_seg_len), .busy(busy)
    );

    always #5 clk = ~clk;

    // --------------- register-write helper ---------------
    task wr_field(input [3:0] a, input [15:0] d);
        begin
            @(negedge clk);
            reg_we    = 1'b1;
            reg_addr  = a;
            reg_wdata = d;
            @(negedge clk);
            reg_we    = 1'b0;
            reg_addr  = 4'd0;
            reg_wdata = 16'd0;
        end
    endtask

    task check8(input [127:0] name, input [7:0] got, input [7:0] exp);
        begin
            if (got !== exp) begin
                errors = errors + 1;
                $display("  FAIL %0s : got 0x%02x exp 0x%02x", name, got, exp);
            end else begin
                $display("  ok   %0s = 0x%02x", name, got);
            end
        end
    endtask

    initial begin
        // init
        reg_we = 0; reg_addr = 0; reg_wdata = 0;
        build_start = 0; rx_byte = 0; rx_valid = 0;

        // reset
        repeat (3) @(negedge clk);
        rst = 1'b0;
        @(negedge clk);

        // ============================================================
        // T1 — BUILD a Command UPIU header.
        //   Transaction Type = COMMAND   = 6'h01
        //   Flags            = 0x01 (read direction bit, example)
        //   LUN              = 0x03
        //   Task Tag         = 0x07
        //   IID/CmdSetType   = IID=0x2 CST=0x0  -> byte = 0x20
        //   Query Func       = 0x00
        //   Response         = 0x00
        //   Status           = 0x00
        //   EHS Length       = 0x00
        //   Dev Info         = 0x00
        //   Data Seg Length  = 0x0010 (16 bytes CDB payload)
        // ============================================================
        $display("== T1 BUILD Command UPIU ==");
        gold[0]  = 8'h01; // {2'b00, 6'h01}
        gold[1]  = 8'h01;
        gold[2]  = 8'h03;
        gold[3]  = 8'h07;
        gold[4]  = 8'h20; // {IID=2, CST=0}
        gold[5]  = 8'h00;
        gold[6]  = 8'h00;
        gold[7]  = 8'h00;
        gold[8]  = 8'h00;
        gold[9]  = 8'h00;
        gold[10] = 8'h00; // DSL[15:8]
        gold[11] = 8'h10; // DSL[7:0]

        wr_field(4'd0,  16'h0001); // txn type
        wr_field(4'd1,  16'h0001); // flags
        wr_field(4'd2,  16'h0003); // lun
        wr_field(4'd3,  16'h0007); // task tag
        wr_field(4'd4,  16'h0020); // iid/cst
        wr_field(4'd5,  16'h0000); // query func
        wr_field(4'd6,  16'h0000); // response
        wr_field(4'd7,  16'h0000); // status
        wr_field(4'd8,  16'h0000); // ehs len
        wr_field(4'd9,  16'h0000); // dev info
        wr_field(4'd10, 16'h0010); // dsl

        // pulse build_start
        cap_n = 0;
        @(negedge clk);
        build_start = 1'b1;
        @(negedge clk);
        build_start = 1'b0;

        // capture tx_byte while tx_valid asserted
        while (cap_n < HDR) begin
            @(posedge clk);
            if (tx_valid) begin
                cap[cap_n] = tx_byte;
                cap_n = cap_n + 1;
            end
        end
        @(negedge clk);

        for (i = 0; i < HDR; i = i + 1) begin
            if (cap[i] !== gold[i]) begin
                errors = errors + 1;
                $display("  FAIL build byte[%0d] : got 0x%02x exp 0x%02x", i, cap[i], gold[i]);
            end else begin
                $display("  ok   build byte[%0d] = 0x%02x", i, cap[i]);
            end
        end

        // ============================================================
        // T2 — PARSE a Response UPIU header.
        //   byte0 = Transaction Type RESPONSE = 6'h21 -> 0x21
        //   byte1 = Flags 0xAA
        //   byte2 = LUN 0x05
        //   byte3 = Task Tag 0x07
        //   byte4 = {IID=0x1, CST=0x0} = 0x10
        //   byte5 = Query Func 0x00
        //   byte6 = Response 0x00 (TARGET SUCCESS)
        //   byte7 = Status 0x00 (GOOD)
        //   byte8 = EHS Len 0x00
        //   byte9 = Dev Info 0x01
        //   byte10 = DSL[15:8] 0x00
        //   byte11 = DSL[7:0]  0x18 (24-byte sense data)
        // ============================================================
        $display("== T2 PARSE Response UPIU ==");
        // ensure dut idle
        @(negedge clk);
        send_rx(8'h21);
        send_rx(8'hAA);
        send_rx(8'h05);
        send_rx(8'h07);
        send_rx(8'h10);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h01);
        send_rx(8'h00);
        send_rx(8'h18);

        // wait for parse_done
        wait (parse_done == 1'b1);
        @(negedge clk);
        check8("p_txn_type",     {2'b00, p_txn_type}, 8'h21);
        check8("p_flags",        p_flags,             8'hAA);
        check8("p_lun",          p_lun,               8'h05);
        check8("p_task_tag",     p_task_tag,          8'h07);
        check8("p_iid",          {4'h0, p_iid},       8'h01);
        check8("p_cmd_set_type", {4'h0, p_cmd_set_type}, 8'h00);
        check8("p_query_func",   p_query_func,        8'h00);
        check8("p_response",     p_response,          8'h00);
        check8("p_status",       p_status,            8'h00);
        check8("p_ehs_len",      p_ehs_len,           8'h00);
        check8("p_dev_info",     p_dev_info,          8'h01);
        check8("p_dsl_hi",       p_data_seg_len[15:8],8'h00);
        check8("p_dsl_lo",       p_data_seg_len[7:0], 8'h18);
        if (parse_valid !== 1'b1) begin
            errors = errors + 1;
            $display("  FAIL parse_valid : got %b exp 1 (RESPONSE is a valid txn type)", parse_valid);
        end else $display("  ok   parse_valid = 1");

        // ============================================================
        // T3 — PARSE an INVALID txn type (6'h0A reserved).
        // ============================================================
        $display("== T3 PARSE invalid txn type ==");
        @(negedge clk);
        send_rx(8'h0A); // invalid txn type
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        send_rx(8'h00);
        wait (parse_done == 1'b1);
        @(negedge clk);
        if (parse_valid !== 1'b0) begin
            errors = errors + 1;
            $display("  FAIL parse_valid : got %b exp 0 (0x0A is reserved)", parse_valid);
        end else $display("  ok   parse_valid = 0 (invalid txn rejected)");

        // ============================================================
        $display("====================================================");
        if (errors == 0)
            $display("RESULT: PASS  (all build + parse checks passed)");
        else
            $display("RESULT: FAIL  (%0d errors)", errors);
        $display("====================================================");
        $finish;
    end

    // stream one rx byte for exactly one clock with rx_valid high
    task send_rx(input [7:0] b);
        begin
            @(negedge clk);
            rx_byte  = b;
            rx_valid = 1'b1;
            @(negedge clk);
            rx_valid = 1'b0;
            rx_byte  = 8'h00;
        end
    endtask

    // timeout watchdog
    initial begin
        #100000;
        $display("RESULT: FAIL  (timeout)");
        $finish;
    end

endmodule

`default_nettype wire
