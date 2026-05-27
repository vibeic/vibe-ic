module TopModule (
  input clk,
  input reset,
  input [3:1] s,
  output reg fr3,
  output reg fr2,
  output reg fr1,
  output reg dfr
);
    // States: level + (for middle levels) direction of last change.
    localparam A = 3'd0,  // above s3 (level 3): all off
               B = 3'd1,  // between s3,s2 (level 2), came from above (dfr=0)
               C = 3'd2,  // between s3,s2 (level 2), came from below (dfr=1)
               D = 3'd3,  // between s2,s1 (level 1), came from above (dfr=0)
               E = 3'd4,  // between s2,s1 (level 1), came from below (dfr=1)
               F = 3'd5;  // below s1 (level 0): all on, dfr=1

    reg [2:0] state, next;

    // decode sensor reading -> new water level (0=lowest .. 3=highest)
    reg [1:0] nlvl;
    always @(*) begin
        case (s)
            3'b000:  nlvl = 2'd0;
            3'b001:  nlvl = 2'd1;
            3'b011:  nlvl = 2'd2;
            3'b111:  nlvl = 2'd3;
            default: nlvl = 2'd0;
        endcase
    end

    // current state's level
    reg [1:0] clvl;
    always @(*) begin
        case (state)
            A:       clvl = 2'd3;
            B, C:    clvl = 2'd2;
            D, E:    clvl = 2'd1;
            default: clvl = 2'd0; // F
        endcase
    end

    always @(*) begin
        case (nlvl)
            2'd3: next = A;
            2'd0: next = F;
            2'd2: begin // level 2 (B/C)
                if (nlvl > clvl)      next = C; // rose -> dfr=1
                else if (nlvl < clvl) next = B; // fell -> dfr=0
                else                  next = state; // stay
            end
            2'd1: begin // level 1 (D/E)
                if (nlvl > clvl)      next = E; // rose
                else if (nlvl < clvl) next = D; // fell
                else                  next = state;
            end
            default: next = F;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= F;
        else       state <= next;
    end

    always @(*) begin
        case (state)
            A: begin fr1=0; fr2=0; fr3=0; dfr=0; end
            B: begin fr1=1; fr2=0; fr3=0; dfr=0; end
            C: begin fr1=1; fr2=0; fr3=0; dfr=1; end
            D: begin fr1=1; fr2=1; fr3=0; dfr=0; end
            E: begin fr1=1; fr2=1; fr3=0; dfr=1; end
            F: begin fr1=1; fr2=1; fr3=1; dfr=1; end
            default: begin fr1=1; fr2=1; fr3=1; dfr=1; end
        endcase
    end
endmodule
