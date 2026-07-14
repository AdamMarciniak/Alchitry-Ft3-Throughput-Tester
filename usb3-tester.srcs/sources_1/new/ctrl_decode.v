`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Module Name: ctrl_decode
// Description: Host->FPGA control word decoder + test pattern source +
//              pulse/receive sequencer.  Entirely in the clk_in domain
//              (RX FIFO read side).
//
//   SRC_SEQ emulates one probe scan cycle per element, 0-31 then wrapping:
//     1. "fire" the element (pretend: pulse_active/pulse_elem drive no pins
//        yet - reserved for the real pulser + mux hookup)
//     2. wait seq_dly clk cycles (transmit settling / future mux switch time)
//     3. capture seq_len ADC words while tgc_code ramps tgc_start -> max
//        across the window; dac7554_ramp follows tgc_code so the VCA gain
//        sweeps up over the receive window (TGC)
//     4. snap tgc_code back to tgc_start and wait seq_gap clk cycles so the
//        VCNTRL step can ring out before the next element fires
//   Each window goes out the fast path as one frame:
//     word 0          : {8'hE1, 3'b000, elem[4:0], frame_cnt[15:0]}
//     word 1..seq_len : packed ADC pairs (afe_stream format)
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

    // From ADC stream FIFO (FWFT, clk_in read side)
    input  wire [31:0] adc_word,
    input  wire        adc_empty,
    output wire        adc_rd_en,

    // DAC7554 ramp control (to dac7554_ramp)
    output reg  [23:0] dac_rate,        // clk cycles between ramp steps (0 = max)
    output reg         dac_run,         // 0 = freeze the ramp
    output wire        tgc_en,          // sequencer owns the DAC (TGC mode)
    output wire [11:0] tgc_code,        // TGC target code while tgc_en

    // Pretend pulser (drives no pins yet - future pulser/mux hookup)
    output wire        pulse_active,    // high while "firing"
    output wire [4:0]  pulse_elem,      // element being fired / received

    // AFE5804 register write (to afe5804_ctrl ext port)
    output reg  [23:0] afe_word,        // {addr[7:0], data[15:0]}
    output reg         afe_wr,          // 1-cycle pulse per write

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
                     OP_SET_LIMIT = 8'h06,
                     OP_SET_SRC   = 8'h07,   // payload[1:0]: 0 pattern, 1 ADC, 2 sequencer
                     OP_DAC_RATE  = 8'h08,   // payload: cycles between DAC steps
                     OP_DAC_RUN   = 8'h09,   // payload[0]: 1 = ramp, 0 = freeze
                     OP_AFE_REG   = 8'h0A,   // payload: {addr[7:0], data[15:0]}
                     OP_SEQ_LEN   = 8'h0B,   // payload[15:0]: ADC words per receive window
                     OP_SEQ_DLY   = 8'h0C,   // payload: pulse->receive delay, clk cycles
                     OP_SEQ_TGC   = 8'h0D,   // payload: TGC acc increment per captured word
                     OP_SEQ_GAP   = 8'h0E,   // payload: receive-end->pulse damp, clk cycles
                     OP_SEQ_TGC0  = 8'h0F;   // payload[11:0]: TGC start (min) DAC code

    localparam [1:0] PAT_COUNTER = 2'd0,
                     PAT_LFSR    = 2'd1,
                     PAT_CONST   = 2'd2;

    localparam [1:0] SRC_PATTERN = 2'd0,
                     SRC_ADC     = 2'd1,
                     SRC_SEQ     = 2'd2;

    // FWFT: one word per cycle whenever present
    assign ctrl_rd_en = !ctrl_empty;

    wire [7:0]  opcode  = ctrl_word[31:24];
    wire [23:0] payload = ctrl_word[23:0];

    reg [1:0]  pattern;
    reg [1:0]  src;
    reg [23:0] const_val;
    reg [31:0] word_limit;
    reg [31:0] words_sent;
    reg        rst_cnt_pulse;
    reg [15:0] seq_len;
    reg [23:0] seq_dly;
    reg [23:0] seq_gap;
    reg [23:0] tgc_inc;
    reg [11:0] tgc_start;

    //--------------------------------------------------------------------------
    // Command execution
    //--------------------------------------------------------------------------
    always @(posedge clk) begin
        rst_cnt_pulse <= 1'b0;
        afe_wr        <= 1'b0;

        if (rst) begin
            streaming  <= 1'b0;
            pattern    <= PAT_COUNTER;
            src        <= SRC_PATTERN;    // default: pattern (old tester behaviour)
            const_val  <= 24'hDEAD00;
            word_limit <= 32'h0;          // 0 = unlimited
            dac_rate   <= 24'd0;          // default: ramp at max SPI rate
            dac_run    <= 1'b1;           // ramp free-runs from power-up
            seq_len    <= 16'd2047;       // 4094 samples = 102.35 us window
            seq_dly    <= 24'd500;        // 5 us pulse->receive settling
            seq_gap    <= 24'd5000;       // 50 us DAC ring-out before next pulse
            tgc_inc    <= 24'd8196;       // full 0->4095 sweep over 2047 words
            tgc_start  <= 12'd0;          // ramp starts at DAC code 0
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
                OP_SET_SRC:   src        <= payload[1:0];
                OP_DAC_RATE:  dac_rate   <= payload;
                OP_DAC_RUN:   dac_run    <= payload[0];
                OP_AFE_REG: begin
                    afe_word <= payload;
                    afe_wr   <= 1'b1;
                end
                OP_SEQ_LEN:   seq_len    <= payload[15:0];
                OP_SEQ_DLY:   seq_dly    <= payload;
                OP_SEQ_TGC:   tgc_inc    <= payload;
                OP_SEQ_GAP:   seq_gap    <= payload;
                OP_SEQ_TGC0:  tgc_start  <= payload[11:0];
                default:      ;           // NOP, lock word, anything unknown
            endcase
        end
    end

    //--------------------------------------------------------------------------
    // Pulse/receive sequencer (SRC_SEQ)
    //--------------------------------------------------------------------------
    localparam [2:0] S_DAMP  = 3'd0,            // DAC back at min, ring settling
                     S_PULSE = 3'd1,
                     S_DLY   = 3'd2,
                     S_HDR   = 3'd3,
                     S_RX    = 3'd4;
    localparam [5:0] PULSE_CYCLES = 6'd32;      // 320 ns pretend excitation

    reg [2:0]  sstate;
    reg [4:0]  elem;
    reg [15:0] frame_cnt;
    reg [5:0]  pulse_cnt;
    reg [23:0] dly_cnt;
    reg [15:0] rx_cnt;
    reg [23:0] tgc_acc;

    wire seq_run = streaming && (src == SRC_SEQ);
    wire tx_ok   = !tx_full && !tx_wr_rst_busy;

    wire hdr_write = seq_run && (sstate == S_HDR) && tx_ok;
    wire rx_write  = seq_run && (sstate == S_RX)  && tx_ok && !adc_empty;

    assign pulse_active = seq_run && (sstate == S_PULSE);
    assign pulse_elem   = elem;
    assign tgc_en       = seq_run;
    assign tgc_code     = tgc_acc[23:12];

    wire [24:0] tgc_sum = {1'b0, tgc_acc} + {1'b0, tgc_inc};

    always @(posedge clk) begin
        if (rst || !seq_run) begin              // START always begins at elem 0
            sstate    <= S_DAMP;
            dly_cnt   <= 24'd0;
            elem      <= 5'd0;
            frame_cnt <= 16'd0;
            pulse_cnt <= PULSE_CYCLES;
            tgc_acc   <= {tgc_start, 12'd0};
        end else case (sstate)
            S_DAMP: begin                       // let the DAC min-step ring out
                dly_cnt <= dly_cnt - 1'b1;
                if (dly_cnt == 24'd0) begin
                    pulse_cnt <= PULSE_CYCLES;
                    sstate    <= S_PULSE;
                end
            end
            S_PULSE: begin                      // pretend to fire the element
                pulse_cnt <= pulse_cnt - 1'b1;
                if (pulse_cnt == 6'd0) begin
                    dly_cnt <= seq_dly;
                    sstate  <= S_DLY;
                end
            end
            S_DLY: begin                        // settling / future mux switch
                dly_cnt <= dly_cnt - 1'b1;
                if (dly_cnt == 24'd0) sstate <= S_HDR;
            end
            S_HDR: if (hdr_write) begin         // frame header accepted by FIFO
                rx_cnt <= (seq_len == 16'd0) ? 16'd1 : seq_len;
                sstate <= S_RX;
            end
            S_RX: if (rx_write) begin           // one ADC word captured
                rx_cnt <= rx_cnt - 1'b1;
                if (rx_cnt == 16'd1) begin
                    elem      <= elem + 1'b1;   // 31 wraps to 0
                    frame_cnt <= frame_cnt + 1'b1;
                    tgc_acc   <= {tgc_start, 12'd0};  // gain back to minimum
                    dly_cnt   <= seq_gap;
                    sstate    <= S_DAMP;
                end else begin
                    tgc_acc <= tgc_sum[24] ? 24'hFFFFFF : tgc_sum[23:0];
                end
            end
            default: sstate <= S_DAMP;          // unreachable encodings
        endcase
    end

    //--------------------------------------------------------------------------
    // Pattern source + TX FIFO write arbitration
    //--------------------------------------------------------------------------
    reg [31:0] counter;
    reg [31:0] lfsr;

    wire limit_hit = (word_limit != 32'h0) && (words_sent >= word_limit);
    wire tx_ready  = streaming && !limit_hit && tx_ok;

    wire pat_write = tx_ready && (src == SRC_PATTERN);
    wire adc_write = tx_ready && (src == SRC_ADC) && !adc_empty;

    // Sequencer frames bypass word_limit: a frame must never be cut short.
    assign tx_wr_en = pat_write || adc_write || hdr_write || rx_write;

    // Consume the ADC FIFO when a mode is capturing it; otherwise drain and
    // discard so a stream (or a receive window) always starts with fresh
    // samples, never a stale backlog.
    wire adc_keep = (streaming && (src == SRC_ADC)) ||
                    (seq_run && (sstate == S_RX));
    assign adc_rd_en = adc_write || rx_write || (!adc_keep && !adc_empty);

    always @(posedge clk) begin
        if (rst || rst_cnt_pulse) begin
            counter    <= 32'h0;
            lfsr       <= 32'hACE1_2345;   // any non-zero seed
            words_sent <= 32'h0;
        end else begin
            if (pat_write) begin
                counter <= counter + 1'b1;
                // maximal-length 32-bit XNOR LFSR, taps 32,22,2,1
                lfsr    <= {lfsr[30:0], ~(lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0])};
            end
            if (tx_wr_en) words_sent <= words_sent + 1'b1;
        end
    end

    always @* begin
        case (src)
            SRC_SEQ: tx_din = (sstate == S_HDR)
                            ? {8'hE1, 3'b000, elem, frame_cnt}
                            : adc_word;
            SRC_ADC: tx_din = adc_word;
            default: case (pattern)
                PAT_LFSR:  tx_din = lfsr;
                PAT_CONST: tx_din = {8'hC0, const_val};
                default:   tx_din = counter;   // PAT_COUNTER
            endcase
        endcase
    end

endmodule
