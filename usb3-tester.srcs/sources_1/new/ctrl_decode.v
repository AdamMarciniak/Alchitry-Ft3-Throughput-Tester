`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: ctrl_decode
// Description: Host->FPGA control word decoder + test pattern source.
//              Entirely in the clk_in domain (RX FIFO read side).
//////////////////////////////////////////////////////////////////////////////////

module ctrl_decode (
    input  wire        clk,             // clk_in (100 MHz onboard)
    input  wire        rst,             // rst_sys

    // From RX control FIFO (FWFT)
    input  wire [31:0] ctrl_word,
    input  wire        ctrl_empty,
    output wire        ctrl_rd_en,

    // To TX FIFO write port
    output reg  [31:0] tx_din,
    output wire        tx_wr_en,
    input  wire        tx_full,
    input  wire        tx_wr_rst_busy,

    // Status
    output reg         streaming,
    output reg  [7:0]  cmd_count       // increments per accepted command
);

    localparam [7:0] OP_NOP       = 8'h00,
                     OP_START     = 8'h01,
                     OP_STOP      = 8'h02,
                     OP_RST_CNT   = 8'h03,
                     OP_SET_PAT   = 8'h04,
                     OP_SET_CONST = 8'h05,
                     OP_SET_LIMIT = 8'h06;

    localparam [1:0] PAT_COUNTER = 2'd0,
                     PAT_LFSR    = 2'd1,
                     PAT_CONST   = 2'd2;

    // FWFT: one word per cycle whenever present
    assign ctrl_rd_en = !ctrl_empty;

    wire [7:0]  opcode  = ctrl_word[31:24];
    wire [23:0] payload = ctrl_word[23:0];

    reg [1:0]  pattern;
    reg [23:0] const_val;
    reg [31:0] word_limit;
    reg [31:0] words_sent;
    reg        rst_cnt_pulse;

    //--------------------------------------------------------------------------
    // Command execution
    //--------------------------------------------------------------------------
    always @(posedge clk) begin
        rst_cnt_pulse <= 1'b0;

        if (rst) begin
            streaming  <= 1'b0;
            pattern    <= PAT_COUNTER;
            const_val  <= 24'hDEAD00;
            word_limit <= 32'h0;          // 0 = unlimited
            cmd_count  <= 8'h0;
        end else if (ctrl_rd_en) begin
            cmd_count <= cmd_count + 1'b1;

            case (opcode)
                OP_START:     streaming <= 1'b1;
                OP_STOP:      streaming <= 1'b0;
                OP_RST_CNT: begin
                    streaming     <= 1'b0;
                    rst_cnt_pulse <= 1'b1;
                end
                OP_SET_PAT:   pattern    <= payload[1:0];
                OP_SET_CONST: const_val  <= payload;
                OP_SET_LIMIT: word_limit <= {payload, 8'h0};
                default:      ;           // NOP, lock word, anything unknown
            endcase
        end
    end

    //--------------------------------------------------------------------------
    // Pattern source
    //--------------------------------------------------------------------------
    reg [31:0] counter;
    reg [31:0] lfsr;

    wire limit_hit = (word_limit != 32'h0) && (words_sent >= word_limit);
    wire can_write = streaming && !limit_hit && !tx_full && !tx_wr_rst_busy;

    assign tx_wr_en = can_write;

    always @(posedge clk) begin
        if (rst || rst_cnt_pulse) begin
            counter    <= 32'h0;
            lfsr       <= 32'hACE1_2345;   // any non-zero seed
            words_sent <= 32'h0;
        end else if (can_write) begin
            counter    <= counter + 1'b1;
            // maximal-length 32-bit XNOR LFSR, taps 32,22,2,1
            lfsr       <= {lfsr[30:0], ~(lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0])};
            words_sent <= words_sent + 1'b1;
        end
    end

    always @* begin
        case (pattern)
            PAT_LFSR:  tx_din = lfsr;
            PAT_CONST: tx_din = {8'hC0, const_val};
            default:   tx_din = counter;   // PAT_COUNTER
        endcase
    end

endmodule