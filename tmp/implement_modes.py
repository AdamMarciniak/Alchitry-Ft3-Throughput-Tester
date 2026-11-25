from pathlib import Path
rtl=Path('usb3-tester.srcs/sources_1/new')
p=rtl/'tx_sequencer.v';s=p.read_text()
s=s.replace('    input  wire [7:0]  cfg_chirp_len', '''    input  wire [1:0]  cfg_method,     // 0 legacy, 1 Golay A/B, 2 TX i / RX i xor 1
    output wire [1:0]  shot_kind,      // captured at tx_sync
    input  wire [7:0]  cfg_chirp_len''')
s=s.replace('    wire [5:0]  elem_hw   = mux_code(elem_sel);','''    wire golay = cfg_method == 2'd1;
    wire neighbor = cfg_method == 2'd2;
    reg member_b = 0;
    reg switching_rx = 0;
    assign shot_kind = golay ? (member_b ? 2'd2 : 2'd1) :
                       neighbor ? 2'd3 : 2'd0;
    wire [5:0] switch_element = (neighbor && state == S_INHIBIT)
                              ? (element_current ^ 6'd1) : elem_sel;
    wire [5:0]  elem_hw   = mux_code(switch_element);''')
s=s.replace('br_match  && (elem_sel < N_ELEM)','br_match  && (switch_element < N_ELEM)')
s=s.replace("wire        chirp_en    = (cfg_chirp_len != 8'd0);","wire        chirp_en    = !golay && (cfg_chirp_len != 8'd0);")
s=s.replace('total_half  = chirp_en ?',"""total_half  = golay ? 9'd8 : chirp_en ?""")
s=s.replace('    // Host-writable waits','''    // Each chip is a full bipolar cycle. A = +++-, B = ++-+.
    wire invert_chip = golay && (half_idx[2:1] == (member_b ? 2'd2 : 2'd3));
    wire next_negative = half_idx[0] ^ invert_chip;

    // Host-writable waits''')
s=s.replace("        if (rst) begin\n            state", "        if (rst) begin\n            member_b <= 0;\n            switching_rx <= 0;\n            state")
s=s.replace('end else if (disarm) begin','end else if (disarm) begin\n            member_b <= 0;\n            switching_rx <= 0;')
s=s.replace("last_of_frame <= (list_len == 7'd1);","last_of_frame <= (list_len == 7'd1) && (!golay || member_b);")
s=s.replace('last_of_frame <= list_last;', 'last_of_frame <= list_last && (!golay || member_b);')
s=s.replace("                list_ptr <= list_last ?", "                if (!switching_rx && (!golay || member_b))\n                    list_ptr <= list_last ?")
s=s.replace('element_current <= elem_pend;','if (!switching_rx) element_current <= elem_pend;')
s=s.replace("            S_SETTLE: if (!gridded)","""            S_SETTLE: if (switching_rx) begin
                          if (tmr != 0) tmr <= tmr - 1'b1;
                          else begin
                              switching_rx <= 0;
                              state <= S_WAITRX;
                          end
                      end else if (!gridded)""")
a=s.index('            S_DEAD_A: if (btmr');b=s.index('            S_FIRE_N:',a)
s=s[:a]+s[b:]
s=s.replace('            S_DEAD_B: if (btmr','            S_DEAD_A, S_DEAD_B: if (btmr')
s=s.replace("ina_r    <= 1'b1;          // idle -> +HV, next cycle","ina_r    <= !next_negative;\n                          inb_r    <= !next_negative;")
i=s.index('            S_DEAD_A, S_DEAD_B:');s=s[:i]+s[i:].replace('state    <= S_FIRE_P;', 'state    <= next_negative ? S_FIRE_N : S_FIRE_P;',1)
# idle is {ina,inb}=01. Each driven interval 00 or 11, with the same idle gap even on repeated polarity.
s=s.replace("                if (last_of_frame) frame_count", "                if (golay) member_b <= !member_b;\n                if (last_of_frame) frame_count")
s=s.replace("if (last_of_frame && !continuous) run <= 1'b0;\n                state <= S_WAITRX;","""if (last_of_frame && !continuous) run <= 1'b0;
                if (neighbor) begin
                    switching_rx <= 1;
                    shift_data <= chain_word;
                    word_ok_pend <= word_ok;
                    shift_start <= 1;
                    state <= S_SHIFT;
                end else state <= S_WAITRX;""")
p.write_text(s)
p=rtl/'ctrl_decode.v';s=p.read_text().replace('    input  wire [5:0]  tx_elem,','    input  wire [1:0]  tx_kind,\n    output reg  [1:0]  pls_method,\n    input  wire [5:0]  tx_elem,').replace('            pls_arm       <=', '            pls_method    <= 0;\n            pls_arm       <=',1).replace('                OP_INFO_NONCE:','                8\'h20: if (!pls_arm && payload <= 2) pls_method <= payload[1:0];\n                OP_INFO_NONCE:').replace('    reg [5:0]  elem;', '    reg [1:0]  kind;\n    reg [5:0]  elem;').replace('                elem     <= tx_elem;', '                kind     <= tx_kind;\n                elem     <= tx_elem;').replace("{8'hE1, 2'b00, elem, frame_cnt}","{8'hE1, kind, elem, frame_cnt}").replace("13'd0, 1'b1, lease_enabled","10'd0, pls_method, 1'b1, 1'b1, lease_enabled")
p.write_text(s)
p=rtl/'alchitry_top.v';s=p.read_text().replace('    wire [5:0]  pulse_element;', '    wire [1:0]  pls_method, pulse_kind;\n    wire [5:0]  pulse_element;').replace('        .tx_elem ', '        .tx_kind(pulse_kind), .pls_method(pls_method),\n        .tx_elem ').replace('        .cfg_chirp_len ', '        .cfg_method(pls_method), .shot_kind(pulse_kind),\n        .cfg_chirp_len ');p.write_text(s)
p=Path('tests/rtl/tb_capture_ready.v');s=p.read_text().replace('    wire [5:0] elem;', '    wire [1:0] method, kind;\n    wire [5:0] elem;').replace('.tx_elem(elem)', '.tx_kind(kind),.pls_method(method),.tx_elem(elem)').replace('.cfg_chirp_len(','.cfg_method(method),.shot_kind(kind),.cfg_chirp_len(');p.write_text(s)
