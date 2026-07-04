module load_store_unit (
    input  logic                 clk,
    input  logic                 rst_n,

    // EX stage interface
    input  logic                 ex_if_req_i,           // LSU request
    input  logic                 ex_if_we_i,            // Write enable: 0 (load), 1 (store)
    input  logic     [ 1:0]      ex_if_type_i,          // Data type: 0x2 (word), 0x1 (halfword), 0x0 (byte)
    input  logic     [31:0]      ex_if_wdata_i,         // Data to write to memory
    input  logic     [31:0]      ex_if_addr_base_i,     // Base address
    input  logic     [31:0]      ex_if_addr_offset_i,   // Offset address
    input  logic                 ex_if_extend_mode_i,
    output logic                 ex_if_ready_o    ,

    // Writeback stage interface
    output logic     [31:0]      wb_if_rdata_o,         // Requested data
    output logic                 wb_if_rvalid_o,        // Requested data valid

    // Data memory (DMEM) interface
    output logic                 dmem_req_o,
    input  logic                 dmem_gnt_i,
    output logic     [31:0]      dmem_req_addr_o,
    output logic                 dmem_req_we_o,
    output logic     [ 3:0]      dmem_req_be_o,
    output logic     [31:0]      dmem_req_wdata_o,
    input  logic     [31:0]      dmem_rsp_rdata_i,
    input  logic                 dmem_rvalid_i
    );

  // ----------------------------------------
  // - FSM definition
  // ----------------------------------------
  localparam [3:0] IDLE                = 4'd0;
  localparam [3:0] ALIGNED_WR          = 4'd1;
  localparam [3:0] ALIGNED_RD          = 4'd2;
  localparam [3:0] ALIGNED_RD_GNT      = 4'd3;
  localparam [3:0] MISALIGNED_WR       = 4'd4;
  localparam [3:0] MISALIGNED_WR_1     = 4'd5;
  localparam [3:0] MISALIGNED_RD       = 4'd6;
  localparam [3:0] MISALIGNED_RD_GNT   = 4'd7;
  localparam [3:0] MISALIGNED_RD_1     = 4'd8;
  localparam [3:0] MISALIGNED_RD_GNT_1 = 4'd9;

  logic [3:0] state_q, state_d;

  logic [31:0] data_addr_int;
  assign data_addr_int = ex_if_addr_base_i + ex_if_addr_offset_i;

  // ----------------------------------------
  // - Misalignment detection
  // ----------------------------------------
  logic misaligned;
  always_comb begin
    case (ex_if_type_i)
      2'b10:   misaligned = (data_addr_int[1:0] != 2'b00);  // word
      2'b01:   misaligned = (data_addr_int[1:0] == 2'b11);  // halfword crossing word boundary
      default: misaligned = 1'b0;                           // byte never misaligned
    endcase
  end

  // ----------------------------------------
  // - Byte-enable helpers
  // ----------------------------------------
  function automatic logic [3:0] be_first(input logic [1:0] off, input logic [1:0] t);
    case (t)
      2'b00: be_first = (4'b0001 << off);                   // byte
      2'b01: case (off)                                     // halfword low part
               2'b00:   be_first = 4'b0011;
               2'b01:   be_first = 4'b0110;
               2'b10:   be_first = 4'b1100;
               default: be_first = 4'b1000;                 // off==2'b11 -> high byte of this word
             endcase
      2'b10: be_first = (4'b1111 << off);                   // word low part
      default: be_first = 4'b0000;
    endcase
  endfunction

  function automatic logic [3:0] be_second(input logic [1:0] off, input logic [1:0] t);
    case (t)
      2'b01:   be_second = 4'b0001;                         // halfword high byte in next word
      2'b10:   be_second = (4'b1111 >> (3'd4 - off));       // word high part
      default: be_second = 4'b0000;
    endcase
  endfunction

  // ----------------------------------------
  // - Registered request context
  // ----------------------------------------
  logic [31:0] req_addr_word_q;
  logic [ 1:0] req_type_q, req_off_q;
  logic [31:0] req_wdata_q;
  logic        req_sext_q;
  logic [ 3:0] be1_q, be2_q;
  logic        req_aligned_q;

  // Natural alignment of the access (byte always; halfword on a 2-byte
  // boundary; word on a 4-byte boundary). A single-transaction access that is
  // NOT naturally aligned (e.g. a halfword at offset 1) must forward the raw
  // byte-masked memory word to writeback, exactly like a multi-transaction
  // misaligned access -- not the sign/zero-extended (shifted) datum.
  logic naturally_aligned;
  always_comb begin
    case (ex_if_type_i)
      2'b00:   naturally_aligned = 1'b1;                       // byte
      2'b01:   naturally_aligned = (data_addr_int[0] == 1'b0); // halfword
      2'b10:   naturally_aligned = (data_addr_int[1:0] == 2'b00); // word
      default: naturally_aligned = 1'b1;
    endcase
  end

  logic accept;
  assign accept        = ex_if_req_i && (state_q == IDLE);
  assign ex_if_ready_o = (state_q == IDLE);

  always_ff @(posedge clk, negedge rst_n) begin
    if (!rst_n) begin
      req_addr_word_q <= '0;
      req_type_q      <= '0;
      req_off_q       <= '0;
      req_wdata_q     <= '0;
      req_sext_q      <= 1'b0;
      be1_q           <= '0;
      be2_q           <= '0;
      req_aligned_q   <= 1'b0;
    end else if (accept) begin
      req_addr_word_q <= {data_addr_int[31:2], 2'b00};
      req_type_q      <= ex_if_type_i;
      req_off_q       <= data_addr_int[1:0];
      req_wdata_q     <= ex_if_wdata_i;
      req_sext_q      <= ex_if_extend_mode_i;
      be1_q           <= be_first(data_addr_int[1:0], ex_if_type_i);
      be2_q           <= be_second(data_addr_int[1:0], ex_if_type_i);
      req_aligned_q   <= naturally_aligned;
    end
  end

  // ----------------------------------------
  // - Next-state logic
  // ----------------------------------------
  always_comb begin
    state_d = state_q;
    case (state_q)
      IDLE: begin
        if (ex_if_req_i) begin
          if (ex_if_we_i) state_d = misaligned ? MISALIGNED_WR : ALIGNED_WR;
          else            state_d = misaligned ? MISALIGNED_RD : ALIGNED_RD;
        end
      end
      ALIGNED_WR:          if (dmem_gnt_i)    state_d = IDLE;
      ALIGNED_RD:          if (dmem_gnt_i)    state_d = ALIGNED_RD_GNT;
      ALIGNED_RD_GNT:      if (dmem_rvalid_i) state_d = IDLE;
      MISALIGNED_WR:       if (dmem_gnt_i)    state_d = MISALIGNED_WR_1;
      MISALIGNED_WR_1:     if (dmem_gnt_i)    state_d = IDLE;
      MISALIGNED_RD:       if (dmem_gnt_i)    state_d = MISALIGNED_RD_GNT;
      MISALIGNED_RD_GNT:   if (dmem_rvalid_i) state_d = MISALIGNED_RD_1;
      MISALIGNED_RD_1:     if (dmem_gnt_i)    state_d = MISALIGNED_RD_GNT_1;
      MISALIGNED_RD_GNT_1: if (dmem_rvalid_i) state_d = IDLE;
      default:                                state_d = IDLE;
    endcase
  end

  always_ff @(posedge clk, negedge rst_n) begin
    if (!rst_n) state_q <= IDLE;
    else        state_q <= state_d;
  end

  // ----------------------------------------
  // - DMEM bus drive (all signals zeroed when dmem_req_o is deasserted)
  // ----------------------------------------
  always_comb begin
    dmem_req_o       = 1'b0;
    dmem_req_addr_o  = 32'b0;
    dmem_req_we_o    = 1'b0;
    dmem_req_be_o    = 4'b0;
    dmem_req_wdata_o = 32'b0;
    case (state_q)
      ALIGNED_WR: begin
        dmem_req_o       = 1'b1;
        dmem_req_we_o    = 1'b1;
        dmem_req_addr_o  = req_addr_word_q;
        dmem_req_be_o    = be1_q;
        dmem_req_wdata_o = req_wdata_q;
      end
      ALIGNED_RD: begin
        dmem_req_o       = 1'b1;
        dmem_req_addr_o  = req_addr_word_q;
        dmem_req_be_o    = be1_q;
      end
      MISALIGNED_WR: begin
        dmem_req_o       = 1'b1;
        dmem_req_we_o    = 1'b1;
        dmem_req_addr_o  = req_addr_word_q;
        dmem_req_be_o    = be1_q;
        dmem_req_wdata_o = req_wdata_q;
      end
      MISALIGNED_WR_1: begin
        dmem_req_o       = 1'b1;
        dmem_req_we_o    = 1'b1;
        dmem_req_addr_o  = req_addr_word_q + 32'd4;
        dmem_req_be_o    = be2_q;
        dmem_req_wdata_o = req_wdata_q;
      end
      MISALIGNED_RD: begin
        dmem_req_o       = 1'b1;
        dmem_req_addr_o  = req_addr_word_q;
        dmem_req_be_o    = be1_q;
      end
      MISALIGNED_RD_1: begin
        dmem_req_o       = 1'b1;
        dmem_req_addr_o  = req_addr_word_q + 32'd4;
        dmem_req_be_o    = be2_q;
      end
      default: ; // all bus signals held at zero
    endcase
  end

  // ----------------------------------------
  // - Aligned-read data extension
  // ----------------------------------------
  logic [31:0] rdata_ext;
  always_comb begin
    case (req_type_q)
      2'b00: begin // byte
        case (req_off_q)
          2'b00:   rdata_ext = req_sext_q ? {{24{dmem_rsp_rdata_i[ 7]}}, dmem_rsp_rdata_i[ 7:0 ]} : {24'b0, dmem_rsp_rdata_i[ 7:0 ]};
          2'b01:   rdata_ext = req_sext_q ? {{24{dmem_rsp_rdata_i[15]}}, dmem_rsp_rdata_i[15:8 ]} : {24'b0, dmem_rsp_rdata_i[15:8 ]};
          2'b10:   rdata_ext = req_sext_q ? {{24{dmem_rsp_rdata_i[23]}}, dmem_rsp_rdata_i[23:16]} : {24'b0, dmem_rsp_rdata_i[23:16]};
          default: rdata_ext = req_sext_q ? {{24{dmem_rsp_rdata_i[31]}}, dmem_rsp_rdata_i[31:24]} : {24'b0, dmem_rsp_rdata_i[31:24]};
        endcase
      end
      2'b01: begin // halfword
        case (req_off_q)
          2'b10:   rdata_ext = req_sext_q ? {{16{dmem_rsp_rdata_i[31]}}, dmem_rsp_rdata_i[31:16]} : {16'b0, dmem_rsp_rdata_i[31:16]};
          default: rdata_ext = req_sext_q ? {{16{dmem_rsp_rdata_i[15]}}, dmem_rsp_rdata_i[15:0 ]} : {16'b0, dmem_rsp_rdata_i[15:0 ]};
        endcase
      end
      default: rdata_ext = dmem_rsp_rdata_i; // word
    endcase
  end

  // ----------------------------------------
  // - Writeback
  //   Aligned loads: sign/zero-extended. Misaligned loads: raw response data
  //   forwarded per transaction.
  // ----------------------------------------
  always_ff @(posedge clk, negedge rst_n) begin
    if (!rst_n) begin
      wb_if_rdata_o  <= 32'b0;
      wb_if_rvalid_o <= 1'b0;
    end else if (dmem_rvalid_i &&
                 (state_q == ALIGNED_RD_GNT ||
                  state_q == MISALIGNED_RD_GNT ||
                  state_q == MISALIGNED_RD_GNT_1)) begin
      // Aligned single-transaction reads are sign/zero-extended; everything
      // else (multi-transaction misaligned AND a naturally-unaligned single
      // transaction such as a halfword at offset 1) forwards the raw masked
      // response word per transaction.
      wb_if_rdata_o  <= (state_q == ALIGNED_RD_GNT && req_aligned_q) ? rdata_ext
                                                                     : dmem_rsp_rdata_i;
      wb_if_rvalid_o <= 1'b1;
    end else begin
      wb_if_rvalid_o <= 1'b0;
    end
  end

endmodule
