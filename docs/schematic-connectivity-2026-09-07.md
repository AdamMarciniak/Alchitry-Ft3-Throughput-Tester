# Pulser and AFE connectivity reference with confirmed solder bridges

Date: 2026-09-07. Format: UTF-8 Markdown. Coverage: 227 placed components and 1,179 symbol terminals across two EasyEDA Pro schematics, plus the owner-confirmed physical bridges on all three leaf muxes.

## 1. Scope and interpretation

This document combines the supplied schematic projects, BOMs, and the owner’s physical-build clarification into a component-to-net map and a net-to-component map. The primary pin tables and net records incorporate the confirmed solder bridges. Each changed pin also retains its saved-schematic net ID, and each net record retains its constituent saved net IDs. Every placed component and every pin in its selected library symbol is included, even when absent from ordinary package pin counts or left unconnected.

**Verification limit:** this is a reconstruction from the saved project records, not an EasyEDA-generated netlist. A 0.25 schematic-coordinate-unit tolerance is used for pin/port-to-wire matching because the files contain small coordinate offsets. Every tolerance-dependent contact is identified in Section 8. Four additional near contacts at 0.31496063 units are left unresolved in Section 2. The document preserves these limits so an LLM cannot mistake inferred contact for native-netlist confirmation.

- Component IDs use `BOARD.REF`, for example `PULSER.U1` and `AFE.U1`; they are different devices. Pin endpoints use `BOARD.REF.PIN`, with BGA pin numbers preserved as strings such as `AFE.U1.A1`.
- Net IDs use `BOARD:LABEL`. Exact spelling, spaces, signs, and case are preserved. Labels on different boards do not establish a cable connection. Within one board, identical net-port/global-net names are merged.
- Unnamed nets receive a deterministic document ID `BOARD:N_REF_PIN`, based on a naturally sorted endpoint. These IDs are generated for this document, not source labels.
- Pins on the same net are directly electrically connected by reconstructed wiring or an owner-confirmed solder bridge. Components do not otherwise merge nets. No internal IC switching state, diode conduction state, unconfirmed solder bridge, or component population is assumed. Leaf-bank inputs are common within each mux; the three banks retain separate root-switch outputs.
- `CONNECTED` means a net has two or more component terminals. `SINGLE_PIN_NET` means a wire or label exists but only one component terminal was found. `UNCONNECTED` means no wire/port/other pin contact was found under the stated reconstruction rule. It does not by itself mean intentional no-connect.
- A pin named `NC`, `DNC`, or `COM` is recorded literally. Names do not override wiring. In particular, the literal net name `3.3V NC` is a connected pulser supply net, despite containing the letters NC.
- `EXACT` means a contact within 0.0001 coordinate units. `NEAR` means a larger contact offset within 0.25 units. These are geometric evidence classes, not electrical safety or design-quality ratings. Net records identify near pins and near label IDs so dependence on a displaced label remains visible.
- BOM metadata comes from the supplied spreadsheet row; symbol pin names and numbers come from the embedded symbol library. Source notes and placeholder wording are quoted as design data and are not instructions to alter the circuit.

### Source files and coverage

| Board | Project / schematic / sheet | Components | Symbol terminals | Connected nets¹ | Single-pin nets | Unconnected terminals |
| --- | --- | --- | --- | --- | --- | --- |
| PULSER | `pulser-schematic.epro2` / `Schematic1` / `P1` | 116 | 565 | 97 | 14 | 3 |
| AFE | `afe-schematic.epro2` / `Schematic2` / `P1` | 111 | 614 | 72 | 1 | 155 |

¹ Connected nets contain at least two symbol terminals. AFE also contains one wire group with no component terminals or net labels; it is listed separately. Both BOM reference sets exactly match their corresponding schematic reference sets. All 55 populated BOM rows have quantities equal to their listed designator counts.

- `pulser-schematic.epro2`: SHA-256 `455152a7a7848380f5db947caad06ec100e2a7552e6b973bbefc25dc8fb33c20`.
- `BOM_Pulser_Schematic1_2026-09-07.xlsx`: SHA-256 `d0de143cd8b783b805b36755ef8f377fae85d8b4344fda7c3cdd4e641d6c5d3e`.
- `afe-schematic.epro2`: SHA-256 `556ae267556fb4c0a673c0dc0036efffbd1b6385dbefbb1eda35e188c89ae264`.
- `BOM_ADC_Schematic2_2026-09-07.xlsx`: SHA-256 `9721ce7b86a858100f82fbb2cfccab111c5af3caedd6fa4139fa576f9f9494d0`.

## 2. Exceptions that must remain visible

### 2.0 Owner-confirmed physical solder bridges

Owner clarification received 2026-09-07: “the solder gaps for the three leaf muxes have all been physically bridged by me” and “all three tree muxes have all their inputs connected together.” This is treated as authoritative physical-build data for the leaf-mux COM/input gaps. Matching those gaps to the supplied schematic identifies 48 Blob-Standin positions: R17 through R64.

| Leaf mux | Physically bridged gap designators | Common input net | Root switch endpoint |
| --- | --- | --- | --- |
| `PULSER.U3` | `R17–R32` (each gap closed) | `PULSER:NO11` | `PULSER.U5.25` |
| `PULSER.U7` | `R33–R48` (each gap closed) | `PULSER:NO5` | `PULSER.U5.14` |
| `PULSER.U1` | `R49–R64` (each gap closed) | `PULSER:NO7` | `PULSER.U5.18` |

For each leaf mux, COM0 through COM15 (pins 1, 3, 5, 7, 11, 13, 15, 17, 20, 22, 24, 26, 30, 32, 34, and 36) are now one common input node. Each of the 48 listed gap symbols has pin 1 physically shorted to pin 2. The three common nodes are NO11 for U3, NO5 for U7, and NO7 for U1. Their normally-open/output pins remain distinct switched channels. No permanent short between these three common nodes is added.

The root mux U5’s 13 remaining Blob-Standin positions (R2–R8, R10, R12–R16) are not covered by the leaf-gap confirmation. Their original separate-net treatment remains. The primary as-built graph has 48 fewer nets than the saved-schematic reconstruction. No source schematic or BOM was edited.

### 2.1 Four unresolved pulser contacts near ground

In the saved-schematic reconstruction before physical overrides, ground wire group `0aca1b973681fa10` passes 0.31496063 coordinate units from the following resistor pins. These pins already have a direct wire to a switch COM pin. At tolerance 0.25 they remain separate from ground; at 0.5 all four nets merge into ground. Both interpretations must remain possible until checked with an EasyEDA netlist export. No other saved-schematic component-net membership changes when increasing the matching tolerance from 0.25 to 0.5.

| Saved schematic net | Endpoints before physical bridges | Additional possible connection |
| --- | --- | --- |
| `PULSER:N_R18_2` | `PULSER.R18.2`, `PULSER.U3.30` | PULSER:GND (unresolved) |
| `PULSER:N_R19_2` | `PULSER.R19.2`, `PULSER.U3.32` | PULSER:GND (unresolved) |
| `PULSER:N_R20_2` | `PULSER.R20.2`, `PULSER.U3.34` | PULSER:GND (unresolved) |
| `PULSER:N_R21_2` | `PULSER.R21.2`, `PULSER.U3.36` | PULSER:GND (unresolved) |

The separate net IDs in this table identify the saved schematic before physical bridges. In the primary as-built graph, all four belong to `PULSER:NO11` because their gaps are closed. Therefore, if any of these near-ground contacts is recognized as connected by EasyEDA or exists physically, the entire U3 common-input bank is on ground. The owner’s bridge confirmation does not itself establish or rule out that ground connection. Section 8 retains the smaller offsets accepted by the reconstruction.

### 2.2 Population, placeholders, and pin-count discrepancies

- `PULSER.U1` and `PULSER.U7` are included in BOM row 19, but their schematic instance property `Add into BOM` is `no`. Their connectivity remains included; installed population is unresolved.
- 61 pulser resistor designators have value/comment `Blob-Standin`, with no manufacturer or supplier part specified. The 48 leaf positions R17–R64 are physically bridged per owner confirmation. The other 13 positions retain their original separate-net treatment.
- `PULSER.C25` has value/comment `PLACEHOLDER FOR RESISTOR LATER`, while the BOM still lists capacitor part `CL10B104KA8WPNC` and footprint `C0603`. Its intended eventual type/value is unresolved. The two-terminal connection is preserved.
- `PULSER.U9` is called `48 Pin Connector`, but the symbol contains pins `1` through `102` and the BOM footprint is `100P-JMDSS-G-1-TF`. All 102 terminals are included. The intended connector model/contact count cannot be settled from the name alone.
- `AFE.U5` and `AFE.U6` have 82 symbol terminals each although their part name specifies an 80-position connector. The additional symbol terminals are retained exactly. `AFE.U7` has seven symbol terminals and BOM comment `DSC1123 40Mhz OSC`, with no manufacturer part number supplied.
- `PULSER.SET` and `PULSER.GND` are aliases of the same wired net. The canonical document ID is `PULSER:GND`. The four MAX14866 SET pins are therefore on ground in this reconstruction.
- `PULSER.CN1.2` carries the literal label `1.8V NC` but has no second component endpoint. `AFE:41` reaches only `AFE.U6.41`; `AFE.CN1.15` remains unconnected. Do not invent a missing wire between them.

### 2.3 Separate projects do not define an inter-board cable

There is no authoritative inter-board cable map in the supplied files. In particular, identically numbered CN1 connectors are not assumed to mate pin-for-pin. The following is a **candidate reversal hypothesis only**: `PULSER.CN1.n` could pair with `AFE.CN1.(21-n)`. It aligns the 5 V, 3.3 V, 1.8 V, and ground positions by label. It is not included in either board netlist and is not a wiring instruction.

| Pulser pin | Pulser net | Candidate AFE pin | AFE net |
| --- | --- | --- | --- |
| `PULSER.CN1.1` | `PULSER:+5V` | `AFE.CN1.20` | `AFE:+5_VDD` |
| `PULSER.CN1.2` | `PULSER:1.8V NC` | `AFE.CN1.19` | `AFE:+1.8_LVDD` |
| `PULSER.CN1.3` | `PULSER:GND` | `AFE.CN1.18` | `AFE:GND` |
| `PULSER.CN1.4` | `PULSER:3.3V NC` | `AFE.CN1.17` | `AFE:+3.3_VDD` |
| `PULSER.CN1.5` | `PULSER:LE` | `AFE.CN1.16` | `AFE:65` |
| `PULSER.CN1.6` | UNCONNECTED | `AFE.CN1.15` | UNCONNECTED |
| `PULSER.CN1.7` | `PULSER:DIN` | `AFE.CN1.14` | `AFE:63` |
| `PULSER.CN1.8` | `PULSER:GND` | `AFE.CN1.13` | `AFE:GND` |
| `PULSER.CN1.9` | `PULSER:GND` | `AFE.CN1.12` | `AFE:GND` |
| `PULSER.CN1.10` | `PULSER:CLK` | `AFE.CN1.11` | `AFE:39` |
| `PULSER.CN1.11` | `PULSER:SIG2_IN` | `AFE.CN1.10` | `AFE:59` |
| `PULSER.CN1.12` | `PULSER:GND` | `AFE.CN1.9` | `AFE:GND` |
| `PULSER.CN1.13` | `PULSER:GND` | `AFE.CN1.8` | `AFE:GND` |
| `PULSER.CN1.14` | UNCONNECTED | `AFE.CN1.7` | `AFE:35` |
| `PULSER.CN1.15` | `PULSER:SIG1_IN` | `AFE.CN1.6` | `AFE:57` |
| `PULSER.CN1.16` | `PULSER:GND` | `AFE.CN1.5` | `AFE:GND` |
| `PULSER.CN1.17` | `PULSER:CLR` | `AFE.CN1.4` | `AFE:53` |
| `PULSER.CN1.18` | `PULSER:DOUT_READBACK` | `AFE.CN1.3` | `AFE:33` |
| `PULSER.CN1.19` | `PULSER:DRIVER_EN` | `AFE.CN1.2` | `AFE:51` |
| `PULSER.CN1.20` | `PULSER:GND` | `AFE.CN1.1` | `AFE:GND` |

Similarly, `PULSER.RF2.5` is the pulser receive-side signal and `AFE.RF1.5` is the AFE input-side signal. A cable between these SMA ports is a plausible system connection, but neither archive specifies it. SMA pins 1–4 are ground on each board. Their physical cable connection remains unspecified.

## 3. Circuit paths for orientation

These descriptions summarize the pin tables. Arrows express a path through named component terminals, not a short circuit across the component or a guarantee of signal direction in every operating state.

### Pulser

- High-voltage connector: `CN2.1 = -100V`, `CN2.2 = GND`, `CN2.3 = +100V`. MOSFET source pins are `Q1.1/SN = -100V` and `Q1.3/SP = +100V`.
- Driver inputs: `CN1.15 → SIG1_IN → U6.1/INA`; `CN1.11 → SIG2_IN → U6.3/INB`; `CN1.19 → DRIVER_EN → U6.12/OE`.
- Positive gate path: `U6.9/OUTA → C26.1`, through C26 to `C26.2 → C24.2`, through C24 to `C24.1 → P_DRIVER_OUT_A → Q1.4/GP`.
- Negative gate path: `U6.7/OUTB → C3.1`, through C3 to `C3.2 → C25.1`, through unresolved placeholder C25 to `C25.2 → N_DRIVER_OUT_B → Q1.2/GN`.
- Pulse output: `Q1.5/DP` and `Q1.6/DP` share `D1.1`; `Q1.7/DN` and `Q1.8/DN` share `D1.2`; `D1.3` is on `PULSE_OUT`. `U4.3/B` is also on `PULSE_OUT`. `U4.1/A`, `D2.1`, `D2.2`, and `RF2.5` share the receive-side net; `D2.3` is ground. `U4.2/COM` is unconnected in the saved schematic.
- Serial switch chain: `CN1.7/DIN → U5.44/DIN`; `U5.39/DOUT → DOUT1 → U7.44/DIN`; `U7.39/DOUT → DOUT2 → U1.44/DIN`; `U1.39/DOUT → DOUT3 → U3.44/DIN`; `U3.39/DOUT → DOUT_READBACK → CN1.18`. The U1/U7 population discrepancy affects any physical implementation of this chain.
- On all four MAX14866 symbols, pin 38 is `LE`, pin 45 is `CLK`, pin 47 is `CLR`, and pin 46 is `SET`, aliased to ground. Pin 40 uses the literal supply label `3.3V NC`; pin 43 uses `+5V`. All COM/NO pins and every placeholder resistor are listed individually below.
- Inverter: `U2.2/IN = +5V`, `U2.1/OUT = -5V`, `U2.4/GND = GND`; `C9` bridges `U2.3/CFLY-` and `U2.5/CFLY+`.

### AFE / ADC

- Receive path: `RF1.5 → R6.1`; R13 connects this node to ground. Through R6 (33 Ω) the path reaches `R6.2`, `D1.1`, `D1.2`, and `C2.1`; `D1.3` is ground. Through C2 (100 nF), `C2.2 → IN1 → U1.A1`.
- USB-derived 5 V path: `5V-USB → L3.1`, through L3 (4.7 µH) to `L3.2/L7.1`, through L7 to `L7.2/+5_VDD`. The complete capacitor branches are in the component tables.
- 3.3 V regulator path: `+5_VDD → L1.1 → L1.2 → U2.2/IN` and `U2.1/EN`; `U2.4/OUT → L2.1 → L2.2 → +3.3_VDD`.
- 1.8 V regulator path: `+5_VDD → L10.1 → L10.2 → U12.2/IN` and `U12.1/EN`; `U12.4/OUT → L11.1 → L11.2 → +1.8_LVDD`.
- Clock: `U7.4/OUT+ → C53.2`, through C53 to `CLKP → U1.L1`; `U7.5/OUT- → C66.2`, through C66 to `CLKM → U1.K1`. R2 (100 Ω) bridges CLKP and CLKM. The 40 MHz designation is the source BOM comment.
- Connected ADC output pair: `U1.R4/OUT1M → OUT1M → U5.51`; `U1.P4/OUT1P → OUT1P → U5.53`. Frame clock: `U1.N9/FCLKP → U5.48` and `U1.N8/FCLKM → U5.46`. Lane clock: `U1.N1/LCLKP → U5.47` and `U1.N2/LCLKM → U5.45`.
- AFE control: `U6.70 → ADS_RST → U1.H9`; `U6.72 → R5 → SDATA → U1.H8`; `U6.76 → CS → U1.H7`; `U6.78 → R1 → SCLK → U1.H6`. These U6 references identify the connector on the AFE board.
- DAC control: AFE connector U5 pin 77 reaches `DAC_SYNC` through R9; pin 76 reaches `DAC_SCLK` through R10; pin 78 reaches `DAC_SDA` through R11. These nets reach U3 pins 9, 6, and 7 respectively.
- Gain-control path: `U3.2/VouτB → R16.2`, through R16 (200 Ω) to `R16.1 → VCNTL → U1.D2`; C42 (470 pF) connects VCNTL to ground. The source pin spelling `VouτB` is preserved. U3 output pins 1, 4, and 5 are unconnected.
- Reference: `U4.3/EN` and `U4.4/VIN` use `+1.8_LVDD`; `U4.6/VREF → 1.2V VREF → U3.10/REFIN`.

## 4. Component and pin tables

For a pin’s complete set of directly connected peers, find its primary net ID in Section 5. All endpoints in that record are connected under the stated reconstruction and confirmed-bridge rules. `Saved net` preserves the pre-bridge schematic ID when different; `same` means unchanged. `NEAR` refers to Section 8 and describes the source pin-to-wire geometry, not the physical solder bridge. A pin can have exact wire contact on a net whose label contact is NEAR; this is captured in the net record. Empty BOM fields are rendered as `not specified`.

### PULSER components

#### PULSER.C1 — 22uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 2 (item 1).

Value: `22uF`. Manufacturer part: `PA200V22M10X13`. Manufacturer: `JIERR(捷而瑞)`.

Footprint: `CAP-TH_BD10.0-P5.00-D0.6-FD-A`. Supplier: `LCSC`. Supplier part: `C53120970`.

Schematic source: `pulser-schematic.epru` line 3410, component `60499fd1b49e5d25`, symbol `dad83ee5113fbc65`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:+100V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C2 — 22uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 2 (item 1).

Value: `22uF`. Manufacturer part: `PA200V22M10X13`. Manufacturer: `JIERR(捷而瑞)`.

Footprint: `CAP-TH_BD10.0-P5.00-D0.6-FD-A`. Supplier: `LCSC`. Supplier part: `C53120970`.

Schematic source: `pulser-schematic.epru` line 3434, component `c69f1684b059d36a`, symbol `dad83ee5113fbc65`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:-100V` | same | CONNECTED | EXACT |

#### PULSER.C3 — 10nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 3 (item 2).

Value: `10nF`. Manufacturer part: `CC1206JKNPOZBN103`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C1206`. Supplier: `LCSC`. Supplier part: `C7500386`.

Schematic source: `pulser-schematic.epru` line 9533, component `5c3ff4a5ba7e14ad`, symbol `f147a7c1993cea2b`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_C3_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_C3_2` | same | CONNECTED | EXACT |

#### PULSER.C5 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 4 (item 3).

Value: `100nF`. Manufacturer part: `CGA8R4C0G2E104JT0Y0N`. Manufacturer: `TDK`.

Footprint: `C1812`. Supplier: `LCSC`. Supplier part: `C880714`.

Schematic source: `pulser-schematic.epru` line 3453, component `eb6531220340e5c2`, symbol `b0c576200cccd993`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:-100V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C6 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 4 (item 3).

Value: `100nF`. Manufacturer part: `CGA8R4C0G2E104JT0Y0N`. Manufacturer: `TDK`.

Footprint: `C1812`. Supplier: `LCSC`. Supplier part: `C880714`.

Schematic source: `pulser-schematic.epru` line 3464, component `4418f1bf77c9b863`, symbol `b0c576200cccd993`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+100V` | same | CONNECTED | EXACT |

#### PULSER.C7 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 4 (item 3).

Value: `100nF`. Manufacturer part: `CGA8R4C0G2E104JT0Y0N`. Manufacturer: `TDK`.

Footprint: `C1812`. Supplier: `LCSC`. Supplier part: `C880714`.

Schematic source: `pulser-schematic.epru` line 3474, component `1a0561ba9354529b`, symbol `b0c576200cccd993`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+100V` | same | CONNECTED | EXACT |

#### PULSER.C8 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 4 (item 3).

Value: `100nF`. Manufacturer part: `CGA8R4C0G2E104JT0Y0N`. Manufacturer: `TDK`.

Footprint: `C1812`. Supplier: `LCSC`. Supplier part: `C880714`.

Schematic source: `pulser-schematic.epru` line 3484, component `957e581445caf247`, symbol `b0c576200cccd993`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:-100V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C9 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6653, component `50ddaabb2b437199`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_C9_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_C9_2` | same | CONNECTED | EXACT |

#### PULSER.C10 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6674, component `43fafa83e9e030d9`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:-5V` | same | CONNECTED | EXACT |

#### PULSER.C11 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6684, component `c1c8875976d1ce0f`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+5V` | same | CONNECTED | EXACT |

#### PULSER.C12 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 6 (item 5).

Value: `100nF`. Manufacturer part: `CC0402KRX7R8BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C105883`.

Schematic source: `pulser-schematic.epru` line 6969, component `012b090b79f0ca10`, symbol `eb6c4d288e9d0666`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+5V` | same | CONNECTED | EXACT |

#### PULSER.C13 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6734, component `39e9d7e41494588e`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:-5V` | same | CONNECTED | EXACT |

#### PULSER.C14 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 6 (item 5).

Value: `100nF`. Manufacturer part: `CC0402KRX7R8BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C105883`.

Schematic source: `pulser-schematic.epru` line 6982, component `06f2461fb14ab03c`, symbol `eb6c4d288e9d0666`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+5V` | same | CONNECTED | EXACT |

#### PULSER.C15 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6765, component `07bebe957ffca555`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:-5V` | same | CONNECTED | EXACT |

#### PULSER.C16 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 6 (item 5).

Value: `100nF`. Manufacturer part: `CC0402KRX7R8BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C105883`.

Schematic source: `pulser-schematic.epru` line 6993, component `c927f8646802d750`, symbol `eb6c4d288e9d0666`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+5V` | same | CONNECTED | EXACT |

#### PULSER.C17 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6798, component `963e6f748067eb9d`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+5V` | same | CONNECTED | EXACT |

#### PULSER.C18 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 6 (item 5).

Value: `100nF`. Manufacturer part: `CC0402KRX7R8BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C105883`.

Schematic source: `pulser-schematic.epru` line 7006, component `237a48e17c3ebd14`, symbol `eb6c4d288e9d0666`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:-5V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C19 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6823, component `800da672e2547462`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+5V` | same | CONNECTED | EXACT |

#### PULSER.C20 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 6 (item 5).

Value: `100nF`. Manufacturer part: `CC0402KRX7R8BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C105883`.

Schematic source: `pulser-schematic.epru` line 7019, component `51c8e411ba4c0586`, symbol `eb6c4d288e9d0666`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:-5V` | same | CONNECTED | EXACT |

#### PULSER.C21 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6860, component `4c406d4091154d13`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:-5V` | same | CONNECTED | EXACT |

#### PULSER.C22 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 6 (item 5).

Value: `100nF`. Manufacturer part: `CC0402KRX7R8BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C105883`.

Schematic source: `pulser-schematic.epru` line 7032, component `01e6fb5fd25b532b`, symbol `eb6c4d288e9d0666`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:-5V` | same | CONNECTED | EXACT |

#### PULSER.C23 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 5 (item 4).

Value: `1uF`. Manufacturer part: `CL10B105KA8NNNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C29936`.

Schematic source: `pulser-schematic.epru` line 6892, component `46188a0e0b289862`, symbol `2062c01a08ef4663`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:+5V` | same | CONNECTED | EXACT |

#### PULSER.C24 — 100nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 7 (item 6).

Value: `100nF`. Manufacturer part: `CL10B104KA8WPNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `C346190`.

Schematic source: `pulser-schematic.epru` line 6927, component `d36ef7ee15393538`, symbol `2ecdc7c6bb557b0a`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:P_DRIVER_OUT_A` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_C24_2` | same | CONNECTED | NEAR |

#### PULSER.C25 — PLACEHOLDER FOR RESISTOR LATER

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 8 (item 7).

Value: `PLACEHOLDER FOR RESISTOR LATER`. Manufacturer part: `CL10B104KA8WPNC`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0603`. Supplier: `LCSC`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6937, component `b7f01cd60aaedd3c`, symbol `2ecdc7c6bb557b0a`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_C3_2` | same | CONNECTED | NEAR |
| `2` | `2` | `PULSER:N_DRIVER_OUT_B` | same | CONNECTED | EXACT |

#### PULSER.C26 — 10nF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 3 (item 2).

Value: `10nF`. Manufacturer part: `CC1206JKNPOZBN103`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C1206`. Supplier: `LCSC`. Supplier part: `C7500386`.

Schematic source: `pulser-schematic.epru` line 9523, component `da38ad0ba46c7892`, symbol `f147a7c1993cea2b`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_C26_1` | same | CONNECTED | NEAR |
| `2` | `2` | `PULSER:N_C24_2` | same | CONNECTED | EXACT |

#### PULSER.C34 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9225, component `60267d3dedcc82fc`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C35 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9235, component `8a4332130030f3ab`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C36 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9245, component `93ba45beb1126529`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C37 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9255, component `18f9b2e0c12c15b9`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C38 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9283, component `adf0692262b81d5f`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C39 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9293, component `ccc02a0a4642d9d8`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C40 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9303, component `329573045823645a`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.C41 — 1uF

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 9 (item 8).

Value: `1uF`. Manufacturer part: `TCC0402X7R105K160AT`. Manufacturer: `CCTC(三环)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C49210445`.

Schematic source: `pulser-schematic.epru` line 9313, component `928a67c49332d39f`, symbol `8a6029d0ae4aabee`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.CN1 — 321020MG0CBK00A01

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 10 (item 9).

Value: `not specified`. Manufacturer part: `321020MG0CBK00A01`. Manufacturer: `JILN(锦凌)`.

Footprint: `CONN-SMD_321020MG0CBK00A0`. Supplier: `LCSC`. Supplier part: `C601970`.

Schematic source: `pulser-schematic.epru` line 5551, component `ce556b8360bfd89f`, symbol `bd8036b8d00fbd7e`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:1.8V NC` | same | SINGLE_PIN_NET | EXACT |
| `3` | `3` | `PULSER:GND` | same | CONNECTED | EXACT |
| `4` | `4` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `5` | `5` | `PULSER:LE` | same | CONNECTED | EXACT |
| `6` | `6` | — | same | UNCONNECTED | NONE |
| `7` | `7` | `PULSER:DIN` | same | CONNECTED | EXACT |
| `8` | `8` | `PULSER:GND` | same | CONNECTED | EXACT |
| `9` | `9` | `PULSER:GND` | same | CONNECTED | EXACT |
| `10` | `10` | `PULSER:CLK` | same | CONNECTED | EXACT |
| `11` | `11` | `PULSER:SIG2_IN` | same | CONNECTED | EXACT |
| `12` | `12` | `PULSER:GND` | same | CONNECTED | EXACT |
| `13` | `13` | `PULSER:GND` | same | CONNECTED | EXACT |
| `14` | `14` | — | same | UNCONNECTED | NONE |
| `15` | `15` | `PULSER:SIG1_IN` | same | CONNECTED | EXACT |
| `16` | `16` | `PULSER:GND` | same | CONNECTED | EXACT |
| `17` | `17` | `PULSER:CLR` | same | CONNECTED | EXACT |
| `18` | `18` | `PULSER:DOUT_READBACK` | same | CONNECTED | EXACT |
| `19` | `19` | `PULSER:DRIVER_EN` | same | CONNECTED | EXACT |
| `20` | `20` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.CN2 — DB128L-5.08-3P-GN-S

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 11 (item 10).

Value: `not specified`. Manufacturer part: `DB128L-5.08-3P-GN-S`. Manufacturer: `DORABO(地博电气)`.

Footprint: `CONN-TH_DB128L-5.08-3P_1`. Supplier: `LCSC`. Supplier part: `C395869`.

Schematic source: `pulser-schematic.epru` line 7745, component `199e0fa88921f987`, symbol `f4fb586c2645ca3b`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:-100V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |
| `3` | `3` | `PULSER:+100V` | same | CONNECTED | EXACT |

#### PULSER.D1 — BAS21S

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 12 (item 11).

Value: `not specified`. Manufacturer part: `BAS21S`. Manufacturer: `CJ(江苏长电/长晶)`.

Footprint: `SOT-23_L2.9-W1.3-P1.90-LS2.4-BR`. Supplier: `LCSC`. Supplier part: `C68966`.

Schematic source: `pulser-schematic.epru` line 3351, component `da2270622261f4d6`, symbol `cc0bb350d98b19e8`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_D1_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_D1_2` | same | CONNECTED | EXACT |
| `3` | `3` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.D2 — BAV99T

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 13 (item 12).

Value: `not specified`. Manufacturer part: `BAV99T`. Manufacturer: `TWGMC(迪嘉)`.

Footprint: `SOT-523-3_L1.6-W0.8-P1.00-LS1.6-BR`. Supplier: `LCSC`. Supplier part: `C49438156`.

Schematic source: `pulser-schematic.epru` line 6570, component `0c4acb42c8138fae`, symbol `6e431f1fbed40f8d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_D2_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_D2_1` | same | CONNECTED | EXACT |
| `3` | `3` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.Q1 — TC6320TG-G

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 14 (item 13).

Value: `not specified`. Manufacturer part: `TC6320TG-G`. Manufacturer: `MICROCHIP(美国微芯)`.

Footprint: `SOIC-8_L4.9-W3.9-P1.27-LS6.0-BL`. Supplier: `LCSC`. Supplier part: `C624992`.

Schematic source: `pulser-schematic.epru` line 3114, component `bd2f8750953d0d0f`, symbol `1391286d9464f789`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `SN` | `PULSER:-100V` | same | CONNECTED | EXACT |
| `2` | `GN` | `PULSER:N_DRIVER_OUT_B` | same | CONNECTED | EXACT |
| `3` | `SP` | `PULSER:+100V` | same | CONNECTED | EXACT |
| `4` | `GP` | `PULSER:P_DRIVER_OUT_A` | same | CONNECTED | EXACT |
| `5` | `DP` | `PULSER:N_D1_1` | same | CONNECTED | NEAR |
| `6` | `DP` | `PULSER:N_D1_1` | same | CONNECTED | EXACT |
| `7` | `DN` | `PULSER:N_D1_2` | same | CONNECTED | EXACT |
| `8` | `DN` | `PULSER:N_D1_2` | same | CONNECTED | NEAR |

#### PULSER.R2 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 3648, component `45a43c206d4e0133`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R2_2` | same | CONNECTED | EXACT |

#### PULSER.R3 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 3698, component `aacf1951d0109fd6`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R3_2` | same | CONNECTED | EXACT |

#### PULSER.R4 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 3748, component `450f4baa2f5098db`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R4_2` | same | CONNECTED | EXACT |

#### PULSER.R5 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 3798, component `7afd0ad2ed194477`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R5_2` | same | CONNECTED | EXACT |

#### PULSER.R6 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 3848, component `d02de892112404ee`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R6_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R7 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 3898, component `769b5466e7c74e5b`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R7_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R8 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 3948, component `e1e570ad05f8dc5b`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R8_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R10 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4034, component `d86daaed626f2233`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R10_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R12 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4120, component `29c1614e5f5ed109`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R12_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R13 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4170, component `c3af5b8a4981bb4a`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R13_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R14 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4220, component `6faa883090f8ba25`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R14_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R15 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4270, component `ef3470a7c46f7d1c`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R15_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R16 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4320, component `93543ea0527c422d`, symbol `dc207e61e89dc971`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:N_R16_1` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.R17 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4592, component `b79cc5df7c573581`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | `PULSER:N_R17_2` | CONNECTED | EXACT |

#### PULSER.R18 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4604, component `948ce584242759e2`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | `PULSER:N_R18_2` | CONNECTED | EXACT |

#### PULSER.R19 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4615, component `b46d9837ac8f0b60`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | `PULSER:N_R19_2` | CONNECTED | EXACT |

#### PULSER.R20 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4626, component `c2b0a75f76e19f3c`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | `PULSER:N_R20_2` | CONNECTED | EXACT |

#### PULSER.R21 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4637, component `25b5b628da6b639a`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | `PULSER:N_R21_2` | CONNECTED | EXACT |

#### PULSER.R22 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4648, component `3595954d3a649246`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R22_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R23 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4659, component `bd80495b6f1b0958`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R23_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R24 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4670, component `cc21370716f14b96`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R24_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R25 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4681, component `34b2d4d3a72af3b5`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R25_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R26 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4692, component `7db680050716bb2b`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R26_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R27 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4703, component `bcf761cc95177b60`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R27_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R28 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4714, component `bc14537097dc7d60`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R28_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R29 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4725, component `6f38c46b83301097`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R29_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R30 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4736, component `2ec5dbb51030c409`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R30_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R31 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4747, component `095e7f7248d81bac`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R31_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R32 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 4758, component `e8057e2928d90767`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO11` | `PULSER:N_R32_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO11` | same | CONNECTED | EXACT |

#### PULSER.R33 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5080, component `a052a9948b2c46b7`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | `PULSER:N_R33_2` | CONNECTED | EXACT |

#### PULSER.R34 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5092, component `a862ac2a16c22720`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | `PULSER:N_R34_2` | CONNECTED | EXACT |

#### PULSER.R35 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5103, component `d42b96ef4b6e2fc3`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | `PULSER:N_R35_2` | CONNECTED | EXACT |

#### PULSER.R36 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5114, component `c5565ba0b8678e38`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | `PULSER:N_R36_2` | CONNECTED | EXACT |

#### PULSER.R37 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5125, component `bd904c34fd516baa`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | `PULSER:N_R37_2` | CONNECTED | EXACT |

#### PULSER.R38 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5136, component `fff77e090a631e7b`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R38_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R39 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5147, component `f894645b88fc2aae`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R39_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R40 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5158, component `a2a04ed0b8e6831b`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R40_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R41 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5169, component `6bd6c2c0bbbdc906`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R41_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R42 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5180, component `c27c5a75e2850784`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R42_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R43 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5191, component `27b212268fc91a22`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R43_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R44 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5202, component `2fa86772f413e0da`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R44_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R45 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5213, component `8bb895bd9da2c322`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R45_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R46 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5224, component `8b0233450921de63`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R46_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R47 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5235, component `039242416304b614`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R47_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R48 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5246, component `e8722862e07d43e5`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO5` | `PULSER:N_R48_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO5` | same | CONNECTED | EXACT |

#### PULSER.R49 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5915, component `332d6d8957861912`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | `PULSER:N_R49_2` | CONNECTED | EXACT |

#### PULSER.R50 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5931, component `e88d324bdc895761`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | `PULSER:N_R50_2` | CONNECTED | EXACT |

#### PULSER.R51 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5947, component `408b70a4cd37babd`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | `PULSER:N_R51_2` | CONNECTED | EXACT |

#### PULSER.R52 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5963, component `a20156113bad1700`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | `PULSER:N_R52_2` | CONNECTED | EXACT |

#### PULSER.R53 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5979, component `c0fd91f59a889dbb`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | `PULSER:N_R53_2` | CONNECTED | EXACT |

#### PULSER.R54 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 5995, component `c6579ceafda1f6fc`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R54_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R55 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6011, component `652279bab288938a`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R55_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R56 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6027, component `109c7d5fc0f5a85b`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R56_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R57 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6043, component `f44fdc0a9798c4cc`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R57_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R58 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6059, component `2adfe6483311e9c7`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R58_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R59 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6075, component `4e8efc2234f06504`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R59_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R60 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6091, component `952f13ddecd9fb60`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R60_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R61 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6107, component `e4e34a21042dee56`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R61_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R62 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6123, component `58c466e998e03560`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R62_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R63 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6139, component `bba64280157598db`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R63_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R64 — Blob-Standin

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 15 (item 14).

Value: `Blob-Standin`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `R0603`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 6155, component `90c571fbd71dbd13`, symbol `dc207e61e89dc971`.

Physical override: solder gap confirmed closed by owner; pins 1 and 2 are shorted in the primary netlist. BOM metadata above is retained unchanged.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:NO7` | `PULSER:N_R64_1` | CONNECTED | EXACT |
| `2` | `2` | `PULSER:NO7` | same | CONNECTED | EXACT |

#### PULSER.R65 — 47kΩ

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 16 (item 15).

Value: `47kΩ`. Manufacturer part: `FRS2512J473 TS`. Manufacturer: `FOJAN(富捷)`.

Footprint: `R2512`. Supplier: `LCSC`. Supplier part: `C49010114`.

Schematic source: `pulser-schematic.epru` line 9359, component `04e7b8c4a10b2ee0`, symbol `7d87d0b1f6c4b5cc`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:-100V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R65_2` | same | CONNECTED | EXACT |

#### PULSER.R66 — 47kΩ

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 16 (item 15).

Value: `47kΩ`. Manufacturer part: `FRS2512J473 TS`. Manufacturer: `FOJAN(富捷)`.

Footprint: `R2512`. Supplier: `LCSC`. Supplier part: `C49010114`.

Schematic source: `pulser-schematic.epru` line 9370, component `442cdf8687b87983`, symbol `7d87d0b1f6c4b5cc`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:+100V` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R66_2` | same | CONNECTED | EXACT |

#### PULSER.R67 — 1.5kΩ

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 17 (item 16).

Value: `1.5kΩ`. Manufacturer part: `RT0402BRD071K5L`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0402`. Supplier: `LCSC`. Supplier part: `C281775`.

Schematic source: `pulser-schematic.epru` line 9454, component `a0c608cbea22c18d`, symbol `95586970812a246f`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R67_2` | same | CONNECTED | EXACT |

#### PULSER.R68 — 1.5kΩ

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 17 (item 16).

Value: `1.5kΩ`. Manufacturer part: `RT0402BRD071K5L`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0402`. Supplier: `LCSC`. Supplier part: `C281775`.

Schematic source: `pulser-schematic.epru` line 9464, component `36238dbfa7abaa1c`, symbol `95586970812a246f`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:N_R68_2` | same | CONNECTED | EXACT |

#### PULSER.RF2 — 3GHz

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 18 (item 17).

Value: `3GHz`. Manufacturer part: `SMA-KE-347-H13.5-1.6`. Manufacturer: `XUNPU(讯普)`.

Footprint: `SMA-SMD_SMA-KE-347-H13.5-1.6`. Supplier: `LCSC`. Supplier part: `C5723200`.

Schematic source: `pulser-schematic.epru` line 3185, component `e0e3fc9466c8b7e7`, symbol `488a4ac232739c05`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |
| `3` | `3` | `PULSER:GND` | same | CONNECTED | EXACT |
| `4` | `4` | `PULSER:GND` | same | CONNECTED | EXACT |
| `5` | `5` | `PULSER:N_D2_1` | same | CONNECTED | EXACT |

#### PULSER.U1 — MAX14866UTM+

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 19 (item 18).

Value: `not specified`. Manufacturer part: `MAX14866UTM+`. Manufacturer: `ADI(亚德诺)/MAXIM(美信)`.

Footprint: `TQFN-48_L7.0-W7.0-P0.50-TL-EP5.1`. Supplier: `LCSC`. Supplier part: `C1545887`.

Schematic source: `pulser-schematic.epru` line 5881, component `aa9fa6b15a9c0aea`, symbol `9a9da789188b535d`.

Population conflict: schematic `Add into BOM = no`; present in supplied BOM.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `COM0` | `PULSER:NO7` | `PULSER:N_R64_1` | CONNECTED | EXACT |
| `2` | `NO0` | `PULSER:3NO0` | same | CONNECTED | EXACT |
| `3` | `COM1` | `PULSER:NO7` | `PULSER:N_R63_1` | CONNECTED | EXACT |
| `4` | `NO1` | `PULSER:3NO1` | same | CONNECTED | EXACT |
| `5` | `COM2` | `PULSER:NO7` | `PULSER:N_R62_1` | CONNECTED | EXACT |
| `6` | `NO2` | `PULSER:3NO2` | same | CONNECTED | EXACT |
| `7` | `COM3` | `PULSER:NO7` | `PULSER:N_R61_1` | CONNECTED | EXACT |
| `8` | `NO3` | `PULSER:3NO3` | same | CONNECTED | EXACT |
| `9` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `10` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `11` | `COM4` | `PULSER:NO7` | `PULSER:N_R60_1` | CONNECTED | EXACT |
| `12` | `NO4` | `PULSER:3NO4` | same | CONNECTED | EXACT |
| `13` | `COM5` | `PULSER:NO7` | `PULSER:N_R59_1` | CONNECTED | EXACT |
| `14` | `NO5` | `PULSER:3NO5` | same | CONNECTED | EXACT |
| `15` | `COM6` | `PULSER:NO7` | `PULSER:N_R58_1` | CONNECTED | EXACT |
| `16` | `NO6` | `PULSER:3NO6` | same | CONNECTED | EXACT |
| `17` | `COM7` | `PULSER:NO7` | `PULSER:N_R57_1` | CONNECTED | EXACT |
| `18` | `NO7` | `PULSER:3NO7` | same | CONNECTED | EXACT |
| `19` | `NO8` | `PULSER:3NO8` | same | CONNECTED | EXACT |
| `20` | `COM8` | `PULSER:NO7` | `PULSER:N_R56_1` | CONNECTED | EXACT |
| `21` | `NO9` | `PULSER:3NO9` | same | CONNECTED | EXACT |
| `22` | `COM9` | `PULSER:NO7` | `PULSER:N_R55_1` | CONNECTED | EXACT |
| `23` | `NO10` | `PULSER:3NO10` | same | CONNECTED | EXACT |
| `24` | `COM10` | `PULSER:NO7` | `PULSER:N_R54_1` | CONNECTED | EXACT |
| `25` | `NO11` | `PULSER:3NO11` | same | CONNECTED | EXACT |
| `26` | `COM11` | `PULSER:NO7` | `PULSER:N_R49_2` | CONNECTED | EXACT |
| `27` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `28` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `29` | `NO12` | `PULSER:3NO12` | same | CONNECTED | EXACT |
| `30` | `COM12` | `PULSER:NO7` | `PULSER:N_R50_2` | CONNECTED | EXACT |
| `31` | `NO13` | `PULSER:3NO13` | same | CONNECTED | EXACT |
| `32` | `COM13` | `PULSER:NO7` | `PULSER:N_R51_2` | CONNECTED | EXACT |
| `33` | `NO14` | `PULSER:3NO14` | same | CONNECTED | EXACT |
| `34` | `COM14` | `PULSER:NO7` | `PULSER:N_R52_2` | CONNECTED | EXACT |
| `35` | `NO15` | `PULSER:3NO15` | same | CONNECTED | EXACT |
| `36` | `COM15` | `PULSER:NO7` | `PULSER:N_R53_2` | CONNECTED | EXACT |
| `37` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `38` | `LE` | `PULSER:LE` | same | CONNECTED | EXACT |
| `39` | `DOUT` | `PULSER:DOUT3` | same | CONNECTED | EXACT |
| `40` | `VDD` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `41` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `42` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `43` | `VCC` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `44` | `DIN` | `PULSER:DOUT2` | same | CONNECTED | EXACT |
| `45` | `CLK` | `PULSER:CLK` | same | CONNECTED | EXACT |
| `46` | `SET` | `PULSER:GND` | same | CONNECTED | EXACT |
| `47` | `CLR` | `PULSER:CLR` | same | CONNECTED | EXACT |
| `48` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `49` | `EP` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.U2 — TPS60403DBVR

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 20 (item 19).

Value: `not specified`. Manufacturer part: `TPS60403DBVR`. Manufacturer: `TI(德州仪器)`.

Footprint: `SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BR`. Supplier: `LCSC`. Supplier part: `C11338`.

Schematic source: `pulser-schematic.epru` line 6610, component `c65cbb677ac23800`, symbol `2458d7a0ce36d02c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `OUT` | `PULSER:-5V` | same | CONNECTED | NEAR |
| `2` | `IN` | `PULSER:+5V` | same | CONNECTED | NEAR |
| `3` | `CFLY-` | `PULSER:N_C9_1` | same | CONNECTED | EXACT |
| `4` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `5` | `CFLY+` | `PULSER:N_C9_2` | same | CONNECTED | EXACT |

#### PULSER.U3 — MAX14866UTM+

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 19 (item 18).

Value: `not specified`. Manufacturer part: `MAX14866UTM+`. Manufacturer: `ADI(亚德诺)/MAXIM(美信)`.

Footprint: `TQFN-48_L7.0-W7.0-P0.50-TL-EP5.1`. Supplier: `LCSC`. Supplier part: `C1545887`.

Schematic source: `pulser-schematic.epru` line 4557, component `40c289f5bef2311c`, symbol `9a9da789188b535d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `COM0` | `PULSER:NO11` | `PULSER:N_R32_1` | CONNECTED | EXACT |
| `2` | `NO0` | `PULSER:1NO0` | same | CONNECTED | EXACT |
| `3` | `COM1` | `PULSER:NO11` | `PULSER:N_R31_1` | CONNECTED | EXACT |
| `4` | `NO1` | `PULSER:1NO1` | same | CONNECTED | EXACT |
| `5` | `COM2` | `PULSER:NO11` | `PULSER:N_R30_1` | CONNECTED | EXACT |
| `6` | `NO2` | `PULSER:1NO2` | same | CONNECTED | EXACT |
| `7` | `COM3` | `PULSER:NO11` | `PULSER:N_R29_1` | CONNECTED | EXACT |
| `8` | `NO3` | `PULSER:1NO3` | same | CONNECTED | EXACT |
| `9` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `10` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `11` | `COM4` | `PULSER:NO11` | `PULSER:N_R28_1` | CONNECTED | EXACT |
| `12` | `NO4` | `PULSER:1NO4` | same | CONNECTED | EXACT |
| `13` | `COM5` | `PULSER:NO11` | `PULSER:N_R27_1` | CONNECTED | EXACT |
| `14` | `NO5` | `PULSER:1NO5` | same | CONNECTED | EXACT |
| `15` | `COM6` | `PULSER:NO11` | `PULSER:N_R26_1` | CONNECTED | EXACT |
| `16` | `NO6` | `PULSER:1NO6` | same | CONNECTED | EXACT |
| `17` | `COM7` | `PULSER:NO11` | `PULSER:N_R25_1` | CONNECTED | EXACT |
| `18` | `NO7` | `PULSER:1NO7` | same | CONNECTED | EXACT |
| `19` | `NO8` | `PULSER:1NO8` | same | CONNECTED | EXACT |
| `20` | `COM8` | `PULSER:NO11` | `PULSER:N_R24_1` | CONNECTED | EXACT |
| `21` | `NO9` | `PULSER:1NO9` | same | CONNECTED | EXACT |
| `22` | `COM9` | `PULSER:NO11` | `PULSER:N_R23_1` | CONNECTED | EXACT |
| `23` | `NO10` | `PULSER:1NO10` | same | CONNECTED | EXACT |
| `24` | `COM10` | `PULSER:NO11` | `PULSER:N_R22_1` | CONNECTED | EXACT |
| `25` | `NO11` | `PULSER:1NO11` | same | CONNECTED | EXACT |
| `26` | `COM11` | `PULSER:NO11` | `PULSER:N_R17_2` | CONNECTED | EXACT |
| `27` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `28` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `29` | `NO12` | `PULSER:1NO12` | same | CONNECTED | EXACT |
| `30` | `COM12` | `PULSER:NO11` | `PULSER:N_R18_2` | CONNECTED | EXACT |
| `31` | `NO13` | `PULSER:1NO13` | same | CONNECTED | EXACT |
| `32` | `COM13` | `PULSER:NO11` | `PULSER:N_R19_2` | CONNECTED | EXACT |
| `33` | `NO14` | `PULSER:1NO14` | same | CONNECTED | EXACT |
| `34` | `COM14` | `PULSER:NO11` | `PULSER:N_R20_2` | CONNECTED | EXACT |
| `35` | `NO15` | `PULSER:1NO15` | same | CONNECTED | EXACT |
| `36` | `COM15` | `PULSER:NO11` | `PULSER:N_R21_2` | CONNECTED | EXACT |
| `37` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `38` | `LE` | `PULSER:LE` | same | CONNECTED | EXACT |
| `39` | `DOUT` | `PULSER:DOUT_READBACK` | same | CONNECTED | EXACT |
| `40` | `VDD` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `41` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `42` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `43` | `VCC` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `44` | `DIN` | `PULSER:DOUT3` | same | CONNECTED | EXACT |
| `45` | `CLK` | `PULSER:CLK` | same | CONNECTED | EXACT |
| `46` | `SET` | `PULSER:GND` | same | CONNECTED | EXACT |
| `47` | `CLR` | `PULSER:CLR` | same | CONNECTED | EXACT |
| `48` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `49` | `EP` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.U4 — MD0100N8-G

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 21 (item 20).

Value: `not specified`. Manufacturer part: `MD0100N8-G`. Manufacturer: `MICROCHIP(美国微芯)`.

Footprint: `SOT-89-3_L4.5-W2.5-P1.50-LS4.2-BR`. Supplier: `LCSC`. Supplier part: `C629131`.

Schematic source: `pulser-schematic.epru` line 3052, component `961d1c2c4ce8ab3c`, symbol `037d94b0af592212`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `A` | `PULSER:N_D2_1` | same | CONNECTED | EXACT |
| `2` | `COM` | — | same | UNCONNECTED | NONE |
| `3` | `B` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |

#### PULSER.U5 — MAX14866UTM+

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 19 (item 18).

Value: `not specified`. Manufacturer part: `MAX14866UTM+`. Manufacturer: `ADI(亚德诺)/MAXIM(美信)`.

Footprint: `TQFN-48_L7.0-W7.0-P0.50-TL-EP5.1`. Supplier: `LCSC`. Supplier part: `C1545887`.

Schematic source: `pulser-schematic.epru` line 3081, component `c9b04c5b8a6e7867`, symbol `9a9da789188b535d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `COM0` | `PULSER:N_R16_1` | same | CONNECTED | EXACT |
| `2` | `NO0` | `PULSER:NO0` | same | SINGLE_PIN_NET | EXACT |
| `3` | `COM1` | `PULSER:N_R15_1` | same | CONNECTED | EXACT |
| `4` | `NO1` | `PULSER:NO1` | same | SINGLE_PIN_NET | EXACT |
| `5` | `COM2` | `PULSER:N_R14_1` | same | CONNECTED | EXACT |
| `6` | `NO2` | `PULSER:NO2` | same | SINGLE_PIN_NET | EXACT |
| `7` | `COM3` | `PULSER:N_R13_1` | same | CONNECTED | EXACT |
| `8` | `NO3` | `PULSER:NO3` | same | SINGLE_PIN_NET | EXACT |
| `9` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `10` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `11` | `COM4` | `PULSER:N_R12_1` | same | CONNECTED | EXACT |
| `12` | `NO4` | `PULSER:NO4` | same | SINGLE_PIN_NET | EXACT |
| `13` | `COM5` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |
| `14` | `NO5` | `PULSER:NO5` | same | CONNECTED | EXACT |
| `15` | `COM6` | `PULSER:N_R10_1` | same | CONNECTED | EXACT |
| `16` | `NO6` | `PULSER:NO6` | same | SINGLE_PIN_NET | EXACT |
| `17` | `COM7` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |
| `18` | `NO7` | `PULSER:NO7` | same | CONNECTED | EXACT |
| `19` | `NO8` | `PULSER:NO8` | same | SINGLE_PIN_NET | EXACT |
| `20` | `COM8` | `PULSER:N_R8_1` | same | CONNECTED | EXACT |
| `21` | `NO9` | `PULSER:NO9` | same | SINGLE_PIN_NET | EXACT |
| `22` | `COM9` | `PULSER:N_R7_1` | same | CONNECTED | EXACT |
| `23` | `NO10` | `PULSER:NO10` | same | SINGLE_PIN_NET | EXACT |
| `24` | `COM10` | `PULSER:N_R6_1` | same | CONNECTED | EXACT |
| `25` | `NO11` | `PULSER:NO11` | same | CONNECTED | EXACT |
| `26` | `COM11` | `PULSER:PULSE_OUT` | same | CONNECTED | EXACT |
| `27` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `28` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `29` | `NO12` | `PULSER:NO12` | same | SINGLE_PIN_NET | EXACT |
| `30` | `COM12` | `PULSER:N_R2_2` | same | CONNECTED | EXACT |
| `31` | `NO13` | `PULSER:NO13` | same | SINGLE_PIN_NET | EXACT |
| `32` | `COM13` | `PULSER:N_R3_2` | same | CONNECTED | EXACT |
| `33` | `NO14` | `PULSER:NO14` | same | SINGLE_PIN_NET | EXACT |
| `34` | `COM14` | `PULSER:N_R4_2` | same | CONNECTED | EXACT |
| `35` | `NO15` | `PULSER:NO15` | same | SINGLE_PIN_NET | EXACT |
| `36` | `COM15` | `PULSER:N_R5_2` | same | CONNECTED | EXACT |
| `37` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `38` | `LE` | `PULSER:LE` | same | CONNECTED | EXACT |
| `39` | `DOUT` | `PULSER:DOUT1` | same | CONNECTED | EXACT |
| `40` | `VDD` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `41` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `42` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `43` | `VCC` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `44` | `DIN` | `PULSER:DIN` | same | CONNECTED | EXACT |
| `45` | `CLK` | `PULSER:CLK` | same | CONNECTED | EXACT |
| `46` | `SET` | `PULSER:GND` | same | CONNECTED | EXACT |
| `47` | `CLR` | `PULSER:CLR` | same | CONNECTED | EXACT |
| `48` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `49` | `EP` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.U6 — MD1213K6-G

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 22 (item 21).

Value: `not specified`. Manufacturer part: `MD1213K6-G`. Manufacturer: `MICROCHIP(美国微芯)`.

Footprint: `QFN-12_L4.0-W4.0-P0.80-BL-EP1.7`. Supplier: `LCSC`. Supplier part: `C621434`.

Schematic source: `pulser-schematic.epru` line 3148, component `2ae050f63c74e9e0`, symbol `554b9e101997cab1`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `INA` | `PULSER:SIG1_IN` | same | CONNECTED | EXACT |
| `2` | `VL` | `PULSER:-5V` | same | CONNECTED | EXACT |
| `3` | `INB` | `PULSER:SIG2_IN` | same | CONNECTED | NEAR |
| `4` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `5` | `VSS1` | `PULSER:-5V` | same | CONNECTED | EXACT |
| `6` | `VSS2` | `PULSER:-5V` | same | CONNECTED | EXACT |
| `7` | `OUTB` | `PULSER:N_C3_1` | same | CONNECTED | EXACT |
| `8` | `VH` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `9` | `OUTA` | `PULSER:N_C26_1` | same | CONNECTED | EXACT |
| `10` | `VDD2` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `11` | `VDD1` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `12` | `OE` | `PULSER:DRIVER_EN` | same | CONNECTED | EXACT |
| `13` | `EP` | `PULSER:-5V` | same | CONNECTED | NEAR |

#### PULSER.U7 — MAX14866UTM+

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 19 (item 18).

Value: `not specified`. Manufacturer part: `MAX14866UTM+`. Manufacturer: `ADI(亚德诺)/MAXIM(美信)`.

Footprint: `TQFN-48_L7.0-W7.0-P0.50-TL-EP5.1`. Supplier: `LCSC`. Supplier part: `C1545887`.

Schematic source: `pulser-schematic.epru` line 5045, component `e8f1768174d70074`, symbol `9a9da789188b535d`.

Population conflict: schematic `Add into BOM = no`; present in supplied BOM.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `COM0` | `PULSER:NO5` | `PULSER:N_R48_1` | CONNECTED | EXACT |
| `2` | `NO0` | `PULSER:2NO0` | same | CONNECTED | EXACT |
| `3` | `COM1` | `PULSER:NO5` | `PULSER:N_R47_1` | CONNECTED | EXACT |
| `4` | `NO1` | `PULSER:2NO1` | same | CONNECTED | EXACT |
| `5` | `COM2` | `PULSER:NO5` | `PULSER:N_R46_1` | CONNECTED | EXACT |
| `6` | `NO2` | `PULSER:2NO2` | same | CONNECTED | EXACT |
| `7` | `COM3` | `PULSER:NO5` | `PULSER:N_R45_1` | CONNECTED | EXACT |
| `8` | `NO3` | `PULSER:2NO3` | same | CONNECTED | EXACT |
| `9` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `10` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `11` | `COM4` | `PULSER:NO5` | `PULSER:N_R44_1` | CONNECTED | EXACT |
| `12` | `NO4` | `PULSER:2NO4` | same | CONNECTED | EXACT |
| `13` | `COM5` | `PULSER:NO5` | `PULSER:N_R43_1` | CONNECTED | EXACT |
| `14` | `NO5` | `PULSER:2NO5` | same | CONNECTED | EXACT |
| `15` | `COM6` | `PULSER:NO5` | `PULSER:N_R42_1` | CONNECTED | EXACT |
| `16` | `NO6` | `PULSER:2NO6` | same | CONNECTED | EXACT |
| `17` | `COM7` | `PULSER:NO5` | `PULSER:N_R41_1` | CONNECTED | EXACT |
| `18` | `NO7` | `PULSER:2NO7` | same | CONNECTED | EXACT |
| `19` | `NO8` | `PULSER:2NO8` | same | CONNECTED | EXACT |
| `20` | `COM8` | `PULSER:NO5` | `PULSER:N_R40_1` | CONNECTED | EXACT |
| `21` | `NO9` | `PULSER:2NO9` | same | CONNECTED | EXACT |
| `22` | `COM9` | `PULSER:NO5` | `PULSER:N_R39_1` | CONNECTED | EXACT |
| `23` | `NO10` | `PULSER:2NO10` | same | CONNECTED | EXACT |
| `24` | `COM10` | `PULSER:NO5` | `PULSER:N_R38_1` | CONNECTED | EXACT |
| `25` | `NO11` | `PULSER:2NO11` | same | CONNECTED | EXACT |
| `26` | `COM11` | `PULSER:NO5` | `PULSER:N_R33_2` | CONNECTED | EXACT |
| `27` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `28` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `29` | `NO12` | `PULSER:2NO12` | same | CONNECTED | EXACT |
| `30` | `COM12` | `PULSER:NO5` | `PULSER:N_R34_2` | CONNECTED | EXACT |
| `31` | `NO13` | `PULSER:2NO13` | same | CONNECTED | EXACT |
| `32` | `COM13` | `PULSER:NO5` | `PULSER:N_R35_2` | CONNECTED | EXACT |
| `33` | `NO14` | `PULSER:2NO14` | same | CONNECTED | EXACT |
| `34` | `COM14` | `PULSER:NO5` | `PULSER:N_R36_2` | CONNECTED | EXACT |
| `35` | `NO15` | `PULSER:2NO15` | same | CONNECTED | EXACT |
| `36` | `COM15` | `PULSER:NO5` | `PULSER:N_R37_2` | CONNECTED | EXACT |
| `37` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `38` | `LE` | `PULSER:LE` | same | CONNECTED | EXACT |
| `39` | `DOUT` | `PULSER:DOUT2` | same | CONNECTED | EXACT |
| `40` | `VDD` | `PULSER:3.3V NC` | same | CONNECTED | EXACT |
| `41` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `42` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `43` | `VCC` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `44` | `DIN` | `PULSER:DOUT1` | same | CONNECTED | EXACT |
| `45` | `CLK` | `PULSER:CLK` | same | CONNECTED | EXACT |
| `46` | `SET` | `PULSER:GND` | same | CONNECTED | EXACT |
| `47` | `CLR` | `PULSER:CLR` | same | CONNECTED | EXACT |
| `48` | `GND` | `PULSER:GND` | same | CONNECTED | EXACT |
| `49` | `EP` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.U9 — 48 Pin Connector

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 23 (item 22).

Value: `not specified`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `100P-JMDSS-G-1-TF`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `pulser-schematic.epru` line 7615, component `a3a07490589d4ed8`, symbol `0d4a1a4f073031f7`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `PULSER:GND` | same | CONNECTED | NEAR |
| `2` | `2` | `PULSER:GND` | same | CONNECTED | EXACT |
| `3` | `3` | `PULSER:1NO4` | same | CONNECTED | EXACT |
| `4` | `4` | `PULSER:GND` | same | CONNECTED | EXACT |
| `5` | `5` | `PULSER:1NO5` | same | CONNECTED | NEAR |
| `6` | `6` | `PULSER:GND` | same | CONNECTED | EXACT |
| `7` | `7` | `PULSER:1NO6` | same | CONNECTED | NEAR |
| `8` | `8` | `PULSER:GND` | same | CONNECTED | EXACT |
| `9` | `9` | `PULSER:1NO7` | same | CONNECTED | NEAR |
| `10` | `10` | `PULSER:GND` | same | CONNECTED | EXACT |
| `11` | `11` | `PULSER:1NO8` | same | CONNECTED | NEAR |
| `12` | `12` | `PULSER:GND` | same | CONNECTED | EXACT |
| `13` | `13` | `PULSER:1NO9` | same | CONNECTED | NEAR |
| `14` | `14` | `PULSER:GND` | same | CONNECTED | EXACT |
| `15` | `15` | `PULSER:1NO10` | same | CONNECTED | NEAR |
| `16` | `16` | `PULSER:GND` | same | CONNECTED | EXACT |
| `17` | `17` | `PULSER:1NO11` | same | CONNECTED | NEAR |
| `18` | `18` | `PULSER:GND` | same | CONNECTED | EXACT |
| `19` | `19` | `PULSER:1NO12` | same | CONNECTED | NEAR |
| `20` | `20` | `PULSER:GND` | same | CONNECTED | EXACT |
| `21` | `21` | `PULSER:1NO13` | same | CONNECTED | NEAR |
| `22` | `22` | `PULSER:GND` | same | CONNECTED | EXACT |
| `23` | `23` | `PULSER:1NO14` | same | CONNECTED | NEAR |
| `24` | `24` | `PULSER:GND` | same | CONNECTED | EXACT |
| `25` | `25` | `PULSER:1NO15` | same | CONNECTED | NEAR |
| `26` | `26` | `PULSER:GND` | same | CONNECTED | EXACT |
| `27` | `27` | `PULSER:2NO0` | same | CONNECTED | NEAR |
| `28` | `28` | `PULSER:GND` | same | CONNECTED | EXACT |
| `29` | `29` | `PULSER:2NO1` | same | CONNECTED | NEAR |
| `30` | `30` | `PULSER:GND` | same | CONNECTED | EXACT |
| `31` | `31` | `PULSER:2NO2` | same | CONNECTED | EXACT |
| `32` | `32` | `PULSER:GND` | same | CONNECTED | EXACT |
| `33` | `33` | `PULSER:2NO3` | same | CONNECTED | NEAR |
| `34` | `34` | `PULSER:GND` | same | CONNECTED | EXACT |
| `35` | `35` | `PULSER:2NO4` | same | CONNECTED | NEAR |
| `36` | `36` | `PULSER:GND` | same | CONNECTED | EXACT |
| `37` | `37` | `PULSER:2NO5` | same | CONNECTED | NEAR |
| `38` | `38` | `PULSER:GND` | same | CONNECTED | EXACT |
| `39` | `39` | `PULSER:2NO6` | same | CONNECTED | NEAR |
| `40` | `40` | `PULSER:GND` | same | CONNECTED | EXACT |
| `41` | `41` | `PULSER:2NO7` | same | CONNECTED | NEAR |
| `42` | `42` | `PULSER:GND` | same | CONNECTED | EXACT |
| `43` | `43` | `PULSER:2NO8` | same | CONNECTED | NEAR |
| `44` | `44` | `PULSER:GND` | same | CONNECTED | EXACT |
| `45` | `45` | `PULSER:2NO9` | same | CONNECTED | NEAR |
| `46` | `46` | `PULSER:GND` | same | CONNECTED | EXACT |
| `47` | `47` | `PULSER:2NO10` | same | CONNECTED | NEAR |
| `48` | `48` | `PULSER:GND` | same | CONNECTED | EXACT |
| `49` | `49` | `PULSER:2NO11` | same | CONNECTED | NEAR |
| `50` | `50` | `PULSER:GND` | same | CONNECTED | EXACT |
| `51` | `51` | `PULSER:GND` | same | CONNECTED | NEAR |
| `52` | `52` | `PULSER:1NO3` | same | CONNECTED | EXACT |
| `53` | `53` | `PULSER:GND` | same | CONNECTED | NEAR |
| `54` | `54` | `PULSER:1NO2` | same | CONNECTED | EXACT |
| `55` | `55` | `PULSER:GND` | same | CONNECTED | EXACT |
| `56` | `56` | `PULSER:1NO1` | same | CONNECTED | EXACT |
| `57` | `57` | `PULSER:GND` | same | CONNECTED | EXACT |
| `58` | `58` | `PULSER:1NO0` | same | CONNECTED | EXACT |
| `59` | `59` | `PULSER:GND` | same | CONNECTED | EXACT |
| `60` | `60` | `PULSER:3NO15` | same | CONNECTED | NEAR |
| `61` | `61` | `PULSER:GND` | same | CONNECTED | EXACT |
| `62` | `62` | `PULSER:3NO14` | same | CONNECTED | EXACT |
| `63` | `63` | `PULSER:GND` | same | CONNECTED | EXACT |
| `64` | `64` | `PULSER:3NO13` | same | CONNECTED | EXACT |
| `65` | `65` | `PULSER:GND` | same | CONNECTED | EXACT |
| `66` | `66` | `PULSER:3NO12` | same | CONNECTED | EXACT |
| `67` | `67` | `PULSER:GND` | same | CONNECTED | EXACT |
| `68` | `68` | `PULSER:3NO11` | same | CONNECTED | EXACT |
| `69` | `69` | `PULSER:GND` | same | CONNECTED | EXACT |
| `70` | `70` | `PULSER:3NO10` | same | CONNECTED | EXACT |
| `71` | `71` | `PULSER:GND` | same | CONNECTED | EXACT |
| `72` | `72` | `PULSER:3NO9` | same | CONNECTED | EXACT |
| `73` | `73` | `PULSER:GND` | same | CONNECTED | EXACT |
| `74` | `74` | `PULSER:3NO8` | same | CONNECTED | EXACT |
| `75` | `75` | `PULSER:GND` | same | CONNECTED | EXACT |
| `76` | `76` | `PULSER:3NO7` | same | CONNECTED | EXACT |
| `77` | `77` | `PULSER:GND` | same | CONNECTED | EXACT |
| `78` | `78` | `PULSER:3NO6` | same | CONNECTED | EXACT |
| `79` | `79` | `PULSER:GND` | same | CONNECTED | EXACT |
| `80` | `80` | `PULSER:3NO5` | same | CONNECTED | EXACT |
| `81` | `81` | `PULSER:GND` | same | CONNECTED | EXACT |
| `82` | `82` | `PULSER:3NO4` | same | CONNECTED | EXACT |
| `83` | `83` | `PULSER:GND` | same | CONNECTED | EXACT |
| `84` | `84` | `PULSER:3NO3` | same | CONNECTED | EXACT |
| `85` | `85` | `PULSER:GND` | same | CONNECTED | EXACT |
| `86` | `86` | `PULSER:3NO2` | same | CONNECTED | EXACT |
| `87` | `87` | `PULSER:GND` | same | CONNECTED | EXACT |
| `88` | `88` | `PULSER:3NO1` | same | CONNECTED | EXACT |
| `89` | `89` | `PULSER:GND` | same | CONNECTED | EXACT |
| `90` | `90` | `PULSER:3NO0` | same | CONNECTED | NEAR |
| `91` | `91` | `PULSER:GND` | same | CONNECTED | EXACT |
| `92` | `92` | `PULSER:2NO15` | same | CONNECTED | EXACT |
| `93` | `93` | `PULSER:GND` | same | CONNECTED | EXACT |
| `94` | `94` | `PULSER:2NO14` | same | CONNECTED | EXACT |
| `95` | `95` | `PULSER:GND` | same | CONNECTED | EXACT |
| `96` | `96` | `PULSER:2NO13` | same | CONNECTED | EXACT |
| `97` | `97` | `PULSER:GND` | same | CONNECTED | EXACT |
| `98` | `98` | `PULSER:2NO12` | same | CONNECTED | EXACT |
| `99` | `99` | `PULSER:GND` | same | CONNECTED | EXACT |
| `100` | `100` | `PULSER:GND` | same | CONNECTED | NEAR |
| `101` | `101` | `PULSER:GND` | same | CONNECTED | EXACT |
| `102` | `102` | `PULSER:GND` | same | CONNECTED | EXACT |

#### PULSER.U11 — LG L29K-F2J1-24-0-2-R18-Z

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 24 (item 23).

Value: `not specified`. Manufacturer part: `LG L29K-F2J1-24-0-2-R18-Z`. Manufacturer: `OSRAM(欧司朗)`.

Footprint: `LED-SMD_L1.3-W0.8-LS1.7-FD`. Supplier: `LCSC`. Supplier part: `C2899882`.

Schematic source: `pulser-schematic.epru` line 9434, component `e3d32dd206d563d9`, symbol `8356150616e25125`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `A` | `PULSER:N_R67_2` | same | CONNECTED | EXACT |
| `2` | `K` | `PULSER:-5V` | same | CONNECTED | EXACT |

#### PULSER.U12 — LG L29K-F2J1-24-0-2-R18-Z

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 24 (item 23).

Value: `not specified`. Manufacturer part: `LG L29K-F2J1-24-0-2-R18-Z`. Manufacturer: `OSRAM(欧司朗)`.

Footprint: `LED-SMD_L1.3-W0.8-LS1.7-FD`. Supplier: `LCSC`. Supplier part: `C2899882`.

Schematic source: `pulser-schematic.epru` line 9444, component `dfc6511903bad834`, symbol `8356150616e25125`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `A` | `PULSER:+5V` | same | CONNECTED | EXACT |
| `2` | `K` | `PULSER:N_R68_2` | same | CONNECTED | EXACT |

#### PULSER.U13 — LG L29K-F2J1-24-0-2-R18-Z

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 24 (item 23).

Value: `not specified`. Manufacturer part: `LG L29K-F2J1-24-0-2-R18-Z`. Manufacturer: `OSRAM(欧司朗)`.

Footprint: `LED-SMD_L1.3-W0.8-LS1.7-FD`. Supplier: `LCSC`. Supplier part: `C2899882`.

Schematic source: `pulser-schematic.epru` line 14462, component `da339a4ba6daf8b8`, symbol `8356150616e25125`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `A` | `PULSER:N_R66_2` | same | CONNECTED | NEAR |
| `2` | `K` | `PULSER:GND` | same | CONNECTED | NEAR |

#### PULSER.U14 — LG L29K-F2J1-24-0-2-R18-Z

BOM: `BOM_Pulser_Schematic1_2026-09-07.xlsx`, sheet `BOM_Pulser_Schematic1_2026-09-0`, row 24 (item 23).

Value: `not specified`. Manufacturer part: `LG L29K-F2J1-24-0-2-R18-Z`. Manufacturer: `OSRAM(欧司朗)`.

Footprint: `LED-SMD_L1.3-W0.8-LS1.7-FD`. Supplier: `LCSC`. Supplier part: `C2899882`.

Schematic source: `pulser-schematic.epru` line 14499, component `2631d91f5cc9da59`, symbol `8356150616e25125`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `A` | `PULSER:GND` | same | CONNECTED | EXACT |
| `2` | `K` | `PULSER:N_R65_2` | same | CONNECTED | EXACT |

### AFE components

#### AFE.C1 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6659, component `9bc13f36b4fe6967`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C2 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 3 (item 2).

Value: `100nF`. Manufacturer part: `GRM3195C2A104GA01D`. Manufacturer: `muRata(村田)`.

Footprint: `C1206`. Supplier: `LCSC`. Supplier part: `C3906406`.

Schematic source: `afe-schematic.epru` line 7466, component `e80b75f947bb7f07`, symbol `4926c59b162759bc`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C2_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:IN1` | same | CONNECTED | EXACT |

#### AFE.C3 — 22uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 4 (item 3).

Value: `22uF`. Manufacturer part: `TPSC226K016R0375`. Manufacturer: `Kyocera AVX`.

Footprint: `CAP-SMD_L6.0-W3.2`. Supplier: `LCSC`. Supplier part: `C283238`.

Schematic source: `afe-schematic.epru` line 5365, component `9671587ccc876d26`, symbol `758c7e2511ec2067`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C3_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C4 — 22uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 4 (item 3).

Value: `22uF`. Manufacturer part: `TPSC226K016R0375`. Manufacturer: `Kyocera AVX`.

Footprint: `CAP-SMD_L6.0-W3.2`. Supplier: `LCSC`. Supplier part: `C283238`.

Schematic source: `afe-schematic.epru` line 5392, component `6d98a8190fc14986`, symbol `758c7e2511ec2067`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C4_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C5 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5419, component `698860f0975ae584`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C3_1` | same | CONNECTED | EXACT |

#### AFE.C6 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5439, component `b7e9b4b933047301`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C6_2` | same | CONNECTED | EXACT |

#### AFE.C7 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5665, component `f541fb4948357d25`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C8 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5686, component `ad3038390c824545`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C9 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5706, component `c4280be0ad5bb6c6`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C10 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5726, component `6e26ad434752f18c`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C11 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5746, component `07f7e3c05d056c02`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C12 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5766, component `43e05290223fceb9`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C13 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5800, component `f187a5f71e7cf656`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C14 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 5820, component `abcef7b7671e9c3c`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C15 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 5922, component `6fdf3ac9b7731389`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C16 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 5949, component `e32fa756f82a66bb`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C17 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 5975, component `5ef4219e2b183b89`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C18 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 6010, component `7183ae3c9da0ae69`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |

#### AFE.C19 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 6042, component `9568f2426d8da24d`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+5_VDD` | same | CONNECTED | EXACT |

#### AFE.C20 — 2.2uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 6 (item 5).

Value: `2.2uF`. Manufacturer part: `GRM155Z71A225KE44D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C2999759`.

Schematic source: `afe-schematic.epru` line 8110, component `db3abad2ba459d08`, symbol `d48250001382645a`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:VB1` | same | CONNECTED | EXACT |

#### AFE.C21 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8156, component `272bfbb040782b5b`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:VCM` | same | CONNECTED | EXACT |

#### AFE.C22 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 7438, component `f09d38e2fe899d02`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C23 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 7532, component `25b05fec4f2779ab`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C24 — 1uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 7 (item 6).

Value: `1uF`. Manufacturer part: `GRM155Z71A105KE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C528974`.

Schematic source: `afe-schematic.epru` line 7552, component `1e5d17244a6cae71`, symbol `0b2bd054bc5f98fe`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C25 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8212, component `835ab206fdeeda1d`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C26 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8237, component `8f61b98fbe5c1128`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:1.2V VREF` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C27 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6683, component `0ef99e8ca03a90ea`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL2` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C28 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6707, component `9ae25067d64fce1d`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL3` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C29 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6731, component `d279bf2dc8e3e7f6`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL4` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C30 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6755, component `ff6c1588a43d63ba`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL8` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C31 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6779, component `7aacab10aa947ebd`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL7` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C32 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6803, component `fd979255fad579fd`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL6` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C33 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 6827, component `6e8d9cdd308b3d20`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VBL5` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C34 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 7131, component `5407ca5806965e03`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VB2` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C35 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 7152, component `c44ef5ffd095056b`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:VB3` | same | CONNECTED | EXACT |

#### AFE.C36 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 7172, component `bf640dac7edc04e1`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VB4` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C37 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 7192, component `47fd62b12b6f038b`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:VB5` | same | CONNECTED | EXACT |

#### AFE.C38 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8276, component `7aeba686c23a92d6`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C38_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C39 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 7213, component `6f77426f2dfc6c58`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:VB6` | same | CONNECTED | EXACT |

#### AFE.C40 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8400, component `bdf939158f152617`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C41 — 1uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 7 (item 6).

Value: `1uF`. Manufacturer part: `GRM155Z71A105KE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C528974`.

Schematic source: `afe-schematic.epru` line 8421, component `651c16e07ccf8309`, symbol `0b2bd054bc5f98fe`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C42 — 470pF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 8 (item 7).

Value: `470pF`. Manufacturer part: `GRM1555C1H471JA01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C76971`.

Schematic source: `afe-schematic.epru` line 8476, component `2714d8ea6c773359`, symbol `75edc728d54d2c66`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VCNTL` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C43 — 1uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 7 (item 6).

Value: `1uF`. Manufacturer part: `GRM155Z71A105KE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C528974`.

Schematic source: `afe-schematic.epru` line 8487, component `47a307639bae102b`, symbol `0b2bd054bc5f98fe`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:1.2V VREF` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C44 — 2.2uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 6 (item 5).

Value: `2.2uF`. Manufacturer part: `GRM155Z71A225KE44D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C2999759`.

Schematic source: `afe-schematic.epru` line 8830, component `a5564c76925deedb`, symbol `d48250001382645a`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:REFB` | same | CONNECTED | EXACT |

#### AFE.C45 — 2.2uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 6 (item 5).

Value: `2.2uF`. Manufacturer part: `GRM155Z71A225KE44D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C2999759`.

Schematic source: `afe-schematic.epru` line 8901, component `8ebc3f7e862cfbb2`, symbol `d48250001382645a`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:REFT` | same | CONNECTED | EXACT |

#### AFE.C46 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8911, component `6c3a8b7df3cf17b6`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:REFT` | same | CONNECTED | EXACT |

#### AFE.C47 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4627, component `e7460`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |

#### AFE.C48 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4638, component `e7505`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |

#### AFE.C49 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4648, component `e7541`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |

#### AFE.C50 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8947, component `6101a236cf929333`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:VREFH` | same | CONNECTED | EXACT |

#### AFE.C51 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8967, component `f9b6a0602afaad2a`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:VREFL` | same | CONNECTED | EXACT |

#### AFE.C52 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 9044, component `88d7f6e6d4dd4513`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:CM` | same | CONNECTED | EXACT |

#### AFE.C53 — 10nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 9 (item 8).

Value: `10nF`. Manufacturer part: `GRM1555C1E103GE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C3872300`.

Schematic source: `afe-schematic.epru` line 9116, component `36d7bd37401d3698`, symbol `41c4b2240d8fa40d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:CLKP` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C53_2` | same | CONNECTED | EXACT |

#### AFE.C54 — 47uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 10 (item 9).

Value: `47uF`. Manufacturer part: `35SVPK47M`. Manufacturer: `PANASONIC(松下)`.

Footprint: `CAP-SMD_BD6.3-L6.6-W6.6-FD`. Supplier: `LCSC`. Supplier part: `C264034`.

Schematic source: `afe-schematic.epru` line 9372, component `8617591b89a6fedb`, symbol `1ca39529faa8a87e`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C55 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4658, component `e7789`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+5_VDD` | same | CONNECTED | EXACT |

#### AFE.C56 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4669, component `e7823`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C57 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4679, component `e7859`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C58 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4689, component `e7895`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C59 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4699, component `e7931`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C60 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4709, component `e7967`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C61 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4719, component `e8003`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C62 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 4729, component `e8037`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |

#### AFE.C63 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 8840, component `77fd12a8c7bc9431`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:REFB` | same | CONNECTED | EXACT |

#### AFE.C64 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 4739, component `e8139`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+5_VDD` | same | CONNECTED | EXACT |

#### AFE.C65 — 10uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 5 (item 4).

Value: `10uF`. Manufacturer part: `CL21B106KOQNNNE`. Manufacturer: `SAMSUNG(三星)`.

Footprint: `C0805`. Supplier: `LCSC`. Supplier part: `C95841`.

Schematic source: `afe-schematic.epru` line 4750, component `e8173`, symbol `e1610870497f6ebb`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.C66 — 10nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 9 (item 8).

Value: `10nF`. Manufacturer part: `GRM1555C1E103GE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C3872300`.

Schematic source: `afe-schematic.epru` line 9106, component `b0abc4767a53809b`, symbol `41c4b2240d8fa40d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:CLKM` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C66_2` | same | CONNECTED | EXACT |

#### AFE.C67 — 22uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 11 (item 10).

Value: `22uF`. Manufacturer part: `HV1H226M0605PZ`. Manufacturer: `HONOR(荣誉)`.

Footprint: `CAP-SMD_BD6.3-L6.6-W6.6-LS7.2-R-RD-1`. Supplier: `LCSC`. Supplier part: `C5246560`.

Schematic source: `afe-schematic.epru` line 9382, component `4bb7f67c7319cf84`, symbol `bb98abe4e089eada`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C67_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C68 — 1uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 7 (item 6).

Value: `1uF`. Manufacturer part: `GRM155Z71A105KE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C528974`.

Schematic source: `afe-schematic.epru` line 9392, component `f2d4761c0ca0162e`, symbol `0b2bd054bc5f98fe`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:5V-USB` | same | CONNECTED | EXACT |

#### AFE.C69 — 10nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 9 (item 8).

Value: `10nF`. Manufacturer part: `GRM1555C1E103GE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C3872300`.

Schematic source: `afe-schematic.epru` line 9418, component `925681cf176d0074`, symbol `41c4b2240d8fa40d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+5_VDD` | same | CONNECTED | EXACT |

#### AFE.C70 — 22uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 4 (item 3).

Value: `22uF`. Manufacturer part: `TPSC226K016R0375`. Manufacturer: `Kyocera AVX`.

Footprint: `CAP-SMD_L6.0-W3.2`. Supplier: `LCSC`. Supplier part: `C283238`.

Schematic source: `afe-schematic.epru` line 4794, component `e8744`, symbol `758c7e2511ec2067`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C70_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C71 — 22uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 4 (item 3).

Value: `22uF`. Manufacturer part: `TPSC226K016R0375`. Manufacturer: `Kyocera AVX`.

Footprint: `CAP-SMD_L6.0-W3.2`. Supplier: `LCSC`. Supplier part: `C283238`.

Schematic source: `afe-schematic.epru` line 4803, component `e8779`, symbol `758c7e2511ec2067`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C71_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.C72 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4812, component `e8814`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C70_1` | same | CONNECTED | EXACT |

#### AFE.C73 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 4822, component `e8848`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C73_2` | same | CONNECTED | EXACT |

#### AFE.C74 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 9428, component `edfdc2fc62cfc3bc`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C67_1` | same | CONNECTED | EXACT |

#### AFE.C75 — 100nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 2 (item 1).

Value: `100nF`. Manufacturer part: `CC0402KRX7R7BB104`. Manufacturer: `YAGEO(国巨)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C60474`.

Schematic source: `afe-schematic.epru` line 9448, component `4b51794ba83d6e57`, symbol `a0bdc10da1095b7c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C67_1` | same | CONNECTED | EXACT |

#### AFE.C76 — 1uF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 7 (item 6).

Value: `1uF`. Manufacturer part: `GRM155Z71A105KE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C528974`.

Schematic source: `afe-schematic.epru` line 9468, component `bcdf7f82f465dfc8`, symbol `0b2bd054bc5f98fe`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C67_1` | same | CONNECTED | EXACT |

#### AFE.C77 — 10nF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 9 (item 8).

Value: `10nF`. Manufacturer part: `GRM1555C1E103GE01D`. Manufacturer: `muRata(村田)`.

Footprint: `C0402`. Supplier: `LCSC`. Supplier part: `C3872300`.

Schematic source: `afe-schematic.epru` line 9494, component `d62f6688af7ec266`, symbol `41c4b2240d8fa40d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+5_VDD` | same | CONNECTED | EXACT |

#### AFE.CN1 — 321020MG0CBK00A01

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 12 (item 11).

Value: `not specified`. Manufacturer part: `321020MG0CBK00A01`. Manufacturer: `JILN(锦凌)`.

Footprint: `CONN-SMD_321020MG0CBK00A0`. Supplier: `LCSC`. Supplier part: `C601970`.

Schematic source: `afe-schematic.epru` line 9920, component `f1139830714f8b18`, symbol `bd8036b8d00fbd7e`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:51` | same | CONNECTED | EXACT |
| `3` | `3` | `AFE:33` | same | CONNECTED | EXACT |
| `4` | `4` | `AFE:53` | same | CONNECTED | EXACT |
| `5` | `5` | `AFE:GND` | same | CONNECTED | EXACT |
| `6` | `6` | `AFE:57` | same | CONNECTED | EXACT |
| `7` | `7` | `AFE:35` | same | CONNECTED | EXACT |
| `8` | `8` | `AFE:GND` | same | CONNECTED | EXACT |
| `9` | `9` | `AFE:GND` | same | CONNECTED | EXACT |
| `10` | `10` | `AFE:59` | same | CONNECTED | EXACT |
| `11` | `11` | `AFE:39` | same | CONNECTED | EXACT |
| `12` | `12` | `AFE:GND` | same | CONNECTED | EXACT |
| `13` | `13` | `AFE:GND` | same | CONNECTED | EXACT |
| `14` | `14` | `AFE:63` | same | CONNECTED | EXACT |
| `15` | `15` | — | same | UNCONNECTED | NONE |
| `16` | `16` | `AFE:65` | same | CONNECTED | EXACT |
| `17` | `17` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `18` | `18` | `AFE:GND` | same | CONNECTED | EXACT |
| `19` | `19` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |
| `20` | `20` | `AFE:+5_VDD` | same | CONNECTED | EXACT |

#### AFE.CN2 — DF40C-50DP-0.4V(51)

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 13 (item 12).

Value: `not specified`. Manufacturer part: `DF40C-50DP-0.4V(51)`. Manufacturer: `HRS(广濑)`.

Footprint: `CONN-SMD_DF40C-50DP-0.4V`. Supplier: `LCSC`. Supplier part: `C424645`.

Schematic source: `afe-schematic.epru` line 7394, component `bf7c0d114cc0009e`, symbol `da7d3fdbc6b73860`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | — | same | UNCONNECTED | NONE |
| `2` | `2` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `3` | `3` | — | same | UNCONNECTED | NONE |
| `4` | `4` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `5` | `5` | — | same | UNCONNECTED | NONE |
| `6` | `6` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `7` | `7` | — | same | UNCONNECTED | NONE |
| `8` | `8` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `9` | `9` | — | same | UNCONNECTED | NONE |
| `10` | `10` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `11` | `11` | — | same | UNCONNECTED | NONE |
| `12` | `12` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `13` | `13` | — | same | UNCONNECTED | NONE |
| `14` | `14` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `15` | `15` | — | same | UNCONNECTED | NONE |
| `16` | `16` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `17` | `17` | `AFE:GND` | same | CONNECTED | EXACT |
| `18` | `18` | `AFE:GND` | same | CONNECTED | EXACT |
| `19` | `19` | `AFE:GND` | same | CONNECTED | EXACT |
| `20` | `20` | `AFE:GND` | same | CONNECTED | EXACT |
| `21` | `21` | `AFE:GND` | same | CONNECTED | EXACT |
| `22` | `22` | `AFE:GND` | same | CONNECTED | EXACT |
| `23` | `23` | `AFE:GND` | same | CONNECTED | EXACT |
| `24` | `24` | `AFE:GND` | same | CONNECTED | EXACT |
| `25` | `25` | `AFE:GND` | same | CONNECTED | EXACT |
| `26` | `26` | `AFE:GND` | same | CONNECTED | EXACT |
| `27` | `27` | `AFE:GND` | same | CONNECTED | EXACT |
| `28` | `28` | `AFE:GND` | same | CONNECTED | EXACT |
| `29` | `29` | — | same | UNCONNECTED | NONE |
| `30` | `30` | — | same | UNCONNECTED | NONE |
| `31` | `31` | — | same | UNCONNECTED | NONE |
| `32` | `32` | — | same | UNCONNECTED | NONE |
| `33` | `33` | — | same | UNCONNECTED | NONE |
| `34` | `34` | — | same | UNCONNECTED | NONE |
| `35` | `35` | — | same | UNCONNECTED | NONE |
| `36` | `36` | — | same | UNCONNECTED | NONE |
| `37` | `37` | — | same | UNCONNECTED | NONE |
| `38` | `38` | `AFE:GND` | same | CONNECTED | EXACT |
| `39` | `39` | — | same | UNCONNECTED | NONE |
| `40` | `40` | `AFE:GND` | same | CONNECTED | EXACT |
| `41` | `41` | — | same | UNCONNECTED | NONE |
| `42` | `42` | — | same | UNCONNECTED | NONE |
| `43` | `43` | — | same | UNCONNECTED | NONE |
| `44` | `44` | — | same | UNCONNECTED | NONE |
| `45` | `45` | — | same | UNCONNECTED | NONE |
| `46` | `46` | — | same | UNCONNECTED | NONE |
| `47` | `47` | — | same | UNCONNECTED | NONE |
| `48` | `48` | — | same | UNCONNECTED | NONE |
| `49` | `49` | — | same | UNCONNECTED | NONE |
| `50` | `50` | — | same | UNCONNECTED | NONE |
| `51` | `51` | `AFE:GND` | same | CONNECTED | EXACT |
| `52` | `52` | `AFE:GND` | same | CONNECTED | EXACT |
| `53` | `53` | `AFE:GND` | same | CONNECTED | EXACT |
| `54` | `54` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.D1 — BAV99HMT116

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 14 (item 13).

Value: `not specified`. Manufacturer part: `BAV99HMT116`. Manufacturer: `ROHM(罗姆)`.

Footprint: `SOT-23-3_L3.0-W1.7-P0.95-LS2.9-BR`. Supplier: `LCSC`. Supplier part: `C253174`.

Schematic source: `afe-schematic.epru` line 9297, component `8ba05c32165ef9d9`, symbol `fd10e83fed4963ed`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `A` | `AFE:N_C2_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C2_1` | same | CONNECTED | EXACT |
| `3` | `K` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.L1 — BLM21AG601SH1D

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 15 (item 14).

Value: `not specified`. Manufacturer part: `BLM21AG601SH1D`. Manufacturer: `muRata(村田)`.

Footprint: `L0805`. Supplier: `LCSC`. Supplier part: `C437406`.

Schematic source: `afe-schematic.epru` line 5309, component `249f3bac9e6ba6a5`, symbol `bb1ac188317c8317`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:+5_VDD` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C3_1` | same | CONNECTED | EXACT |

#### AFE.L2 — BLM21AG601SH1D

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 15 (item 14).

Value: `not specified`. Manufacturer part: `BLM21AG601SH1D`. Manufacturer: `muRata(村田)`.

Footprint: `L0805`. Supplier: `LCSC`. Supplier part: `C437406`.

Schematic source: `afe-schematic.epru` line 5337, component `861df291faec48e6`, symbol `bb1ac188317c8317`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C4_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.L3 — 4.7uH

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 16 (item 15).

Value: `4.7uH`. Manufacturer part: `LVS303012-4R7M-N`. Manufacturer: `Chilisin(奇力新)`.

Footprint: `IND-SMD_L3.0-W3.0_LQH3NPN2R2NG0L`. Supplier: `LCSC`. Supplier part: `C329597`.

Schematic source: `afe-schematic.epru` line 9601, component `7da1bed09b3292b1`, symbol `48b81541ee80a1a9`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:5V-USB` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C67_1` | same | CONNECTED | EXACT |

#### AFE.L7 — BLM21AG601SH1D

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 15 (item 14).

Value: `not specified`. Manufacturer part: `BLM21AG601SH1D`. Manufacturer: `muRata(村田)`.

Footprint: `L0805`. Supplier: `LCSC`. Supplier part: `C437406`.

Schematic source: `afe-schematic.epru` line 4616, component `e6781`, symbol `bb1ac188317c8317`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C67_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+5_VDD` | same | CONNECTED | EXACT |

#### AFE.L10 — BLM21AG601SH1D

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 15 (item 14).

Value: `not specified`. Manufacturer part: `BLM21AG601SH1D`. Manufacturer: `muRata(村田)`.

Footprint: `L0805`. Supplier: `LCSC`. Supplier part: `C437406`.

Schematic source: `afe-schematic.epru` line 4773, component `e8672`, symbol `bb1ac188317c8317`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:+5_VDD` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C70_1` | same | CONNECTED | EXACT |

#### AFE.L11 — BLM21AG601SH1D

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 15 (item 14).

Value: `not specified`. Manufacturer part: `BLM21AG601SH1D`. Manufacturer: `muRata(村田)`.

Footprint: `L0805`. Supplier: `LCSC`. Supplier part: `C437406`.

Schematic source: `afe-schematic.epru` line 4784, component `e8708`, symbol `bb1ac188317c8317`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_C71_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |

#### AFE.R1 — 33Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 17 (item 16).

Value: `33Ω`. Manufacturer part: `RC0201JR-0733RL`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C142009`.

Schematic source: `afe-schematic.epru` line 8078, component `7bc8a7c2aedd151c`, symbol `7ad6a6b1ad6bb270`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:SCLK` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_R1_2` | same | CONNECTED | EXACT |

#### AFE.R2 — 100Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 18 (item 17).

Value: `100Ω`. Manufacturer part: `ERA2AEB101X`. Manufacturer: `PANASONIC(松下)`.

Footprint: `R0402`. Supplier: `LCSC`. Supplier part: `C445575`.

Schematic source: `afe-schematic.epru` line 7636, component `333dfdec54487606`, symbol `6f6e8a08d9099e75`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:CLKM` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:CLKP` | same | CONNECTED | EXACT |

#### AFE.R4 — 100Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 19 (item 18).

Value: `100Ω`. Manufacturer part: `ERA1AEB101C`. Manufacturer: `PANASONIC(松下)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C490806`.

Schematic source: `afe-schematic.epru` line 9346, component `9ba296e15199dd73`, symbol `dae7dc78a58ecce7`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:LCLKP` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:LCLKM` | same | CONNECTED | EXACT |

#### AFE.R5 — 33Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 17 (item 16).

Value: `33Ω`. Manufacturer part: `RC0201JR-0733RL`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C142009`.

Schematic source: `afe-schematic.epru` line 8089, component `51bb0973c9802d64`, symbol `7ad6a6b1ad6bb270`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:SDATA` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_R5_2` | same | CONNECTED | EXACT |

#### AFE.R6 — 33Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 20 (item 19).

Value: `33Ω`. Manufacturer part: `HP122WF330JT4E`. Manufacturer: `UNI-ROYAL(厚声)`.

Footprint: `R2512`. Supplier: `LCSC`. Supplier part: `C2758887`.

Schematic source: `afe-schematic.epru` line 9314, component `c6a93e6055baf073`, symbol `33b8319e74adfb3d`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_R6_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_C2_1` | same | CONNECTED | EXACT |

#### AFE.R7 — 10kΩ

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 21 (item 20).

Value: `10kΩ`. Manufacturer part: `ERJ1GNF1002C`. Manufacturer: `PANASONIC(松下)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C717002`.

Schematic source: `afe-schematic.epru` line 8681, component `f7b1aa1f024c39c1`, symbol `fe190506867ca773`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:DAC_SYNC` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.R8 — 10kΩ

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 22 (item 21).

Value: `10kΩ`. Manufacturer part: `ERJ2RKF1002X`. Manufacturer: `PANASONIC(松下)`.

Footprint: `R0402`. Supplier: `LCSC`. Supplier part: `C191123`.

Schematic source: `afe-schematic.epru` line 8564, component `3c2d1bfc24ea0e23`, symbol `055f02e0ef66f6ec`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:+3.3_VDD` | same | CONNECTED | NEAR |
| `2` | `2` | `AFE:CS` | same | CONNECTED | EXACT |

#### AFE.R9 — 33Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 17 (item 16).

Value: `33Ω`. Manufacturer part: `RC0201JR-0733RL`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C142009`.

Schematic source: `afe-schematic.epru` line 8622, component `ece80704bf4b1e11`, symbol `7ad6a6b1ad6bb270`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:DAC_SYNC` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_R9_2` | same | CONNECTED | EXACT |

#### AFE.R10 — 33Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 17 (item 16).

Value: `33Ω`. Manufacturer part: `RC0201JR-0733RL`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C142009`.

Schematic source: `afe-schematic.epru` line 8632, component `0c4dfea2fa42a427`, symbol `7ad6a6b1ad6bb270`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_R10_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:DAC_SCLK` | same | CONNECTED | EXACT |

#### AFE.R11 — 33Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 17 (item 16).

Value: `33Ω`. Manufacturer part: `RC0201JR-0733RL`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C142009`.

Schematic source: `afe-schematic.epru` line 8642, component `0dd936008a85abe7`, symbol `7ad6a6b1ad6bb270`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:N_R11_1` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:DAC_SDA` | same | CONNECTED | EXACT |

#### AFE.R12 — 10kΩ

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 22 (item 21).

Value: `10kΩ`. Manufacturer part: `ERJ2RKF1002X`. Manufacturer: `PANASONIC(松下)`.

Footprint: `R0402`. Supplier: `LCSC`. Supplier part: `C191123`.

Schematic source: `afe-schematic.epru` line 9127, component `4a17349a804f0610`, symbol `055f02e0ef66f6ec`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:ADS_RST` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |

#### AFE.R13 — 50Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 23 (item 22).

Value: `50Ω`. Manufacturer part: `RT0603BRE0750RL`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0603`. Supplier: `LCSC`. Supplier part: `C849792`.

Schematic source: `afe-schematic.epru` line 9155, component `2d20f5ed63ce712c`, symbol `a0dffe57b1b3820b`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_R6_1` | same | CONNECTED | EXACT |

#### AFE.R14 — 100Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 19 (item 18).

Value: `100Ω`. Manufacturer part: `ERA1AEB101C`. Manufacturer: `PANASONIC(松下)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C490806`.

Schematic source: `afe-schematic.epru` line 9359, component `1c98471594aa4d79`, symbol `dae7dc78a58ecce7`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:FCLKP` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:FCLKM` | same | CONNECTED | EXACT |

#### AFE.R15 — 56kΩ

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 24 (item 23).

Value: `56kΩ`. Manufacturer part: `PTFR0603B56K0N9`. Manufacturer: `RESI(开步睿思)`.

Footprint: `R0603`. Supplier: `LCSC`. Supplier part: `C2692810`.

Schematic source: `afe-schematic.epru` line 9688, component `b72eabb624048852`, symbol `2683488d09fb8d32`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_R15_2` | same | CONNECTED | EXACT |

#### AFE.R16 — 200Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 25 (item 24).

Value: `200Ω`. Manufacturer part: `RC0402FR-07200RL`. Manufacturer: `YAGEO(国巨)`.

Footprint: `R0402`. Supplier: `LCSC`. Supplier part: `C114764`.

Schematic source: `afe-schematic.epru` line 9286, component `52da64e9e3d51691`, symbol `5a17f4bd79a5d3c1`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:VCNTL` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:N_R16_2` | same | CONNECTED | EXACT |

#### AFE.R17 — 100Ω

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 19 (item 18).

Value: `100Ω`. Manufacturer part: `ERA1AEB101C`. Manufacturer: `PANASONIC(松下)`.

Footprint: `R0201`. Supplier: `LCSC`. Supplier part: `C490806`.

Schematic source: `afe-schematic.epru` line 9336, component `5a674fda86363994`, symbol `dae7dc78a58ecce7`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:OUT1P` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:OUT1M` | same | CONNECTED | EXACT |

#### AFE.RF1 — 3GHz

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 26 (item 25).

Value: `3GHz`. Manufacturer part: `SMA-KE-347-H13.5-1.6`. Manufacturer: `XUNPU(讯普)`.

Footprint: `SMA-SMD_SMA-KE-347-H13.5-1.6`. Supplier: `LCSC`. Supplier part: `C5723200`.

Schematic source: `afe-schematic.epru` line 6912, component `4d97bc0d962f2c05`, symbol `488a4ac232739c05`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `2` | `AFE:GND` | same | CONNECTED | EXACT |
| `3` | `3` | `AFE:GND` | same | CONNECTED | EXACT |
| `4` | `4` | `AFE:GND` | same | CONNECTED | EXACT |
| `5` | `5` | `AFE:N_R6_1` | same | CONNECTED | EXACT |

#### AFE.U1 — AFE5804ZCF

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 27 (item 26).

Value: `not specified`. Manufacturer part: `AFE5804ZCF`. Manufacturer: `TI(德州仪器)`.

Footprint: `BGA-135_L15.0-W9.0-R15-C9-P1.00-BL`. Supplier: `LCSC`. Supplier part: `C1520726`.

Schematic source: `afe-schematic.epru` line 5121, component `0abb5abc1205405c`, symbol `2177723e297a826c`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `A1` | `IN1` | `AFE:IN1` | same | CONNECTED | EXACT |
| `A2` | `IN2` | — | same | UNCONNECTED | NONE |
| `A3` | `IN3` | — | same | UNCONNECTED | NONE |
| `A4` | `IN4` | — | same | UNCONNECTED | NONE |
| `A5` | `VCA_PD` | `AFE:GND` | same | CONNECTED | EXACT |
| `A6` | `IN8` | — | same | UNCONNECTED | NONE |
| `A7` | `IN7` | — | same | UNCONNECTED | NONE |
| `A8` | `IN6` | — | same | UNCONNECTED | NONE |
| `A9` | `IN5` | — | same | UNCONNECTED | NONE |
| `B1` | `VBL1` | `AFE:VBL1` | same | CONNECTED | EXACT |
| `B2` | `VBL2` | `AFE:VBL2` | same | CONNECTED | EXACT |
| `B3` | `VBL3` | `AFE:VBL3` | same | CONNECTED | EXACT |
| `B4` | `VBL4` | `AFE:VBL4` | same | CONNECTED | EXACT |
| `B5` | `DNC` | — | same | UNCONNECTED | NONE |
| `B6` | `VBL8` | `AFE:VBL8` | same | CONNECTED | EXACT |
| `B7` | `VBL7` | `AFE:VBL7` | same | CONNECTED | EXACT |
| `B8` | `VBL6` | `AFE:VBL6` | same | CONNECTED | EXACT |
| `B9` | `VBL5` | `AFE:VBL5` | same | CONNECTED | EXACT |
| `C1` | `CW9` | — | same | UNCONNECTED | NONE |
| `C2` | `AVDD2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `C3` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `C4` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `C5` | `DVDD` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `C6` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `C7` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `C8` | `AVDD2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `C9` | `CW0` | — | same | UNCONNECTED | NONE |
| `D1` | `CW8` | — | same | UNCONNECTED | NONE |
| `D2` | `VCNTL` | `AFE:VCNTL` | same | CONNECTED | EXACT |
| `D3` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `D4` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `D5` | `DVDD` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `D6` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `D7` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `D8` | `VB2` | `AFE:VB2` | same | CONNECTED | EXACT |
| `D9` | `CW1` | — | same | UNCONNECTED | NONE |
| `E1` | `CW7` | — | same | UNCONNECTED | NONE |
| `E2` | `AVDD_5V` | `AFE:+5_VDD` | same | CONNECTED | EXACT |
| `E3` | `VB3` | `AFE:VB3` | same | CONNECTED | NEAR |
| `E4` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `E5` | `AVSS2` | `AFE:GND` | same | CONNECTED | NEAR |
| `E6` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `E7` | `VB4` | `AFE:VB4` | same | CONNECTED | NEAR |
| `E8` | `AVDD_5V` | `AFE:+5_VDD` | same | CONNECTED | NEAR |
| `E9` | `CW2` | — | same | UNCONNECTED | NONE |
| `F1` | `CW6` | — | same | UNCONNECTED | NONE |
| `F2` | `VB1` | `AFE:VB1` | same | CONNECTED | NEAR |
| `F3` | `VB5` | `AFE:VB5` | same | CONNECTED | EXACT |
| `F4` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `F5` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `F6` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `F7` | `VREFH` | `AFE:VREFH` | same | CONNECTED | EXACT |
| `F8` | `VB6` | `AFE:VB6` | same | CONNECTED | EXACT |
| `F9` | `CW3` | — | same | UNCONNECTED | NONE |
| `G1` | `CW5` | — | same | UNCONNECTED | NONE |
| `G2` | `AVDD2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `G3` | `VCM` | `AFE:VCM` | same | CONNECTED | EXACT |
| `G4` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `G5` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `G6` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `G7` | `VREFL` | `AFE:VREFL` | same | CONNECTED | EXACT |
| `G8` | `AVDD2` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `G9` | `CW4` | — | same | UNCONNECTED | NONE |
| `H1` | `ADS_PD` | `AFE:GND` | same | CONNECTED | EXACT |
| `H2` | `DNC` | — | same | UNCONNECTED | NONE |
| `H3` | `DNC` | — | same | UNCONNECTED | NONE |
| `H4` | `VCA_CS` | `AFE:RST` | same | CONNECTED | EXACT |
| `H5` | `RST` | `AFE:RST` | same | CONNECTED | EXACT |
| `H6` | `SCLK` | `AFE:SCLK` | same | CONNECTED | EXACT |
| `H7` | `CS#` | `AFE:CS` | same | CONNECTED | EXACT |
| `H8` | `SDATA` | `AFE:SDATA` | same | CONNECTED | EXACT |
| `H9` | `ADS_RESET#` | `AFE:ADS_RST` | same | CONNECTED | EXACT |
| `J1` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `J2` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `J3` | `INT/EXT#` | — | same | UNCONNECTED | NONE |
| `J4` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `J5` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `J6` | `AVSS2` | `AFE:GND` | same | CONNECTED | EXACT |
| `J7` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `J8` | `REFT` | `AFE:REFT` | same | CONNECTED | EXACT |
| `J9` | `REFB` | `AFE:REFB` | same | CONNECTED | EXACT |
| `K1` | `CLKM` | `AFE:CLKM` | same | CONNECTED | EXACT |
| `K2` | `DNC` | — | same | UNCONNECTED | NONE |
| `K3` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `K4` | `DNC` | — | same | UNCONNECTED | NONE |
| `K5` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `K6` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `K7` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `K8` | `CM` | `AFE:CM` | same | CONNECTED | EXACT |
| `K9` | `ISET` | `AFE:N_R15_2` | same | CONNECTED | EXACT |
| `L1` | `CLKP` | `AFE:CLKP` | same | CONNECTED | EXACT |
| `L2` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `L3` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `L4` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `L5` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `L6` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `L7` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `L8` | `AVDD1` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `L9` | `EN_SM` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `M1` | `DNC` | — | same | UNCONNECTED | NONE |
| `M2` | `DNC` | — | same | UNCONNECTED | NONE |
| `M3` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `M4` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `M5` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `M6` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `M7` | `AVSS1` | `AFE:GND` | same | CONNECTED | EXACT |
| `M8` | `DNC` | — | same | UNCONNECTED | NONE |
| `M9` | `DNC` | — | same | UNCONNECTED | NONE |
| `N1` | `LCLKP` | `AFE:LCLKP` | same | CONNECTED | EXACT |
| `N2` | `LCLKM` | `AFE:LCLKM` | same | CONNECTED | EXACT |
| `N3` | `LVSS` | `AFE:GND` | same | CONNECTED | EXACT |
| `N4` | `LVSS` | `AFE:GND` | same | CONNECTED | NEAR |
| `N5` | `LVSS` | `AFE:GND` | same | CONNECTED | EXACT |
| `N6` | `LVDD` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |
| `N7` | `LVDD` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |
| `N8` | `FCLKM` | `AFE:FCLKM` | same | CONNECTED | EXACT |
| `N9` | `FCLKP` | `AFE:FCLKP` | same | CONNECTED | EXACT |
| `P1` | `OUT4P` | — | same | UNCONNECTED | NONE |
| `P2` | `OUT3P` | — | same | UNCONNECTED | NONE |
| `P3` | `OUT2P` | — | same | UNCONNECTED | NONE |
| `P4` | `OUT1P` | `AFE:OUT1P` | same | CONNECTED | NEAR |
| `P5` | `LVDD` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |
| `P6` | `OUT5P` | — | same | UNCONNECTED | NONE |
| `P7` | `OUT6P` | — | same | UNCONNECTED | NONE |
| `P8` | `OUT7P` | — | same | UNCONNECTED | NONE |
| `P9` | `OUT8P` | — | same | UNCONNECTED | NONE |
| `R1` | `OUT4M` | — | same | UNCONNECTED | NONE |
| `R2` | `OUT3M` | — | same | UNCONNECTED | NONE |
| `R3` | `OUT2M` | — | same | UNCONNECTED | NONE |
| `R4` | `OUT1M` | `AFE:OUT1M` | same | CONNECTED | EXACT |
| `R5` | `LVSS` | `AFE:GND` | same | CONNECTED | EXACT |
| `R6` | `OUT5M` | — | same | UNCONNECTED | NONE |
| `R7` | `OUT6M` | — | same | UNCONNECTED | NONE |
| `R8` | `OUT7M` | — | same | UNCONNECTED | NONE |
| `R9` | `OUT8M` | — | same | UNCONNECTED | NONE |

#### AFE.U2 — TPS79633DCQR

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 28 (item 27).

Value: `not specified`. Manufacturer part: `TPS79633DCQR`. Manufacturer: `TI(德州仪器)`.

Footprint: `SOT-223-6_L6.5-W3.5-P1.27-BL`. Supplier: `LCSC`. Supplier part: `C485803`.

Schematic source: `afe-schematic.epru` line 5275, component `96016b88124ef30a`, symbol `ec4be7be36d10577`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `EN` | `AFE:N_C3_1` | same | CONNECTED | EXACT |
| `2` | `IN` | `AFE:N_C3_1` | same | CONNECTED | EXACT |
| `3` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |
| `4` | `OUT` | `AFE:N_C4_1` | same | CONNECTED | EXACT |
| `5` | `NR/FB` | `AFE:N_C6_2` | same | CONNECTED | EXACT |
| `6` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.U3 — DAC7554IDGSR

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 29 (item 28).

Value: `not specified`. Manufacturer part: `DAC7554IDGSR`. Manufacturer: `TI(德州仪器)`.

Footprint: `MSOP-10_L3.0-W3.0-P0.50-LS5.0-BL`. Supplier: `LCSC`. Supplier part: `C97255`.

Schematic source: `afe-schematic.epru` line 8340, component `9fc2f0cac367b9ba`, symbol `3dbb5f916cbf388a`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `VouτA` | — | same | UNCONNECTED | NONE |
| `2` | `VouτB` | `AFE:N_R16_2` | same | CONNECTED | EXACT |
| `3` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |
| `4` | `VouτC` | — | same | UNCONNECTED | NONE |
| `5` | `VouτD` | — | same | UNCONNECTED | NONE |
| `6` | `SCLK` | `AFE:DAC_SCLK` | same | CONNECTED | EXACT |
| `7` | `DIN` | `AFE:DAC_SDA` | same | CONNECTED | EXACT |
| `8` | `VDD` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `9` | `SYNC#` | `AFE:DAC_SYNC` | same | CONNECTED | EXACT |
| `10` | `REFIN` | `AFE:1.2V VREF` | same | CONNECTED | EXACT |

#### AFE.U4 — REF35120QDBVR

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 30 (item 29).

Value: `not specified`. Manufacturer part: `REF35120QDBVR`. Manufacturer: `TI(德州仪器)`.

Footprint: `SOT-23-6_L2.9-W1.6-P0.95-LS2.8-BR`. Supplier: `LCSC`. Supplier part: `C5722646`.

Schematic source: `afe-schematic.epru` line 8185, component `d7917528c59514f6`, symbol `b547e935e8f5c408`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |
| `2` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |
| `3` | `EN` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |
| `4` | `VIN` | `AFE:+1.8_LVDD` | same | CONNECTED | EXACT |
| `5` | `NR` | `AFE:N_C38_1` | same | CONNECTED | EXACT |
| `6` | `VREF` | `AFE:1.2V VREF` | same | CONNECTED | EXACT |

#### AFE.U5 — HC-PBB40C-80DP-0.4V-02

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 31 (item 30).

Value: `not specified`. Manufacturer part: `HC-PBB40C-80DP-0.4V-02`. Manufacturer: `HCTL(华灿天禄)`.

Footprint: `CONN-SMD_80P-P0.40_HC-PBB40C-80DP-0.4V-02`. Supplier: `LCSC`. Supplier part: `C19089237`.

Schematic source: `afe-schematic.epru` line 9709, component `8d4e444b1de886b7`, symbol `985859a5747b811e`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | NEAR |
| `2` | `2` | `AFE:GND` | same | CONNECTED | NEAR |
| `3` | `3` | — | same | UNCONNECTED | NONE |
| `4` | `4` | — | same | UNCONNECTED | NONE |
| `5` | `5` | — | same | UNCONNECTED | NONE |
| `6` | `6` | — | same | UNCONNECTED | NONE |
| `7` | `7` | `AFE:GND` | same | CONNECTED | NEAR |
| `8` | `8` | `AFE:GND` | same | CONNECTED | NEAR |
| `9` | `9` | — | same | UNCONNECTED | NONE |
| `10` | `10` | — | same | UNCONNECTED | NONE |
| `11` | `11` | — | same | UNCONNECTED | NONE |
| `12` | `12` | — | same | UNCONNECTED | NONE |
| `13` | `13` | `AFE:GND` | same | CONNECTED | NEAR |
| `14` | `14` | `AFE:GND` | same | CONNECTED | NEAR |
| `15` | `15` | — | same | UNCONNECTED | NONE |
| `16` | `16` | — | same | UNCONNECTED | NONE |
| `17` | `17` | — | same | UNCONNECTED | NONE |
| `18` | `18` | — | same | UNCONNECTED | NONE |
| `19` | `19` | `AFE:GND` | same | CONNECTED | NEAR |
| `20` | `20` | `AFE:GND` | same | CONNECTED | NEAR |
| `21` | `21` | — | same | UNCONNECTED | NONE |
| `22` | `22` | — | same | UNCONNECTED | NONE |
| `23` | `23` | — | same | UNCONNECTED | NONE |
| `24` | `24` | — | same | UNCONNECTED | NONE |
| `25` | `25` | `AFE:GND` | same | CONNECTED | NEAR |
| `26` | `26` | `AFE:GND` | same | CONNECTED | NEAR |
| `27` | `27` | — | same | UNCONNECTED | NONE |
| `28` | `28` | — | same | UNCONNECTED | NONE |
| `29` | `29` | — | same | UNCONNECTED | NONE |
| `30` | `30` | — | same | UNCONNECTED | NONE |
| `31` | `31` | `AFE:GND` | same | CONNECTED | NEAR |
| `32` | `32` | `AFE:GND` | same | CONNECTED | NEAR |
| `33` | `33` | — | same | UNCONNECTED | NONE |
| `34` | `34` | — | same | UNCONNECTED | NONE |
| `35` | `35` | — | same | UNCONNECTED | NONE |
| `36` | `36` | — | same | UNCONNECTED | NONE |
| `37` | `37` | `AFE:GND` | same | CONNECTED | NEAR |
| `38` | `38` | `AFE:GND` | same | CONNECTED | NEAR |
| `39` | `39` | — | same | UNCONNECTED | NONE |
| `40` | `40` | — | same | UNCONNECTED | NONE |
| `41` | `41` | — | same | UNCONNECTED | NONE |
| `42` | `42` | — | same | UNCONNECTED | NONE |
| `43` | `43` | `AFE:GND` | same | CONNECTED | NEAR |
| `44` | `44` | `AFE:GND` | same | CONNECTED | NEAR |
| `45` | `45` | `AFE:LCLKM` | same | CONNECTED | NEAR |
| `46` | `46` | `AFE:FCLKM` | same | CONNECTED | NEAR |
| `47` | `47` | `AFE:LCLKP` | same | CONNECTED | NEAR |
| `48` | `48` | `AFE:FCLKP` | same | CONNECTED | NEAR |
| `49` | `49` | `AFE:GND` | same | CONNECTED | NEAR |
| `50` | `50` | `AFE:GND` | same | CONNECTED | NEAR |
| `51` | `51` | `AFE:OUT1M` | same | CONNECTED | NEAR |
| `52` | `52` | — | same | UNCONNECTED | NONE |
| `53` | `53` | `AFE:OUT1P` | same | CONNECTED | NEAR |
| `54` | `54` | — | same | UNCONNECTED | NONE |
| `55` | `55` | `AFE:GND` | same | CONNECTED | NEAR |
| `56` | `56` | `AFE:GND` | same | CONNECTED | NEAR |
| `57` | `57` | — | same | UNCONNECTED | NONE |
| `58` | `58` | — | same | UNCONNECTED | NONE |
| `59` | `59` | — | same | UNCONNECTED | NONE |
| `60` | `60` | — | same | UNCONNECTED | NONE |
| `61` | `61` | `AFE:GND` | same | CONNECTED | NEAR |
| `62` | `62` | `AFE:GND` | same | CONNECTED | NEAR |
| `63` | `63` | — | same | UNCONNECTED | NONE |
| `64` | `64` | — | same | UNCONNECTED | NONE |
| `65` | `65` | — | same | UNCONNECTED | NONE |
| `66` | `66` | — | same | UNCONNECTED | NONE |
| `67` | `67` | `AFE:GND` | same | CONNECTED | NEAR |
| `68` | `68` | `AFE:GND` | same | CONNECTED | NEAR |
| `69` | `69` | — | same | UNCONNECTED | NONE |
| `70` | `70` | — | same | UNCONNECTED | NONE |
| `71` | `71` | — | same | UNCONNECTED | NONE |
| `72` | `72` | — | same | UNCONNECTED | NONE |
| `73` | `73` | `AFE:GND` | same | CONNECTED | NEAR |
| `74` | `74` | `AFE:GND` | same | CONNECTED | NEAR |
| `75` | `75` | — | same | UNCONNECTED | NONE |
| `76` | `76` | `AFE:N_R10_1` | same | CONNECTED | NEAR |
| `77` | `77` | `AFE:N_R9_2` | same | CONNECTED | NEAR |
| `78` | `78` | `AFE:N_R11_1` | same | CONNECTED | NEAR |
| `79` | `79` | `AFE:GND` | same | CONNECTED | NEAR |
| `80` | `80` | `AFE:GND` | same | CONNECTED | NEAR |
| `81` | `81` | `AFE:GND` | same | CONNECTED | EXACT |
| `82` | `82` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.U6 — HC-PBB40C-80DP-0.4V-02

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 31 (item 30).

Value: `not specified`. Manufacturer part: `HC-PBB40C-80DP-0.4V-02`. Manufacturer: `HCTL(华灿天禄)`.

Footprint: `CONN-SMD_80P-P0.40_HC-PBB40C-80DP-0.4V-02`. Supplier: `LCSC`. Supplier part: `C19089237`.

Schematic source: `afe-schematic.epru` line 9832, component `02952efc6ac43099`, symbol `985859a5747b811e`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `1` | `AFE:GND` | same | CONNECTED | NEAR |
| `2` | `2` | `AFE:GND` | same | CONNECTED | NEAR |
| `3` | `3` | — | same | UNCONNECTED | NONE |
| `4` | `4` | — | same | UNCONNECTED | NONE |
| `5` | `5` | — | same | UNCONNECTED | NONE |
| `6` | `6` | — | same | UNCONNECTED | NONE |
| `7` | `7` | `AFE:GND` | same | CONNECTED | NEAR |
| `8` | `8` | `AFE:GND` | same | CONNECTED | NEAR |
| `9` | `9` | — | same | UNCONNECTED | NONE |
| `10` | `10` | — | same | UNCONNECTED | NONE |
| `11` | `11` | — | same | UNCONNECTED | NONE |
| `12` | `12` | — | same | UNCONNECTED | NONE |
| `13` | `13` | `AFE:GND` | same | CONNECTED | NEAR |
| `14` | `14` | `AFE:GND` | same | CONNECTED | NEAR |
| `15` | `15` | — | same | UNCONNECTED | NONE |
| `16` | `16` | — | same | UNCONNECTED | NONE |
| `17` | `17` | — | same | UNCONNECTED | NONE |
| `18` | `18` | — | same | UNCONNECTED | NONE |
| `19` | `19` | `AFE:GND` | same | CONNECTED | NEAR |
| `20` | `20` | `AFE:GND` | same | CONNECTED | NEAR |
| `21` | `21` | — | same | UNCONNECTED | NONE |
| `22` | `22` | — | same | UNCONNECTED | NONE |
| `23` | `23` | — | same | UNCONNECTED | NONE |
| `24` | `24` | — | same | UNCONNECTED | NONE |
| `25` | `25` | `AFE:GND` | same | CONNECTED | NEAR |
| `26` | `26` | `AFE:GND` | same | CONNECTED | NEAR |
| `27` | `27` | — | same | UNCONNECTED | NONE |
| `28` | `28` | — | same | UNCONNECTED | NONE |
| `29` | `29` | — | same | UNCONNECTED | NONE |
| `30` | `30` | — | same | UNCONNECTED | NONE |
| `31` | `31` | `AFE:GND` | same | CONNECTED | NEAR |
| `32` | `32` | `AFE:GND` | same | CONNECTED | NEAR |
| `33` | `33` | `AFE:33` | same | CONNECTED | EXACT |
| `34` | `34` | — | same | UNCONNECTED | NONE |
| `35` | `35` | `AFE:35` | same | CONNECTED | NEAR |
| `36` | `36` | — | same | UNCONNECTED | NONE |
| `37` | `37` | `AFE:GND` | same | CONNECTED | NEAR |
| `38` | `38` | `AFE:GND` | same | CONNECTED | NEAR |
| `39` | `39` | `AFE:39` | same | CONNECTED | EXACT |
| `40` | `40` | — | same | UNCONNECTED | NONE |
| `41` | `41` | `AFE:41` | same | SINGLE_PIN_NET | EXACT |
| `42` | `42` | — | same | UNCONNECTED | NONE |
| `43` | `43` | `AFE:GND` | same | CONNECTED | NEAR |
| `44` | `44` | `AFE:GND` | same | CONNECTED | NEAR |
| `45` | `45` | — | same | UNCONNECTED | NONE |
| `46` | `46` | — | same | UNCONNECTED | NONE |
| `47` | `47` | — | same | UNCONNECTED | NONE |
| `48` | `48` | — | same | UNCONNECTED | NONE |
| `49` | `49` | `AFE:GND` | same | CONNECTED | NEAR |
| `50` | `50` | `AFE:GND` | same | CONNECTED | NEAR |
| `51` | `51` | `AFE:51` | same | CONNECTED | EXACT |
| `52` | `52` | — | same | UNCONNECTED | NONE |
| `53` | `53` | `AFE:53` | same | CONNECTED | EXACT |
| `54` | `54` | — | same | UNCONNECTED | NONE |
| `55` | `55` | `AFE:GND` | same | CONNECTED | NEAR |
| `56` | `56` | `AFE:GND` | same | CONNECTED | NEAR |
| `57` | `57` | `AFE:57` | same | CONNECTED | EXACT |
| `58` | `58` | — | same | UNCONNECTED | NONE |
| `59` | `59` | `AFE:59` | same | CONNECTED | EXACT |
| `60` | `60` | — | same | UNCONNECTED | NONE |
| `61` | `61` | `AFE:GND` | same | CONNECTED | NEAR |
| `62` | `62` | `AFE:GND` | same | CONNECTED | NEAR |
| `63` | `63` | `AFE:63` | same | CONNECTED | EXACT |
| `64` | `64` | — | same | UNCONNECTED | NONE |
| `65` | `65` | `AFE:65` | same | CONNECTED | EXACT |
| `66` | `66` | — | same | UNCONNECTED | NONE |
| `67` | `67` | `AFE:GND` | same | CONNECTED | NEAR |
| `68` | `68` | `AFE:GND` | same | CONNECTED | NEAR |
| `69` | `69` | — | same | UNCONNECTED | NONE |
| `70` | `70` | `AFE:ADS_RST` | same | CONNECTED | NEAR |
| `71` | `71` | — | same | UNCONNECTED | NONE |
| `72` | `72` | `AFE:N_R5_2` | same | CONNECTED | NEAR |
| `73` | `73` | `AFE:GND` | same | CONNECTED | NEAR |
| `74` | `74` | `AFE:GND` | same | CONNECTED | NEAR |
| `75` | `75` | — | same | UNCONNECTED | NONE |
| `76` | `76` | `AFE:CS` | same | CONNECTED | NEAR |
| `77` | `77` | — | same | UNCONNECTED | NONE |
| `78` | `78` | `AFE:N_R1_2` | same | CONNECTED | NEAR |
| `79` | `79` | `AFE:GND` | same | CONNECTED | NEAR |
| `80` | `80` | `AFE:GND` | same | CONNECTED | NEAR |
| `81` | `81` | `AFE:GND` | same | CONNECTED | EXACT |
| `82` | `82` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.U7 — DSC1123 40Mhz OSC

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 32 (item 31).

Value: `not specified`. Manufacturer part: `not specified`. Manufacturer: `not specified`.

Footprint: `DSC1123AE2 OSC`. Supplier: `not specified`. Supplier part: `not specified`.

Schematic source: `afe-schematic.epru` line 7521, component `2147158f825a2506`, symbol `8f951c266737ee93`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `EN` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `2` | `NC` | — | same | UNCONNECTED | NONE |
| `3` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |
| `4` | `OUT+` | `AFE:N_C53_2` | same | CONNECTED | EXACT |
| `5` | `OUT-` | `AFE:N_C66_2` | same | CONNECTED | EXACT |
| `6` | `VDD` | `AFE:+3.3_VDD` | same | CONNECTED | EXACT |
| `7` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |

#### AFE.U12 — TPS79618DCQR

BOM: `BOM_ADC_Schematic2_2026-09-07.xlsx`, sheet `BOM_ADC_Schematic2_2026-09-07`, row 33 (item 32).

Value: `not specified`. Manufacturer part: `TPS79618DCQR`. Manufacturer: `TI(德州仪器)`.

Footprint: `SOT-223-6_L6.5-W3.5-P1.27-BR`. Supplier: `LCSC`. Supplier part: `C2867020`.

Schematic source: `afe-schematic.epru` line 4832, component `e8882`, symbol `9b8442de22eb94c4`.

| Pin | Source pin name | Primary net ID | Saved net | Status | Contact |
| --- | --- | --- | --- | --- | --- |
| `1` | `EN` | `AFE:N_C70_1` | same | CONNECTED | EXACT |
| `2` | `IN` | `AFE:N_C70_1` | same | CONNECTED | EXACT |
| `3` | `GND` | `AFE:GND` | same | CONNECTED | EXACT |
| `4` | `OUT` | `AFE:N_C71_1` | same | CONNECTED | EXACT |
| `5` | `NR/FB` | `AFE:N_C73_2` | same | CONNECTED | EXACT |
| `6` | `TAB` | `AFE:GND` | same | CONNECTED | EXACT |

## 5. Complete net-to-endpoint index

The records below are JSON Lines: one complete JSON object per line. `endpoints` lists every component terminal on the primary net. `aliases` contains source net labels without the board prefix. `saved_net_ids` lists the pre-bridge schematic nets merged into this primary net; the component tables identify each pin’s original membership. `bridged_components`, when present, lists owner-confirmed closed gaps. `wire_ids` and `label_ids` are source record IDs in the board’s `.epru` SCH_PAGE section. `near_pins` and `near_labels` identify accepted tolerance-dependent contacts. Unconnected terminals appear in Sections 4 and 6 and are not encoded as a shared net. Unnamed nets with only one attached terminal remain listed.

### PULSER net records

```jsonl
{"net":"PULSER:1.8V NC","aliases":["1.8V NC"],"saved_net_ids":["PULSER:1.8V NC"],"endpoints":["PULSER.CN1.2"],"wire_ids":["6ac14325dd4df0d8"],"label_ids":["ca76cca1d225f3c7"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:1NO0","aliases":["1NO0"],"saved_net_ids":["PULSER:1NO0"],"endpoints":["PULSER.U3.2","PULSER.U9.58"],"wire_ids":["62fa4a82974f7bd2","6c9c9e6651b6294b"],"label_ids":["4959a333bb945683","4ff2db8d5f867c34"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:1NO1","aliases":["1NO1"],"saved_net_ids":["PULSER:1NO1"],"endpoints":["PULSER.U3.4","PULSER.U9.56"],"wire_ids":["86deb02790a45eac","927c92422879cb56"],"label_ids":["762f69d21f71ae78","b5c5c6a2e68fd23a"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:1NO2","aliases":["1NO2"],"saved_net_ids":["PULSER:1NO2"],"endpoints":["PULSER.U3.6","PULSER.U9.54"],"wire_ids":["39a5190b044cb024","3d9d5966366a99ae"],"label_ids":["35e6ed31db98941b","5f12d1cef2342dca"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:1NO3","aliases":["1NO3"],"saved_net_ids":["PULSER:1NO3"],"endpoints":["PULSER.U3.8","PULSER.U9.52"],"wire_ids":["4dfa76c88037fe57","fb07ace92ed3a351"],"label_ids":["5ecff5c78cce1939","8e21764c2b4b9533"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:1NO4","aliases":["1NO4"],"saved_net_ids":["PULSER:1NO4"],"endpoints":["PULSER.U3.12","PULSER.U9.3"],"wire_ids":["3c7668711f976c32","6f20882016c9a586"],"label_ids":["7887e471dd379b44","b31332ef2a7ba404"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:1NO5","aliases":["1NO5"],"saved_net_ids":["PULSER:1NO5"],"endpoints":["PULSER.U3.14","PULSER.U9.5"],"wire_ids":["949501208a25d603","be76079f40eb8d09"],"label_ids":["0fea1b53085d6b17","1e97f7d886985be8"],"near_pins":["PULSER.U9.5"],"near_labels":[]}
{"net":"PULSER:1NO6","aliases":["1NO6"],"saved_net_ids":["PULSER:1NO6"],"endpoints":["PULSER.U3.16","PULSER.U9.7"],"wire_ids":["930386a5e28e72a0","f2009515ed303127"],"label_ids":["0d31f9596999aa6b","46a49351e7fed06b"],"near_pins":["PULSER.U9.7"],"near_labels":[]}
{"net":"PULSER:1NO7","aliases":["1NO7"],"saved_net_ids":["PULSER:1NO7"],"endpoints":["PULSER.U3.18","PULSER.U9.9"],"wire_ids":["023c3c66a3319273","73b0dce4d4237d61"],"label_ids":["e75c7b4fe0c4b2fa","fac357aa2834dee7"],"near_pins":["PULSER.U9.9"],"near_labels":[]}
{"net":"PULSER:1NO8","aliases":["1NO8"],"saved_net_ids":["PULSER:1NO8"],"endpoints":["PULSER.U3.19","PULSER.U9.11"],"wire_ids":["a4579d2992f9b1ce","d14a0a472ea35b7f"],"label_ids":["703517626a1ed9cf","7354e52615c42d55"],"near_pins":["PULSER.U9.11"],"near_labels":[]}
{"net":"PULSER:1NO9","aliases":["1NO9"],"saved_net_ids":["PULSER:1NO9"],"endpoints":["PULSER.U3.21","PULSER.U9.13"],"wire_ids":["2874451854915c77","c597d444cc1fcdc2"],"label_ids":["2932f11f0cb339a3","f567320ecbfbf970"],"near_pins":["PULSER.U9.13"],"near_labels":[]}
{"net":"PULSER:1NO10","aliases":["1NO10"],"saved_net_ids":["PULSER:1NO10"],"endpoints":["PULSER.U3.23","PULSER.U9.15"],"wire_ids":["b0b7a9a1687acbe3","f0ee217c2160c935"],"label_ids":["5ab3683da6f58ed1","efa3a8699e586543"],"near_pins":["PULSER.U9.15"],"near_labels":[]}
{"net":"PULSER:1NO11","aliases":["1NO11"],"saved_net_ids":["PULSER:1NO11"],"endpoints":["PULSER.U3.25","PULSER.U9.17"],"wire_ids":["a479472c9a6918be","f0483fc77185e52f"],"label_ids":["8898f16763602bb8","e57cc853ca9baf04"],"near_pins":["PULSER.U9.17"],"near_labels":[]}
{"net":"PULSER:1NO12","aliases":["1NO12"],"saved_net_ids":["PULSER:1NO12"],"endpoints":["PULSER.U3.29","PULSER.U9.19"],"wire_ids":["205b9f8f03234af5","b95888ec0ab48303"],"label_ids":["15a67e86d82b8312","b2aa0e5fc740b04e"],"near_pins":["PULSER.U9.19"],"near_labels":[]}
{"net":"PULSER:1NO13","aliases":["1NO13"],"saved_net_ids":["PULSER:1NO13"],"endpoints":["PULSER.U3.31","PULSER.U9.21"],"wire_ids":["2cd131969ce62480","e411ad16b1f3968d"],"label_ids":["030d2f5709e7b97a","c856be71b654d9a8"],"near_pins":["PULSER.U9.21"],"near_labels":[]}
{"net":"PULSER:1NO14","aliases":["1NO14"],"saved_net_ids":["PULSER:1NO14"],"endpoints":["PULSER.U3.33","PULSER.U9.23"],"wire_ids":["b1ceaedc415c2237","d673f771060b857c"],"label_ids":["cadaba3769605cc0","e5f64358c386532c"],"near_pins":["PULSER.U9.23"],"near_labels":[]}
{"net":"PULSER:1NO15","aliases":["1NO15"],"saved_net_ids":["PULSER:1NO15"],"endpoints":["PULSER.U3.35","PULSER.U9.25"],"wire_ids":["533ec39150dc05ca","977dd9f5262cbbdd"],"label_ids":["48e4a6c8174ad5f0","f0b46718460aebc6"],"near_pins":["PULSER.U9.25"],"near_labels":[]}
{"net":"PULSER:2NO0","aliases":["2NO0"],"saved_net_ids":["PULSER:2NO0"],"endpoints":["PULSER.U7.2","PULSER.U9.27"],"wire_ids":["013e6ed05e44f5c8","93175f8fd1617ab1"],"label_ids":["0471a50917344087","19ed6068e87fdc11"],"near_pins":["PULSER.U9.27"],"near_labels":[]}
{"net":"PULSER:2NO1","aliases":["2NO1"],"saved_net_ids":["PULSER:2NO1"],"endpoints":["PULSER.U7.4","PULSER.U9.29"],"wire_ids":["69577d6aac655c68","85468b869f8b5858"],"label_ids":["476cc33e4fe0b6e4","6ad4edf0f5e41613"],"near_pins":["PULSER.U9.29"],"near_labels":[]}
{"net":"PULSER:2NO2","aliases":["2NO2"],"saved_net_ids":["PULSER:2NO2"],"endpoints":["PULSER.U7.6","PULSER.U9.31"],"wire_ids":["999b19394fa0e219","d59c91b17b875ea5"],"label_ids":["7032d7bf59cff509","832a9be41e6230f8"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:2NO3","aliases":["2NO3"],"saved_net_ids":["PULSER:2NO3"],"endpoints":["PULSER.U7.8","PULSER.U9.33"],"wire_ids":["39069e08bf0aca4d","fe7b83ad4522024a"],"label_ids":["7b2eb6c43a72db97","7f63bf33d0871422"],"near_pins":["PULSER.U9.33"],"near_labels":[]}
{"net":"PULSER:2NO4","aliases":["2NO4"],"saved_net_ids":["PULSER:2NO4"],"endpoints":["PULSER.U7.12","PULSER.U9.35"],"wire_ids":["49abad9656a60550","8a9121db77e70321"],"label_ids":["1592deddcb3824cf","caa5092c3e27d1bc"],"near_pins":["PULSER.U9.35"],"near_labels":[]}
{"net":"PULSER:2NO5","aliases":["2NO5"],"saved_net_ids":["PULSER:2NO5"],"endpoints":["PULSER.U7.14","PULSER.U9.37"],"wire_ids":["69abb1b0955ba195","e2bf46b3bebad673"],"label_ids":["7419fba94b45ae9e","bc663fdc69b072a8"],"near_pins":["PULSER.U9.37"],"near_labels":[]}
{"net":"PULSER:2NO6","aliases":["2NO6"],"saved_net_ids":["PULSER:2NO6"],"endpoints":["PULSER.U7.16","PULSER.U9.39"],"wire_ids":["be5ade77ac46190e","fc322f1d180fdff7"],"label_ids":["0faf3e2c92f21b7a","f0891f0b37518e8d"],"near_pins":["PULSER.U9.39"],"near_labels":[]}
{"net":"PULSER:2NO7","aliases":["2NO7"],"saved_net_ids":["PULSER:2NO7"],"endpoints":["PULSER.U7.18","PULSER.U9.41"],"wire_ids":["75c7c4fb63f4a3b3","e70dd7a402a68f37"],"label_ids":["985f54df933d0922","9bb1835948a27c80"],"near_pins":["PULSER.U9.41"],"near_labels":[]}
{"net":"PULSER:2NO8","aliases":["2NO8"],"saved_net_ids":["PULSER:2NO8"],"endpoints":["PULSER.U7.19","PULSER.U9.43"],"wire_ids":["a81f0ce961708fd8","dec805cff9dcbc89"],"label_ids":["5fbfc7339e6fad23","8af83f411c779182"],"near_pins":["PULSER.U9.43"],"near_labels":[]}
{"net":"PULSER:2NO9","aliases":["2NO9"],"saved_net_ids":["PULSER:2NO9"],"endpoints":["PULSER.U7.21","PULSER.U9.45"],"wire_ids":["9f26c35bfe14cf71","b33a11b199de2e03"],"label_ids":["cbafc43beca678e8","d983698fdce93e6f"],"near_pins":["PULSER.U9.45"],"near_labels":[]}
{"net":"PULSER:2NO10","aliases":["2NO10"],"saved_net_ids":["PULSER:2NO10"],"endpoints":["PULSER.U7.23","PULSER.U9.47"],"wire_ids":["d347b2e67f95322a","efc9703dd6bef54b"],"label_ids":["5ad1f664064380f5","cfaf07a66ca35da8"],"near_pins":["PULSER.U9.47"],"near_labels":[]}
{"net":"PULSER:2NO11","aliases":["2NO11"],"saved_net_ids":["PULSER:2NO11"],"endpoints":["PULSER.U7.25","PULSER.U9.49"],"wire_ids":["19b692f4eaecff2a","e9bf284e5f3ce641"],"label_ids":["e41bff7772dca5fe","ef0bf83b351b3a88"],"near_pins":["PULSER.U9.49"],"near_labels":[]}
{"net":"PULSER:2NO12","aliases":["2NO12"],"saved_net_ids":["PULSER:2NO12"],"endpoints":["PULSER.U7.29","PULSER.U9.98"],"wire_ids":["09f20d8c9c6a5322","6b1ed2ebc08cd662"],"label_ids":["499ddbe7b3cf1a83","a8c259b75c414ab2"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:2NO13","aliases":["2NO13"],"saved_net_ids":["PULSER:2NO13"],"endpoints":["PULSER.U7.31","PULSER.U9.96"],"wire_ids":["1c290130b0c75266","23bfa084b8f4ea4b"],"label_ids":["98d2676aa1215b90","da8d1518b6010a65"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:2NO14","aliases":["2NO14"],"saved_net_ids":["PULSER:2NO14"],"endpoints":["PULSER.U7.33","PULSER.U9.94"],"wire_ids":["178d1c9a61096dde","a08420619b5b5b90"],"label_ids":["12341ff26717a33e","934962f98d8816ae"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:2NO15","aliases":["2NO15"],"saved_net_ids":["PULSER:2NO15"],"endpoints":["PULSER.U7.35","PULSER.U9.92"],"wire_ids":["7f4f36e2fa8e4edc","c087fece8c0e8954"],"label_ids":["e4583c8ea8f74bc8","e6c7c9f14d237a6f"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3.3V NC","aliases":["3.3V NC"],"saved_net_ids":["PULSER:3.3V NC"],"endpoints":["PULSER.C34.1","PULSER.C35.1","PULSER.C36.1","PULSER.C37.1","PULSER.CN1.4","PULSER.U1.40","PULSER.U3.40","PULSER.U5.40","PULSER.U7.40"],"wire_ids":["110e7b994b47914c","2856cfe677554791","498060796a25a249","93fe9bf056a42798","e5c17440a9cb6896","e7b356d931ddbe5e"],"label_ids":["62332749250cd0fe","8efda481b9fc72de","9e5400d6058774c2","abc29ef43dc264ed","aecbc843e9d1ee1b","e6efe456c90fde6d"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO0","aliases":["3NO0"],"saved_net_ids":["PULSER:3NO0"],"endpoints":["PULSER.U1.2","PULSER.U9.90"],"wire_ids":["1d7c97b9a7df8ae3","905eee50a8baea94"],"label_ids":["31cabe6bd126106f","44babadf43a200fb"],"near_pins":["PULSER.U9.90"],"near_labels":[]}
{"net":"PULSER:3NO1","aliases":["3NO1"],"saved_net_ids":["PULSER:3NO1"],"endpoints":["PULSER.U1.4","PULSER.U9.88"],"wire_ids":["495e1bdbc19efb78","e1f7f92520c1486a"],"label_ids":["3b1dde0be2558a5b","6d8759da7082b483"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO2","aliases":["3NO2"],"saved_net_ids":["PULSER:3NO2"],"endpoints":["PULSER.U1.6","PULSER.U9.86"],"wire_ids":["77e9d4566bbcc836","dcf76cf33cd3ccdb"],"label_ids":["117a9515f8a4f819","e04b804107beb676"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO3","aliases":["3NO3"],"saved_net_ids":["PULSER:3NO3"],"endpoints":["PULSER.U1.8","PULSER.U9.84"],"wire_ids":["3063905c5a7d0c05","5a50180991b6b954"],"label_ids":["a78d84afe5c6aa50","b286243bafc46fdb"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO4","aliases":["3NO4"],"saved_net_ids":["PULSER:3NO4"],"endpoints":["PULSER.U1.12","PULSER.U9.82"],"wire_ids":["2e2639f7208d6269","e6960966d7312965"],"label_ids":["060b3af6af7b4362","2a7a7602fe5ff8f2"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO5","aliases":["3NO5"],"saved_net_ids":["PULSER:3NO5"],"endpoints":["PULSER.U1.14","PULSER.U9.80"],"wire_ids":["26767ffe9f524da9","b3e5ca0215f7063b"],"label_ids":["22489852b8478b26","8999818cfb797c49"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO6","aliases":["3NO6"],"saved_net_ids":["PULSER:3NO6"],"endpoints":["PULSER.U1.16","PULSER.U9.78"],"wire_ids":["308f4fcf25de3991","42225f6c34234097"],"label_ids":["c537a421569c07f6","e1bc5b6363d4afb4"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO7","aliases":["3NO7"],"saved_net_ids":["PULSER:3NO7"],"endpoints":["PULSER.U1.18","PULSER.U9.76"],"wire_ids":["037725185bf6c43e","236b1ccff67aea9a"],"label_ids":["02a83cbb3dc5f18a","11ec8df97329c9c1"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO8","aliases":["3NO8"],"saved_net_ids":["PULSER:3NO8"],"endpoints":["PULSER.U1.19","PULSER.U9.74"],"wire_ids":["234093aa9fb211c1","fdfa331bd5d171b9"],"label_ids":["5455766629caf8ee","ad728e68681db8a0"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO9","aliases":["3NO9"],"saved_net_ids":["PULSER:3NO9"],"endpoints":["PULSER.U1.21","PULSER.U9.72"],"wire_ids":["57d8f79b81983688","fd6876c405b6df3d"],"label_ids":["4ae1c4efab13ff85","be31e514aa91e3df"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO10","aliases":["3NO10"],"saved_net_ids":["PULSER:3NO10"],"endpoints":["PULSER.U1.23","PULSER.U9.70"],"wire_ids":["01bf607831943582","5554435d233246fc"],"label_ids":["cdcfb38727e27de5","e77b9dc2ee188096"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO11","aliases":["3NO11"],"saved_net_ids":["PULSER:3NO11"],"endpoints":["PULSER.U1.25","PULSER.U9.68"],"wire_ids":["6633ae6f4d158b92","7c9b9194f1893ebe"],"label_ids":["043de0186767499f","4195ce5b6ad9a247"],"near_pins":[],"near_labels":["4195ce5b6ad9a247"]}
{"net":"PULSER:3NO12","aliases":["3NO12"],"saved_net_ids":["PULSER:3NO12"],"endpoints":["PULSER.U1.29","PULSER.U9.66"],"wire_ids":["5b84f98a35f7370b","a00f4361b3e94202"],"label_ids":["0c726e79ebd5a588","d35dde52a1d30e5e"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO13","aliases":["3NO13"],"saved_net_ids":["PULSER:3NO13"],"endpoints":["PULSER.U1.31","PULSER.U9.64"],"wire_ids":["02dbaf6f0493f53b","0f745ce9260bb40e"],"label_ids":["81aa75aba2732883","abed59c978a8f225"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO14","aliases":["3NO14"],"saved_net_ids":["PULSER:3NO14"],"endpoints":["PULSER.U1.33","PULSER.U9.62"],"wire_ids":["7b40d66e5f306f95","b1c00c8292477ade"],"label_ids":["88055495418ecf42","9615f6d9e27ce0f4"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:3NO15","aliases":["3NO15"],"saved_net_ids":["PULSER:3NO15"],"endpoints":["PULSER.U1.35","PULSER.U9.60"],"wire_ids":["4c90fe207f4b079d","904acf529aaf226d"],"label_ids":["19ef0f89c47e2e3f","a1474ab07af54e45"],"near_pins":["PULSER.U9.60"],"near_labels":[]}
{"net":"PULSER:+5V","aliases":["+5V"],"saved_net_ids":["PULSER:+5V"],"endpoints":["PULSER.C11.2","PULSER.C12.2","PULSER.C14.2","PULSER.C16.2","PULSER.C17.2","PULSER.C19.2","PULSER.C23.2","PULSER.C38.1","PULSER.C39.1","PULSER.C40.1","PULSER.C41.1","PULSER.CN1.1","PULSER.U1.43","PULSER.U2.2","PULSER.U3.43","PULSER.U5.43","PULSER.U6.8","PULSER.U6.10","PULSER.U6.11","PULSER.U7.43","PULSER.U12.1"],"wire_ids":["0927df7e34365017","0e55f0f83c6b611a","1bf7d88ee05136ac","59b3f15e83ab5296","60ff718c3b4bdb75","6d29dfb3ca2a8541","8ec95c2d2b73bee6","dac679013545eadf","e545b978ea6585c0"],"label_ids":["2b45b0afc71f6549","62405edb7e859556","63fae41161899ec3","9766d6ed9bb37564","cafd552ae9b52ee0","d3ae0f7367050e44","d8cabeb3088bff0a","eb238d1cf1149e45","f9efdad555167126"],"near_pins":["PULSER.U2.2"],"near_labels":["d3ae0f7367050e44"]}
{"net":"PULSER:+100V","aliases":["+100V"],"saved_net_ids":["PULSER:+100V"],"endpoints":["PULSER.C1.1","PULSER.C6.2","PULSER.C7.2","PULSER.CN2.3","PULSER.Q1.3","PULSER.R66.1"],"wire_ids":["7a299eabd28d15c4","8de3c6a655bc7a26","c0213affd2b05290"],"label_ids":["a60e9f5683c5314e","dd2cebd32604fa55","e5b4b2b3fe438be0"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:-5V","aliases":["-5V"],"saved_net_ids":["PULSER:-5V"],"endpoints":["PULSER.C10.2","PULSER.C13.2","PULSER.C15.2","PULSER.C18.1","PULSER.C20.2","PULSER.C21.2","PULSER.C22.2","PULSER.U2.1","PULSER.U6.2","PULSER.U6.5","PULSER.U6.6","PULSER.U6.13","PULSER.U11.2"],"wire_ids":["15588bf15250544d","25c0e4a9dd44c27a","819e9031daee8cd6","905c92aa14c446ec"],"label_ids":["0c2a528a90e34442","54fe7a11ed72dc4a","70247c32ae669fab","f7064fb401297102"],"near_pins":["PULSER.U2.1","PULSER.U6.13"],"near_labels":[]}
{"net":"PULSER:-100V","aliases":["-100V"],"saved_net_ids":["PULSER:-100V"],"endpoints":["PULSER.C2.2","PULSER.C5.1","PULSER.C8.1","PULSER.CN2.1","PULSER.Q1.1","PULSER.R65.1"],"wire_ids":["2939ce1e1fab0b40","62a59a58e84e7872","b575ff02f2ad175b"],"label_ids":["756b405bdcc46f69","e0e41705850e13a0","f0496d2ad937e237"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:CLK","aliases":["CLK"],"saved_net_ids":["PULSER:CLK"],"endpoints":["PULSER.CN1.10","PULSER.U1.45","PULSER.U3.45","PULSER.U5.45","PULSER.U7.45"],"wire_ids":["00c99d667504842a","3d31712e420b4136","7b46de04609566ce","bd0100abf2abd283","d6134480918be4d7"],"label_ids":["5de46e56e5b793a7","7565857f545959f2","8e41a4914a088b31","b1899c7e79567ea8","cc8fe3d2b50ae8a5"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:CLR","aliases":["CLR"],"saved_net_ids":["PULSER:CLR"],"endpoints":["PULSER.CN1.17","PULSER.U1.47","PULSER.U3.47","PULSER.U5.47","PULSER.U7.47"],"wire_ids":["3811c17b2600f485","476bd81d16c8cc43","4ff9b05b315b472a","b42b3743247222da","fb3e9bafa3333e9b"],"label_ids":["0f5822d540e8b559","0f8c1f80f1cb9a1d","4774a1a350336963","93fd2546ea39eac7","d6bb999b969e615c"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:DIN","aliases":["DIN"],"saved_net_ids":["PULSER:DIN"],"endpoints":["PULSER.CN1.7","PULSER.U5.44"],"wire_ids":["518867c7ffef6635","feefac20321d5e7f"],"label_ids":["80666efb75b501b5","c4f49945fb409135"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:DOUT1","aliases":["DOUT1"],"saved_net_ids":["PULSER:DOUT1"],"endpoints":["PULSER.U5.39","PULSER.U7.44"],"wire_ids":["c25ac58f5c3da986","ec63fd284cb8cf5a"],"label_ids":["701d3e779c822226","a3f808f12df2757d"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:DOUT2","aliases":["DOUT2"],"saved_net_ids":["PULSER:DOUT2"],"endpoints":["PULSER.U1.44","PULSER.U7.39"],"wire_ids":["67a1e7b06977d758","ba372e9466eca04f"],"label_ids":["3710631572a6a714","fc399ed8e1f53fc2"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:DOUT3","aliases":["DOUT3"],"saved_net_ids":["PULSER:DOUT3"],"endpoints":["PULSER.U1.39","PULSER.U3.44"],"wire_ids":["9a512037d66cf408","9ee7810d85ada9ea"],"label_ids":["282f01a04af41360","d1b3338a40f0bebf"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:DOUT_READBACK","aliases":["DOUT_READBACK"],"saved_net_ids":["PULSER:DOUT_READBACK"],"endpoints":["PULSER.CN1.18","PULSER.U3.39"],"wire_ids":["64e3e9c42a844fb7","c949e4de198c5cff"],"label_ids":["97127126eabbe6c4","e10ccb944d9ccb4b"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:DRIVER_EN","aliases":["DRIVER_EN"],"saved_net_ids":["PULSER:DRIVER_EN"],"endpoints":["PULSER.CN1.19","PULSER.U6.12"],"wire_ids":["060ea0d3f46f0cf5","fb4ad85f7915df90"],"label_ids":["52b58f091ad6580c","8fc66f1fd1357380"],"near_pins":[],"near_labels":["52b58f091ad6580c"]}
{"net":"PULSER:GND","aliases":["GND","SET"],"saved_net_ids":["PULSER:GND"],"endpoints":["PULSER.C1.2","PULSER.C2.1","PULSER.C5.2","PULSER.C6.1","PULSER.C7.1","PULSER.C8.2","PULSER.C10.1","PULSER.C11.1","PULSER.C12.1","PULSER.C13.1","PULSER.C14.1","PULSER.C15.1","PULSER.C16.1","PULSER.C17.1","PULSER.C18.2","PULSER.C19.1","PULSER.C20.1","PULSER.C21.1","PULSER.C22.1","PULSER.C23.1","PULSER.C34.2","PULSER.C35.2","PULSER.C36.2","PULSER.C37.2","PULSER.C38.2","PULSER.C39.2","PULSER.C40.2","PULSER.C41.2","PULSER.CN1.3","PULSER.CN1.8","PULSER.CN1.9","PULSER.CN1.12","PULSER.CN1.13","PULSER.CN1.16","PULSER.CN1.20","PULSER.CN2.2","PULSER.D2.3","PULSER.R67.1","PULSER.R68.1","PULSER.RF2.1","PULSER.RF2.2","PULSER.RF2.3","PULSER.RF2.4","PULSER.U1.9","PULSER.U1.10","PULSER.U1.27","PULSER.U1.28","PULSER.U1.37","PULSER.U1.41","PULSER.U1.42","PULSER.U1.46","PULSER.U1.48","PULSER.U1.49","PULSER.U2.4","PULSER.U3.9","PULSER.U3.10","PULSER.U3.27","PULSER.U3.28","PULSER.U3.37","PULSER.U3.41","PULSER.U3.42","PULSER.U3.46","PULSER.U3.48","PULSER.U3.49","PULSER.U5.9","PULSER.U5.10","PULSER.U5.27","PULSER.U5.28","PULSER.U5.37","PULSER.U5.41","PULSER.U5.42","PULSER.U5.46","PULSER.U5.48","PULSER.U5.49","PULSER.U6.4","PULSER.U7.9","PULSER.U7.10","PULSER.U7.27","PULSER.U7.28","PULSER.U7.37","PULSER.U7.41","PULSER.U7.42","PULSER.U7.46","PULSER.U7.48","PULSER.U7.49","PULSER.U9.1","PULSER.U9.2","PULSER.U9.4","PULSER.U9.6","PULSER.U9.8","PULSER.U9.10","PULSER.U9.12","PULSER.U9.14","PULSER.U9.16","PULSER.U9.18","PULSER.U9.20","PULSER.U9.22","PULSER.U9.24","PULSER.U9.26","PULSER.U9.28","PULSER.U9.30","PULSER.U9.32","PULSER.U9.34","PULSER.U9.36","PULSER.U9.38","PULSER.U9.40","PULSER.U9.42","PULSER.U9.44","PULSER.U9.46","PULSER.U9.48","PULSER.U9.50","PULSER.U9.51","PULSER.U9.53","PULSER.U9.55","PULSER.U9.57","PULSER.U9.59","PULSER.U9.61","PULSER.U9.63","PULSER.U9.65","PULSER.U9.67","PULSER.U9.69","PULSER.U9.71","PULSER.U9.73","PULSER.U9.75","PULSER.U9.77","PULSER.U9.79","PULSER.U9.81","PULSER.U9.83","PULSER.U9.85","PULSER.U9.87","PULSER.U9.89","PULSER.U9.91","PULSER.U9.93","PULSER.U9.95","PULSER.U9.97","PULSER.U9.99","PULSER.U9.100","PULSER.U9.101","PULSER.U9.102","PULSER.U13.2","PULSER.U14.1"],"wire_ids":["002bd4a410c93707","028dbfea86e1342a","0aca1b973681fa10","0ba5e284a76a0187","147d2ed522d8993c","17eec44d148dc136","2e8ca7d82ab205ec","2fce132729f54b6e","3715a5d12ebee1b4","3723748a0f76c584","4761a1a04067ca7a","494bb4c747c49bdf","4cafc3c347ce3d73","5f22c48726c5b05c","77036363261b7dae","773d598c1d3ad864","776e04fb1bafbb69","7aae0d5a6f259e03","7d4bb8800c8d6f09","7dde8770f46ea380","7f860af4090b79ab","81a0f4ab89e8ee50","8663528e2e6648c9","884cdab617c29b2a","93d3ef61a0daffc2","963ba81d9360b809","96b366f2e40f06c2","96e6d9293bfad319","9b94addf63b78ab5","a50f8f5ba7ae6b82","b6f379e2fdfad808","be9dfa09c0587300","c9bbaab2471de81e","d0f9f0f8feee6cec","de22b7a6695ec361","df2aaaf1269b0c00","e7f77fd8793dc4ba","fb913f5b872dd2c5"],"label_ids":["091dba555b63b797","0cff0f1ee286090e","0d86a150697cf5f9","163ad929551f4bef","1826905e9b81e96a","1894a7a7d38b1db1","1ae5a02044d74d60","26a6cda6bfdef5f7","2b6353af972b4b8d","34933c20cae7ed94","3d6079eb601e48d3","46fbfce588b6a159","4a79c06d13d02772","4b468e3f8b170b9f","4b4ade8805e0e170","4e07b12372717d1a","61cc8c31725f94d8","62a2e4c3210e0cb6","6358120d373abec3","6f7fa30f3d3432f5","6fadd9a3809d401d","71029e96c80288a8","7f93acb5738abc6b","8766bc3ca323431f","8d70d426daddb8d6","92afa3cc22e9f801","93c22ac824eb9c1c","a3e4f22051c56e93","a455043ab5b2eef9","a5e1a00998b05f57","b39513dd86ac93d6","c1ffa59b24812ee4","c48ecf5e6d943306","cfecaa593bae6247","dcae30cd4f722495","f03f7bb5f33d466c","f76323363985371d","f79f7b7ae5a2ac56","f821729b8959c819"],"near_pins":["PULSER.U9.1","PULSER.U9.51","PULSER.U9.53","PULSER.U9.100","PULSER.U13.2"],"near_labels":["4a79c06d13d02772","091dba555b63b797","f79f7b7ae5a2ac56","6fadd9a3809d401d"]}
{"net":"PULSER:LE","aliases":["LE"],"saved_net_ids":["PULSER:LE"],"endpoints":["PULSER.CN1.5","PULSER.U1.38","PULSER.U3.38","PULSER.U5.38","PULSER.U7.38"],"wire_ids":["4df7bb0ae9adc721","6d561f67fb81e8a3","93a466dde1c7d975","a0393bc1b65e777a","ed1948a05e4ceb59"],"label_ids":["02e2f00b25bb3cfd","270d90024035a350","75e198847ad59ffd","b11dae70da2623eb","d8fc2f4645339eea"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO0","aliases":["NO0"],"saved_net_ids":["PULSER:NO0"],"endpoints":["PULSER.U5.2"],"wire_ids":["d95dafd5aaec5c59"],"label_ids":["5a22c89346871cb6"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO1","aliases":["NO1"],"saved_net_ids":["PULSER:NO1"],"endpoints":["PULSER.U5.4"],"wire_ids":["b7b2f3751c6715fc"],"label_ids":["4d072d88b31ee076"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO2","aliases":["NO2"],"saved_net_ids":["PULSER:NO2"],"endpoints":["PULSER.U5.6"],"wire_ids":["b0d96661e387ae3d"],"label_ids":["5d6d6874b85c4bbe"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO3","aliases":["NO3"],"saved_net_ids":["PULSER:NO3"],"endpoints":["PULSER.U5.8"],"wire_ids":["ef5f551baea245f7"],"label_ids":["a786562bee521071"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO4","aliases":["NO4"],"saved_net_ids":["PULSER:NO4"],"endpoints":["PULSER.U5.12"],"wire_ids":["dfbb49e62ef7390c"],"label_ids":["d1b55ef8fc3c4927"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO5","aliases":["NO5"],"saved_net_ids":["PULSER:NO5","PULSER:N_R33_2","PULSER:N_R34_2","PULSER:N_R35_2","PULSER:N_R36_2","PULSER:N_R37_2","PULSER:N_R38_1","PULSER:N_R39_1","PULSER:N_R40_1","PULSER:N_R41_1","PULSER:N_R42_1","PULSER:N_R43_1","PULSER:N_R44_1","PULSER:N_R45_1","PULSER:N_R46_1","PULSER:N_R47_1","PULSER:N_R48_1"],"endpoints":["PULSER.R33.1","PULSER.R33.2","PULSER.R34.1","PULSER.R34.2","PULSER.R35.1","PULSER.R35.2","PULSER.R36.1","PULSER.R36.2","PULSER.R37.1","PULSER.R37.2","PULSER.R38.1","PULSER.R38.2","PULSER.R39.1","PULSER.R39.2","PULSER.R40.1","PULSER.R40.2","PULSER.R41.1","PULSER.R41.2","PULSER.R42.1","PULSER.R42.2","PULSER.R43.1","PULSER.R43.2","PULSER.R44.1","PULSER.R44.2","PULSER.R45.1","PULSER.R45.2","PULSER.R46.1","PULSER.R46.2","PULSER.R47.1","PULSER.R47.2","PULSER.R48.1","PULSER.R48.2","PULSER.U5.14","PULSER.U7.1","PULSER.U7.3","PULSER.U7.5","PULSER.U7.7","PULSER.U7.11","PULSER.U7.13","PULSER.U7.15","PULSER.U7.17","PULSER.U7.20","PULSER.U7.22","PULSER.U7.24","PULSER.U7.26","PULSER.U7.30","PULSER.U7.32","PULSER.U7.34","PULSER.U7.36"],"wire_ids":["1d8e2f53deb99d4c","2ca3271ebc35c3b0","477df3e79d88ff09","4cc2e7f4095bb45e","5b2082123628f827","7fbce9083e9b20ca","85364b64344d363f","8f602720404757cf","95681be436cb5f90","988d64805714918e","a14a32135f01a94a","ba1aa2691ed705dc","c07f990221309e8f","cdf54581fdc4e95a","d2bd2adaddfa7220","d64645fee51ff78a","f23f540ea12c2e1f","f655a57f2952f5ca"],"label_ids":["39ac6b2e66a963e8","3de65f15ce115cca"],"near_pins":[],"near_labels":[],"physical_override":"Owner-confirmed leaf mux solder gaps closed","bridged_components":["PULSER.R33","PULSER.R34","PULSER.R35","PULSER.R36","PULSER.R37","PULSER.R38","PULSER.R39","PULSER.R40","PULSER.R41","PULSER.R42","PULSER.R43","PULSER.R44","PULSER.R45","PULSER.R46","PULSER.R47","PULSER.R48"]}
{"net":"PULSER:NO6","aliases":["NO6"],"saved_net_ids":["PULSER:NO6"],"endpoints":["PULSER.U5.16"],"wire_ids":["9d3c6fe63edb2147"],"label_ids":["e273ea4c0c075546"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO7","aliases":["NO7"],"saved_net_ids":["PULSER:NO7","PULSER:N_R49_2","PULSER:N_R50_2","PULSER:N_R51_2","PULSER:N_R52_2","PULSER:N_R53_2","PULSER:N_R54_1","PULSER:N_R55_1","PULSER:N_R56_1","PULSER:N_R57_1","PULSER:N_R58_1","PULSER:N_R59_1","PULSER:N_R60_1","PULSER:N_R61_1","PULSER:N_R62_1","PULSER:N_R63_1","PULSER:N_R64_1"],"endpoints":["PULSER.R49.1","PULSER.R49.2","PULSER.R50.1","PULSER.R50.2","PULSER.R51.1","PULSER.R51.2","PULSER.R52.1","PULSER.R52.2","PULSER.R53.1","PULSER.R53.2","PULSER.R54.1","PULSER.R54.2","PULSER.R55.1","PULSER.R55.2","PULSER.R56.1","PULSER.R56.2","PULSER.R57.1","PULSER.R57.2","PULSER.R58.1","PULSER.R58.2","PULSER.R59.1","PULSER.R59.2","PULSER.R60.1","PULSER.R60.2","PULSER.R61.1","PULSER.R61.2","PULSER.R62.1","PULSER.R62.2","PULSER.R63.1","PULSER.R63.2","PULSER.R64.1","PULSER.R64.2","PULSER.U1.1","PULSER.U1.3","PULSER.U1.5","PULSER.U1.7","PULSER.U1.11","PULSER.U1.13","PULSER.U1.15","PULSER.U1.17","PULSER.U1.20","PULSER.U1.22","PULSER.U1.24","PULSER.U1.26","PULSER.U1.30","PULSER.U1.32","PULSER.U1.34","PULSER.U1.36","PULSER.U5.18"],"wire_ids":["087f43c7399b26c7","09e963c35aa35e24","1c1ec44a75e33fd6","2a8458a30bc1727c","3fe5b64ccbd9b872","3fe82e196909ab0c","46fc612a0a4f42c4","49e3c0f3ea965a82","65e6b499458c1be6","76582b34aa137bed","923ba802dc239d65","97c2ec538dd51650","ad2a4f25e9fb412a","be527bf6f391513c","c04c7cba8c6fc111","c63758862d41e449","cfedc40ac9eb3349","e0c89728601f7315"],"label_ids":["389fe6d162b8f4c4","69f41a881292d2b8"],"near_pins":[],"near_labels":[],"physical_override":"Owner-confirmed leaf mux solder gaps closed","bridged_components":["PULSER.R49","PULSER.R50","PULSER.R51","PULSER.R52","PULSER.R53","PULSER.R54","PULSER.R55","PULSER.R56","PULSER.R57","PULSER.R58","PULSER.R59","PULSER.R60","PULSER.R61","PULSER.R62","PULSER.R63","PULSER.R64"]}
{"net":"PULSER:NO8","aliases":["NO8"],"saved_net_ids":["PULSER:NO8"],"endpoints":["PULSER.U5.19"],"wire_ids":["7bbdfe4cb6caf577"],"label_ids":["7e930eec2952456f"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO9","aliases":["NO9"],"saved_net_ids":["PULSER:NO9"],"endpoints":["PULSER.U5.21"],"wire_ids":["bdf0db2a2901dbbd"],"label_ids":["2ce74f39c00160db"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO10","aliases":["NO10"],"saved_net_ids":["PULSER:NO10"],"endpoints":["PULSER.U5.23"],"wire_ids":["b71f9596a304342f"],"label_ids":["38798aeadc07f466"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO11","aliases":["NO11"],"saved_net_ids":["PULSER:NO11","PULSER:N_R17_2","PULSER:N_R18_2","PULSER:N_R19_2","PULSER:N_R20_2","PULSER:N_R21_2","PULSER:N_R22_1","PULSER:N_R23_1","PULSER:N_R24_1","PULSER:N_R25_1","PULSER:N_R26_1","PULSER:N_R27_1","PULSER:N_R28_1","PULSER:N_R29_1","PULSER:N_R30_1","PULSER:N_R31_1","PULSER:N_R32_1"],"endpoints":["PULSER.R17.1","PULSER.R17.2","PULSER.R18.1","PULSER.R18.2","PULSER.R19.1","PULSER.R19.2","PULSER.R20.1","PULSER.R20.2","PULSER.R21.1","PULSER.R21.2","PULSER.R22.1","PULSER.R22.2","PULSER.R23.1","PULSER.R23.2","PULSER.R24.1","PULSER.R24.2","PULSER.R25.1","PULSER.R25.2","PULSER.R26.1","PULSER.R26.2","PULSER.R27.1","PULSER.R27.2","PULSER.R28.1","PULSER.R28.2","PULSER.R29.1","PULSER.R29.2","PULSER.R30.1","PULSER.R30.2","PULSER.R31.1","PULSER.R31.2","PULSER.R32.1","PULSER.R32.2","PULSER.U3.1","PULSER.U3.3","PULSER.U3.5","PULSER.U3.7","PULSER.U3.11","PULSER.U3.13","PULSER.U3.15","PULSER.U3.17","PULSER.U3.20","PULSER.U3.22","PULSER.U3.24","PULSER.U3.26","PULSER.U3.30","PULSER.U3.32","PULSER.U3.34","PULSER.U3.36","PULSER.U5.25"],"wire_ids":["0249f0a4a3845708","0737947e3cddd043","0ad0ff4c8d40e51e","11ba7ecd8e3e77ce","2454c3b1c7eb3abb","25b039ee0a8217e0","5179a8ef2cebc220","748e3298ca4ddc86","779eab8fe766db29","80eba04507dfd997","8e471d1d4ad52889","8e7d7f259804950c","d15487e2fcb64d30","d682ca03b250432d","e3586d4f3db59ecf","e8e1d965be00df27","f3f84712c2d34a74","fed3b1776e2a2b7a"],"label_ids":["3df6b4ba2f5b26a5","63bb953416dd486c"],"near_pins":[],"near_labels":[],"physical_override":"Owner-confirmed leaf mux solder gaps closed","bridged_components":["PULSER.R17","PULSER.R18","PULSER.R19","PULSER.R20","PULSER.R21","PULSER.R22","PULSER.R23","PULSER.R24","PULSER.R25","PULSER.R26","PULSER.R27","PULSER.R28","PULSER.R29","PULSER.R30","PULSER.R31","PULSER.R32"]}
{"net":"PULSER:NO12","aliases":["NO12"],"saved_net_ids":["PULSER:NO12"],"endpoints":["PULSER.U5.29"],"wire_ids":["c6d9e8130106d305"],"label_ids":["ed6bf2e6f06edf39"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO13","aliases":["NO13"],"saved_net_ids":["PULSER:NO13"],"endpoints":["PULSER.U5.31"],"wire_ids":["e99edc17d1e3691e"],"label_ids":["dac2e5da2f3095cb"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO14","aliases":["NO14"],"saved_net_ids":["PULSER:NO14"],"endpoints":["PULSER.U5.33"],"wire_ids":["83d6ea01d93f79f5"],"label_ids":["6eee91ff6b4823b7"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:NO15","aliases":["NO15"],"saved_net_ids":["PULSER:NO15"],"endpoints":["PULSER.U5.35"],"wire_ids":["d15abc902f7fd6e4"],"label_ids":["836dc27c4c94b25c"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_C3_1","aliases":[],"saved_net_ids":["PULSER:N_C3_1"],"endpoints":["PULSER.C3.1","PULSER.U6.7"],"wire_ids":["64def5354c08fb15"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_C3_2","aliases":[],"saved_net_ids":["PULSER:N_C3_2"],"endpoints":["PULSER.C3.2","PULSER.C25.1"],"wire_ids":["99264b3aa2e472be"],"label_ids":[],"near_pins":["PULSER.C25.1"],"near_labels":[]}
{"net":"PULSER:N_C9_1","aliases":[],"saved_net_ids":["PULSER:N_C9_1"],"endpoints":["PULSER.C9.1","PULSER.U2.3"],"wire_ids":["cb1f96184a3f5e72"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_C9_2","aliases":[],"saved_net_ids":["PULSER:N_C9_2"],"endpoints":["PULSER.C9.2","PULSER.U2.5"],"wire_ids":["d89d80af787ec544"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_C24_2","aliases":[],"saved_net_ids":["PULSER:N_C24_2"],"endpoints":["PULSER.C24.2","PULSER.C26.2"],"wire_ids":["eb3fc2a58e73d7c5"],"label_ids":[],"near_pins":["PULSER.C24.2"],"near_labels":[]}
{"net":"PULSER:N_C26_1","aliases":[],"saved_net_ids":["PULSER:N_C26_1"],"endpoints":["PULSER.C26.1","PULSER.U6.9"],"wire_ids":["293d1d786470e846"],"label_ids":[],"near_pins":["PULSER.C26.1"],"near_labels":[]}
{"net":"PULSER:N_D1_1","aliases":[],"saved_net_ids":["PULSER:N_D1_1"],"endpoints":["PULSER.D1.1","PULSER.Q1.5","PULSER.Q1.6"],"wire_ids":["19215d27218aa489"],"label_ids":[],"near_pins":["PULSER.Q1.5"],"near_labels":[]}
{"net":"PULSER:N_D1_2","aliases":[],"saved_net_ids":["PULSER:N_D1_2"],"endpoints":["PULSER.D1.2","PULSER.Q1.7","PULSER.Q1.8"],"wire_ids":["3586a91aa5e777ab"],"label_ids":[],"near_pins":["PULSER.Q1.8"],"near_labels":[]}
{"net":"PULSER:N_D2_1","aliases":[],"saved_net_ids":["PULSER:N_D2_1"],"endpoints":["PULSER.D2.1","PULSER.D2.2","PULSER.RF2.5","PULSER.U4.1"],"wire_ids":["6f95420293bd25cf"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_DRIVER_OUT_B","aliases":["N_DRIVER_OUT_B"],"saved_net_ids":["PULSER:N_DRIVER_OUT_B"],"endpoints":["PULSER.C25.2","PULSER.Q1.2"],"wire_ids":["b15a2dc529930aff","f5da917251d71588"],"label_ids":["21d93f8dfcf48915","c6ad6d813b7fc96d"],"near_pins":[],"near_labels":["21d93f8dfcf48915"]}
{"net":"PULSER:N_R2_2","aliases":[],"saved_net_ids":["PULSER:N_R2_2"],"endpoints":["PULSER.R2.2","PULSER.U5.30"],"wire_ids":["6b2ca14b5a05c8e6"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R3_2","aliases":[],"saved_net_ids":["PULSER:N_R3_2"],"endpoints":["PULSER.R3.2","PULSER.U5.32"],"wire_ids":["981e0680dfca4235"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R4_2","aliases":[],"saved_net_ids":["PULSER:N_R4_2"],"endpoints":["PULSER.R4.2","PULSER.U5.34"],"wire_ids":["6a6978eb54670cba"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R5_2","aliases":[],"saved_net_ids":["PULSER:N_R5_2"],"endpoints":["PULSER.R5.2","PULSER.U5.36"],"wire_ids":["95feb593f19191ad"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R6_1","aliases":[],"saved_net_ids":["PULSER:N_R6_1"],"endpoints":["PULSER.R6.1","PULSER.U5.24"],"wire_ids":["81f0982e5a561582"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R7_1","aliases":[],"saved_net_ids":["PULSER:N_R7_1"],"endpoints":["PULSER.R7.1","PULSER.U5.22"],"wire_ids":["6815975a63249df2"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R8_1","aliases":[],"saved_net_ids":["PULSER:N_R8_1"],"endpoints":["PULSER.R8.1","PULSER.U5.20"],"wire_ids":["fcfcf1454af53615"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R10_1","aliases":[],"saved_net_ids":["PULSER:N_R10_1"],"endpoints":["PULSER.R10.1","PULSER.U5.15"],"wire_ids":["07b615bbc245a5b8"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R12_1","aliases":[],"saved_net_ids":["PULSER:N_R12_1"],"endpoints":["PULSER.R12.1","PULSER.U5.11"],"wire_ids":["418f31574439be80"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R13_1","aliases":[],"saved_net_ids":["PULSER:N_R13_1"],"endpoints":["PULSER.R13.1","PULSER.U5.7"],"wire_ids":["f61de168bf2ae230"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R14_1","aliases":[],"saved_net_ids":["PULSER:N_R14_1"],"endpoints":["PULSER.R14.1","PULSER.U5.5"],"wire_ids":["645ab48804a35902"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R15_1","aliases":[],"saved_net_ids":["PULSER:N_R15_1"],"endpoints":["PULSER.R15.1","PULSER.U5.3"],"wire_ids":["9013bfb8597956b0"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R16_1","aliases":[],"saved_net_ids":["PULSER:N_R16_1"],"endpoints":["PULSER.R16.1","PULSER.U5.1"],"wire_ids":["16e10ed83c03add8"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R65_2","aliases":[],"saved_net_ids":["PULSER:N_R65_2"],"endpoints":["PULSER.R65.2","PULSER.U14.2"],"wire_ids":["1d7056059d264625"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R66_2","aliases":[],"saved_net_ids":["PULSER:N_R66_2"],"endpoints":["PULSER.R66.2","PULSER.U13.1"],"wire_ids":["3880a1223a23ff9e"],"label_ids":[],"near_pins":["PULSER.U13.1"],"near_labels":[]}
{"net":"PULSER:N_R67_2","aliases":[],"saved_net_ids":["PULSER:N_R67_2"],"endpoints":["PULSER.R67.2","PULSER.U11.1"],"wire_ids":["0b9bdb9e5a7a552f"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:N_R68_2","aliases":[],"saved_net_ids":["PULSER:N_R68_2"],"endpoints":["PULSER.R68.2","PULSER.U12.2"],"wire_ids":["0e2804aac8beff03"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"PULSER:PULSE_OUT","aliases":["PULSE_OUT"],"saved_net_ids":["PULSER:PULSE_OUT"],"endpoints":["PULSER.D1.3","PULSER.R2.1","PULSER.R3.1","PULSER.R4.1","PULSER.R5.1","PULSER.R6.2","PULSER.R7.2","PULSER.R8.2","PULSER.R10.2","PULSER.R12.2","PULSER.R13.2","PULSER.R14.2","PULSER.R15.2","PULSER.R16.2","PULSER.U4.3","PULSER.U5.13","PULSER.U5.17","PULSER.U5.26"],"wire_ids":["0e452ba86b74b174","b39d45a44379808b","f26b7760c66c7892"],"label_ids":["1114fe18305f5748","1c9f4f2c716a1472","a4647d4eaea55b87"],"near_pins":[],"near_labels":["1c9f4f2c716a1472"]}
{"net":"PULSER:P_DRIVER_OUT_A","aliases":["P_DRIVER_OUT_A"],"saved_net_ids":["PULSER:P_DRIVER_OUT_A"],"endpoints":["PULSER.C24.1","PULSER.Q1.4"],"wire_ids":["05f762b202b4b733","23566d31402c6f99"],"label_ids":["10299b216fa53157","a76e410d968803e6"],"near_pins":[],"near_labels":["10299b216fa53157"]}
{"net":"PULSER:SIG1_IN","aliases":["SIG1_IN"],"saved_net_ids":["PULSER:SIG1_IN"],"endpoints":["PULSER.CN1.15","PULSER.U6.1"],"wire_ids":["7642c257dc89a714","a91900fd296d56f9"],"label_ids":["3b2d46ee97a7c3f7","aed62a37f087b7bd"],"near_pins":[],"near_labels":[]}
{"net":"PULSER:SIG2_IN","aliases":["SIG2_IN"],"saved_net_ids":["PULSER:SIG2_IN"],"endpoints":["PULSER.CN1.11","PULSER.U6.3"],"wire_ids":["914a6e828fbc480d","b9cb9cfab047d5ec"],"label_ids":["b4324b9a9a4a055a","be189672db4e7906"],"near_pins":["PULSER.U6.3"],"near_labels":[]}
```

### AFE net records

```jsonl
{"net":"AFE:1.2V VREF","aliases":["1.2V VREF"],"saved_net_ids":["AFE:1.2V VREF"],"endpoints":["AFE.C26.1","AFE.C43.1","AFE.U3.10","AFE.U4.6"],"wire_ids":["175b69dd87f864c6","e49ff9965b92ed34"],"label_ids":["50a8e3e8f8aa29ae","7b6b1d078085b84c"],"near_pins":[],"near_labels":[]}
{"net":"AFE:5V-USB","aliases":["5V-USB"],"saved_net_ids":["AFE:5V-USB"],"endpoints":["AFE.C54.1","AFE.C68.2","AFE.CN2.2","AFE.CN2.4","AFE.CN2.6","AFE.CN2.8","AFE.CN2.10","AFE.CN2.12","AFE.CN2.14","AFE.CN2.16","AFE.L3.1"],"wire_ids":["11ec6c558ebc2d4a","5109809c8044b7a7"],"label_ids":["1afe4edbe45a06ab","a4cfefccdc49c51c"],"near_pins":[],"near_labels":["1afe4edbe45a06ab"]}
{"net":"AFE:33","aliases":["33"],"saved_net_ids":["AFE:33"],"endpoints":["AFE.CN1.3","AFE.U6.33"],"wire_ids":["8e89f8262553575e","ed1b6730af4df555"],"label_ids":["4f0f73ca6127b5b5","70cc4be9e4bc3801"],"near_pins":[],"near_labels":["4f0f73ca6127b5b5"]}
{"net":"AFE:35","aliases":["35"],"saved_net_ids":["AFE:35"],"endpoints":["AFE.CN1.7","AFE.U6.35"],"wire_ids":["0423eef546dc3347","7d1e3415dc45a950"],"label_ids":["84425a69e67f194d","b9bcc189770da928"],"near_pins":["AFE.U6.35"],"near_labels":[]}
{"net":"AFE:39","aliases":["39"],"saved_net_ids":["AFE:39"],"endpoints":["AFE.CN1.11","AFE.U6.39"],"wire_ids":["1bbaa544f69f0550","9e87f093cdb3ef4e"],"label_ids":["2dc38c71dac1efbf","cd37a28dff509811"],"near_pins":[],"near_labels":["cd37a28dff509811"]}
{"net":"AFE:41","aliases":["41"],"saved_net_ids":["AFE:41"],"endpoints":["AFE.U6.41"],"wire_ids":["5517f21970f5b083"],"label_ids":["5eac4477240f26b2"],"near_pins":[],"near_labels":["5eac4477240f26b2"]}
{"net":"AFE:51","aliases":["51"],"saved_net_ids":["AFE:51"],"endpoints":["AFE.CN1.2","AFE.U6.51"],"wire_ids":["2709ec3422851de9","dbea6c34a987a03c"],"label_ids":["53b2a5c76ef379db","eb3913c036b8da21"],"near_pins":[],"near_labels":["eb3913c036b8da21"]}
{"net":"AFE:53","aliases":["53"],"saved_net_ids":["AFE:53"],"endpoints":["AFE.CN1.4","AFE.U6.53"],"wire_ids":["65507edbc7f5cc56","c07b504b4073f5ce"],"label_ids":["1db95708130a3ac3","de5a673da1b9401b"],"near_pins":[],"near_labels":["1db95708130a3ac3"]}
{"net":"AFE:57","aliases":["57"],"saved_net_ids":["AFE:57"],"endpoints":["AFE.CN1.6","AFE.U6.57"],"wire_ids":["967c4274a7ee0986","cba9fd24b16aae3b"],"label_ids":["d7ed1a1f6410e486","ec5f4845b5333f44"],"near_pins":[],"near_labels":["d7ed1a1f6410e486"]}
{"net":"AFE:59","aliases":["59"],"saved_net_ids":["AFE:59"],"endpoints":["AFE.CN1.10","AFE.U6.59"],"wire_ids":["13560946ca6c4a1c","7f80fda5d2469b40"],"label_ids":["028a500d9adebd7c","321b3061c6be6ab2"],"near_pins":[],"near_labels":["028a500d9adebd7c"]}
{"net":"AFE:63","aliases":["63"],"saved_net_ids":["AFE:63"],"endpoints":["AFE.CN1.14","AFE.U6.63"],"wire_ids":["86d7d659206196db","c19dbbabfdc0bf53"],"label_ids":["29b4e5dd6249d1f4","a5d44cbf1b34ebbf"],"near_pins":[],"near_labels":["a5d44cbf1b34ebbf"]}
{"net":"AFE:65","aliases":["65"],"saved_net_ids":["AFE:65"],"endpoints":["AFE.CN1.16","AFE.U6.65"],"wire_ids":["730fc4b03be329a0","d3e0408852425ae1"],"label_ids":["8131bcf0334ba87c","b3637b26a24b6a0d"],"near_pins":[],"near_labels":[]}
{"net":"AFE:+1.8_LVDD","aliases":["+1.8_LVDD"],"saved_net_ids":["AFE:+1.8_LVDD"],"endpoints":["AFE.C18.2","AFE.C25.1","AFE.C47.2","AFE.C48.2","AFE.C49.2","AFE.C62.2","AFE.CN1.19","AFE.L11.2","AFE.U1.N6","AFE.U1.N7","AFE.U1.P5","AFE.U4.3","AFE.U4.4"],"wire_ids":["1961a71f5ad763eb","4a5091bd5b29aa9e","5ff0bd15661ae9e3","e4638","e8969"],"label_ids":["2e870d61167e58dd","3187860a8efb98f8","cfb801b6f8fa1727","e8985","f22692bf0029594b"],"near_pins":[],"near_labels":[]}
{"net":"AFE:+3.3_VDD","aliases":["+3.3_VDD"],"saved_net_ids":["AFE:+3.3_VDD"],"endpoints":["AFE.C7.2","AFE.C8.2","AFE.C9.2","AFE.C10.2","AFE.C11.2","AFE.C12.2","AFE.C13.2","AFE.C14.2","AFE.C15.2","AFE.C16.2","AFE.C17.2","AFE.C22.2","AFE.C23.2","AFE.C24.2","AFE.C40.2","AFE.C41.2","AFE.C56.2","AFE.C57.2","AFE.C58.2","AFE.C59.2","AFE.C60.2","AFE.C61.2","AFE.C65.2","AFE.CN1.17","AFE.L2.2","AFE.R7.2","AFE.R8.1","AFE.R12.2","AFE.U1.C2","AFE.U1.C5","AFE.U1.C8","AFE.U1.D5","AFE.U1.G2","AFE.U1.G8","AFE.U1.J2","AFE.U1.J7","AFE.U1.K3","AFE.U1.K5","AFE.U1.K6","AFE.U1.K7","AFE.U1.L2","AFE.U1.L8","AFE.U1.L9","AFE.U3.8","AFE.U7.1","AFE.U7.6"],"wire_ids":["0b71960938b426b3","1feb64a1a7f9145b","2823ef5d5ba8bf93","341edb10565ef3ef","391e3163cb9de1cc","71ca34af9cb02866","71e55d50d6867887","b4af8cdeea836e80","ce2a2c7e54e60ae4","d531349091868c76","e1d5510facb938f5","e3795"],"label_ids":["0918391338ce4fb1","1bd08239e5098ac2","42bc6b6137360a41","4f35a0143e86e0c1","538e4de8ae520c02","5613a64590943de3","5a260abebd0391d2","93553fe63e524cdd","953c9ebb1943e4a5","ab8bbe2bed0d7f78","d24e530a700a760f","d41a86450f5361c8"],"near_pins":["AFE.R8.1"],"near_labels":["5613a64590943de3"]}
{"net":"AFE:+5_VDD","aliases":["+5_VDD"],"saved_net_ids":["AFE:+5_VDD"],"endpoints":["AFE.C19.2","AFE.C55.2","AFE.C64.2","AFE.C69.2","AFE.C77.2","AFE.CN1.20","AFE.L1.1","AFE.L7.2","AFE.L10.1","AFE.U1.E2","AFE.U1.E8"],"wire_ids":["00fb1ea216a9f817","474abdc3a1771ff5","56e0e294152a4891","d366766c21abcbb7","e4007","e8967"],"label_ids":["59dc3e44db11befb","b3ce91c5a8338465","be83870342e604f7","c34547ab2cd71e17","ed1a701c595773c1","edb9feea20220489"],"near_pins":["AFE.U1.E8"],"near_labels":["be83870342e604f7"]}
{"net":"AFE:ADS_RST","aliases":["ADS_RST"],"saved_net_ids":["AFE:ADS_RST"],"endpoints":["AFE.R12.1","AFE.U1.H9","AFE.U6.70"],"wire_ids":["69f7e81732db2760","ee8cc476c7686ec4"],"label_ids":["9943beb2e36cdfcd","c246fc8f588cb897"],"near_pins":["AFE.U6.70"],"near_labels":[]}
{"net":"AFE:CLKM","aliases":["CLKM"],"saved_net_ids":["AFE:CLKM"],"endpoints":["AFE.C66.1","AFE.R2.1","AFE.U1.K1"],"wire_ids":["adc11537c36258d0","c053730fe79431c1"],"label_ids":["5190cde3c8927697","f7fe702c41c01dad"],"near_pins":[],"near_labels":["5190cde3c8927697"]}
{"net":"AFE:CLKP","aliases":["CLKP"],"saved_net_ids":["AFE:CLKP"],"endpoints":["AFE.C53.1","AFE.R2.2","AFE.U1.L1"],"wire_ids":["095ee24b2082f716","c5e4a98c36ba9fff"],"label_ids":["0d1b000be7e516eb","846acb327f5d2aa6"],"near_pins":[],"near_labels":[]}
{"net":"AFE:CM","aliases":["CM"],"saved_net_ids":["AFE:CM"],"endpoints":["AFE.C52.2","AFE.U1.K8"],"wire_ids":["7858d04f37cb3fd6","dc06cc6adc18ffa4"],"label_ids":["c3c65a933dda15e1","d3c7e410c7c93861"],"near_pins":[],"near_labels":[]}
{"net":"AFE:CS","aliases":["CS"],"saved_net_ids":["AFE:CS"],"endpoints":["AFE.R8.2","AFE.U1.H7","AFE.U6.76"],"wire_ids":["08ec274149f4fa20","fb851ff48fceea11"],"label_ids":["82b1b4c431eec1c7","9319ae78e95207e9"],"near_pins":["AFE.U6.76"],"near_labels":[]}
{"net":"AFE:DAC_SCLK","aliases":["DAC_SCLK"],"saved_net_ids":["AFE:DAC_SCLK"],"endpoints":["AFE.R10.2","AFE.U3.6"],"wire_ids":["30e73a2ff1e1c06f","dd39de2ea683e7f4"],"label_ids":["134c6d3c298394df","21cb68c0468e27c6"],"near_pins":[],"near_labels":[]}
{"net":"AFE:DAC_SDA","aliases":["DAC_SDA"],"saved_net_ids":["AFE:DAC_SDA"],"endpoints":["AFE.R11.2","AFE.U3.7"],"wire_ids":["824f1728b0a0f65a","90bb724c5a94b628"],"label_ids":["0f32d8ff5d9d52c5","d6206be4cca761b9"],"near_pins":[],"near_labels":[]}
{"net":"AFE:DAC_SYNC","aliases":["DAC_SYNC"],"saved_net_ids":["AFE:DAC_SYNC"],"endpoints":["AFE.R7.1","AFE.R9.1","AFE.U3.9"],"wire_ids":["2213efafa03e48b3","47531076eb8747c0"],"label_ids":["6efbc48d1267f47b","df33ab11cde77016"],"near_pins":[],"near_labels":[]}
{"net":"AFE:FCLKM","aliases":["FCLKM"],"saved_net_ids":["AFE:FCLKM"],"endpoints":["AFE.R14.2","AFE.U1.N8","AFE.U5.46"],"wire_ids":["4bad4a8c2dffbd5c","ca3fd6b3791a0305"],"label_ids":["4326519a371ccab2","4fac5a115f3a8c11"],"near_pins":["AFE.U5.46"],"near_labels":[]}
{"net":"AFE:FCLKP","aliases":["FCLKP"],"saved_net_ids":["AFE:FCLKP"],"endpoints":["AFE.R14.1","AFE.U1.N9","AFE.U5.48"],"wire_ids":["5e86deab0bcc5cd8","82235c2e1fa88d97"],"label_ids":["4c35363d28641b69","eafb62157dbb8628"],"near_pins":["AFE.U5.48"],"near_labels":[]}
{"net":"AFE:GND","aliases":["GND"],"saved_net_ids":["AFE:GND"],"endpoints":["AFE.C1.2","AFE.C3.2","AFE.C4.2","AFE.C5.1","AFE.C6.1","AFE.C7.1","AFE.C8.1","AFE.C9.1","AFE.C10.1","AFE.C11.1","AFE.C12.1","AFE.C13.1","AFE.C14.1","AFE.C15.1","AFE.C16.1","AFE.C17.1","AFE.C18.1","AFE.C19.1","AFE.C20.1","AFE.C21.1","AFE.C22.1","AFE.C23.1","AFE.C24.1","AFE.C25.2","AFE.C26.2","AFE.C27.2","AFE.C28.2","AFE.C29.2","AFE.C30.2","AFE.C31.2","AFE.C32.2","AFE.C33.2","AFE.C34.2","AFE.C35.1","AFE.C36.2","AFE.C37.1","AFE.C38.2","AFE.C39.1","AFE.C40.1","AFE.C41.1","AFE.C42.2","AFE.C43.2","AFE.C44.1","AFE.C45.1","AFE.C46.1","AFE.C47.1","AFE.C48.1","AFE.C49.1","AFE.C50.1","AFE.C51.1","AFE.C52.1","AFE.C54.2","AFE.C55.1","AFE.C56.1","AFE.C57.1","AFE.C58.1","AFE.C59.1","AFE.C60.1","AFE.C61.1","AFE.C62.1","AFE.C63.1","AFE.C64.1","AFE.C65.1","AFE.C67.2","AFE.C68.1","AFE.C69.1","AFE.C70.2","AFE.C71.2","AFE.C72.1","AFE.C73.1","AFE.C74.1","AFE.C75.1","AFE.C76.1","AFE.C77.1","AFE.CN1.1","AFE.CN1.5","AFE.CN1.8","AFE.CN1.9","AFE.CN1.12","AFE.CN1.13","AFE.CN1.18","AFE.CN2.17","AFE.CN2.18","AFE.CN2.19","AFE.CN2.20","AFE.CN2.21","AFE.CN2.22","AFE.CN2.23","AFE.CN2.24","AFE.CN2.25","AFE.CN2.26","AFE.CN2.27","AFE.CN2.28","AFE.CN2.38","AFE.CN2.40","AFE.CN2.51","AFE.CN2.52","AFE.CN2.53","AFE.CN2.54","AFE.D1.3","AFE.R13.1","AFE.R15.1","AFE.RF1.1","AFE.RF1.2","AFE.RF1.3","AFE.RF1.4","AFE.U1.A5","AFE.U1.C3","AFE.U1.C4","AFE.U1.C6","AFE.U1.C7","AFE.U1.D3","AFE.U1.D4","AFE.U1.D6","AFE.U1.D7","AFE.U1.E4","AFE.U1.E5","AFE.U1.E6","AFE.U1.F4","AFE.U1.F5","AFE.U1.F6","AFE.U1.G4","AFE.U1.G5","AFE.U1.G6","AFE.U1.H1","AFE.U1.J1","AFE.U1.J4","AFE.U1.J5","AFE.U1.J6","AFE.U1.L3","AFE.U1.L4","AFE.U1.L5","AFE.U1.L6","AFE.U1.L7","AFE.U1.M3","AFE.U1.M4","AFE.U1.M5","AFE.U1.M6","AFE.U1.M7","AFE.U1.N3","AFE.U1.N4","AFE.U1.N5","AFE.U1.R5","AFE.U2.3","AFE.U2.6","AFE.U3.3","AFE.U4.1","AFE.U4.2","AFE.U5.1","AFE.U5.2","AFE.U5.7","AFE.U5.8","AFE.U5.13","AFE.U5.14","AFE.U5.19","AFE.U5.20","AFE.U5.25","AFE.U5.26","AFE.U5.31","AFE.U5.32","AFE.U5.37","AFE.U5.38","AFE.U5.43","AFE.U5.44","AFE.U5.49","AFE.U5.50","AFE.U5.55","AFE.U5.56","AFE.U5.61","AFE.U5.62","AFE.U5.67","AFE.U5.68","AFE.U5.73","AFE.U5.74","AFE.U5.79","AFE.U5.80","AFE.U5.81","AFE.U5.82","AFE.U6.1","AFE.U6.2","AFE.U6.7","AFE.U6.8","AFE.U6.13","AFE.U6.14","AFE.U6.19","AFE.U6.20","AFE.U6.25","AFE.U6.26","AFE.U6.31","AFE.U6.32","AFE.U6.37","AFE.U6.38","AFE.U6.43","AFE.U6.44","AFE.U6.49","AFE.U6.50","AFE.U6.55","AFE.U6.56","AFE.U6.61","AFE.U6.62","AFE.U6.67","AFE.U6.68","AFE.U6.73","AFE.U6.74","AFE.U6.79","AFE.U6.80","AFE.U6.81","AFE.U6.82","AFE.U7.3","AFE.U7.7","AFE.U12.3","AFE.U12.6"],"wire_ids":["049e658fde488d6f","0d983cbd3681a6a8","1387472fb3cf5688","190bfc886bbbc20e","1c04eb3f3d94924b","20ef526e6dbb467d","22deeadc992285a7","3026760e0159ab86","321331f1fe2758e1","3cd95a451b63378f","3d7be7c9721e6339","41eb3e4b2f8d244c","54e591708c0dad03","5a35b25dd3462a0f","5da886bc7539bc12","68072259f9b0ef98","6cd63ca9a29cc60e","70756d56b564363b","717ecf41905170eb","72647b51fbe67f4b","7ea3fe8fc8e324a8","82f8205f2da2342a","8e54544e3408e536","97b90c61affe60ab","9a7a7137c50afa01","c394cc1f3527fed0","cab2172425feff49","db3abf43d3b0ab32","dc4f5097ac8f7a73","e3807","e3b65c3e200cfa27","e4000","e4639","e66003159453965a","e7a806ad0c5de4ad","e8949","e8954","f3c39be39aba359d","fc53fe79d7a73e6b"],"label_ids":["03124abeb38d0825","08ec9c12cf30cc94","0b646f463ec7ba3c","0c7779a17898d9a4","0fff3da6e6de1d70","1464e0f55f0d7ed9","36fd95a1261de66c","3b7011c3008f6847","451da65ff22c3353","49cfb170e095cdab","4dbbeecdbbdcb992","4f8649d6ae89b17c","6bfb791ee5d471ff","6c19378c277fc75c","70dcf418ee0bbfae","79245b8ab2d9554c","85ec5a3ae13a0441","86ef6d1d830391d7","96629d1e8f583879","aa9ccd9e0e3bec5b","b398e8e59bdc5b1e","b803eeecc2c8bba2","c649baf0489dbd37","c738d6385e5c3065","c760e74e4cc4a7a1","c89902787d160219","d2eaaf05d77584aa","d4928831d89589b9","df7d1b4f235dea3d","e1c294c7681de064","e4415","e4435","e4628","e8632","e8642","edc6a27b3e880991","eec8953c2bc4578c","ef83842a733930e7","f2bcb848fdc1ef53"],"near_pins":["AFE.U1.E5","AFE.U1.N4","AFE.U5.1","AFE.U5.2","AFE.U5.7","AFE.U5.8","AFE.U5.13","AFE.U5.14","AFE.U5.19","AFE.U5.20","AFE.U5.25","AFE.U5.26","AFE.U5.31","AFE.U5.32","AFE.U5.37","AFE.U5.38","AFE.U5.43","AFE.U5.44","AFE.U5.49","AFE.U5.50","AFE.U5.55","AFE.U5.56","AFE.U5.61","AFE.U5.62","AFE.U5.67","AFE.U5.68","AFE.U5.73","AFE.U5.74","AFE.U5.79","AFE.U5.80","AFE.U6.1","AFE.U6.2","AFE.U6.7","AFE.U6.8","AFE.U6.13","AFE.U6.14","AFE.U6.19","AFE.U6.20","AFE.U6.25","AFE.U6.26","AFE.U6.31","AFE.U6.32","AFE.U6.37","AFE.U6.38","AFE.U6.43","AFE.U6.44","AFE.U6.49","AFE.U6.50","AFE.U6.55","AFE.U6.56","AFE.U6.61","AFE.U6.62","AFE.U6.67","AFE.U6.68","AFE.U6.73","AFE.U6.74","AFE.U6.79","AFE.U6.80"],"near_labels":[]}
{"net":"AFE:IN1","aliases":["IN1"],"saved_net_ids":["AFE:IN1"],"endpoints":["AFE.C2.2","AFE.U1.A1"],"wire_ids":["1707c4dd3269b114","de5b3fb05ffefe6b"],"label_ids":["0373ed80ed1ffb78","89f8936d2722eeb0"],"near_pins":[],"near_labels":[]}
{"net":"AFE:LCLKM","aliases":["LCLKM"],"saved_net_ids":["AFE:LCLKM"],"endpoints":["AFE.R4.2","AFE.U1.N2","AFE.U5.45"],"wire_ids":["1bab616de00daec1","2a1be363ab921a62"],"label_ids":["27d8fb298a1bc3e5","3b347fdb58771177"],"near_pins":["AFE.U5.45"],"near_labels":[]}
{"net":"AFE:LCLKP","aliases":["LCLKP"],"saved_net_ids":["AFE:LCLKP"],"endpoints":["AFE.R4.1","AFE.U1.N1","AFE.U5.47"],"wire_ids":["c19c9c72e457682a","cce64000c91d91bb"],"label_ids":["7ddcbd352e72a9bd","c6af6dba64cbc798"],"near_pins":["AFE.U5.47"],"near_labels":[]}
{"net":"AFE:N_C2_1","aliases":[],"saved_net_ids":["AFE:N_C2_1"],"endpoints":["AFE.C2.1","AFE.D1.1","AFE.D1.2","AFE.R6.2"],"wire_ids":["974066361a13989a"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C3_1","aliases":[],"saved_net_ids":["AFE:N_C3_1"],"endpoints":["AFE.C3.1","AFE.C5.2","AFE.L1.2","AFE.U2.1","AFE.U2.2"],"wire_ids":["9226c3e4eb45fcbd"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C4_1","aliases":[],"saved_net_ids":["AFE:N_C4_1"],"endpoints":["AFE.C4.1","AFE.L2.1","AFE.U2.4"],"wire_ids":["aff96884b56c028b"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C6_2","aliases":[],"saved_net_ids":["AFE:N_C6_2"],"endpoints":["AFE.C6.2","AFE.U2.5"],"wire_ids":["3713c335213cd446"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C38_1","aliases":[],"saved_net_ids":["AFE:N_C38_1"],"endpoints":["AFE.C38.1","AFE.U4.5"],"wire_ids":["a72e0a76c19cf02e"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C53_2","aliases":[],"saved_net_ids":["AFE:N_C53_2"],"endpoints":["AFE.C53.2","AFE.U7.4"],"wire_ids":["af5a6a28a1788c8c"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C66_2","aliases":[],"saved_net_ids":["AFE:N_C66_2"],"endpoints":["AFE.C66.2","AFE.U7.5"],"wire_ids":["61eb1a2907ed0a9d"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C67_1","aliases":[],"saved_net_ids":["AFE:N_C67_1"],"endpoints":["AFE.C67.1","AFE.C74.2","AFE.C75.2","AFE.C76.2","AFE.L3.2","AFE.L7.1"],"wire_ids":["0b66adbaa76ce964"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C70_1","aliases":[],"saved_net_ids":["AFE:N_C70_1"],"endpoints":["AFE.C70.1","AFE.C72.2","AFE.L10.2","AFE.U12.1","AFE.U12.2"],"wire_ids":["e8959"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C71_1","aliases":[],"saved_net_ids":["AFE:N_C71_1"],"endpoints":["AFE.C71.1","AFE.L11.1","AFE.U12.4"],"wire_ids":["e8972"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_C73_2","aliases":[],"saved_net_ids":["AFE:N_C73_2"],"endpoints":["AFE.C73.2","AFE.U12.5"],"wire_ids":["e8956"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_R1_2","aliases":[],"saved_net_ids":["AFE:N_R1_2"],"endpoints":["AFE.R1.2","AFE.U6.78"],"wire_ids":["ebad74c143db1ef9"],"label_ids":[],"near_pins":["AFE.U6.78"],"near_labels":[]}
{"net":"AFE:N_R5_2","aliases":[],"saved_net_ids":["AFE:N_R5_2"],"endpoints":["AFE.R5.2","AFE.U6.72"],"wire_ids":["f666a90c20661d5f"],"label_ids":[],"near_pins":["AFE.U6.72"],"near_labels":[]}
{"net":"AFE:N_R6_1","aliases":[],"saved_net_ids":["AFE:N_R6_1"],"endpoints":["AFE.R6.1","AFE.R13.2","AFE.RF1.5"],"wire_ids":["109ea93ad6aad2ad"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_R9_2","aliases":[],"saved_net_ids":["AFE:N_R9_2"],"endpoints":["AFE.R9.2","AFE.U5.77"],"wire_ids":["494168cb2fe8b3e3"],"label_ids":[],"near_pins":["AFE.U5.77"],"near_labels":[]}
{"net":"AFE:N_R10_1","aliases":[],"saved_net_ids":["AFE:N_R10_1"],"endpoints":["AFE.R10.1","AFE.U5.76"],"wire_ids":["ffcdb0ebf723ffe5"],"label_ids":[],"near_pins":["AFE.U5.76"],"near_labels":[]}
{"net":"AFE:N_R11_1","aliases":[],"saved_net_ids":["AFE:N_R11_1"],"endpoints":["AFE.R11.1","AFE.U5.78"],"wire_ids":["c43429ac333b0958"],"label_ids":[],"near_pins":["AFE.U5.78"],"near_labels":[]}
{"net":"AFE:N_R15_2","aliases":[],"saved_net_ids":["AFE:N_R15_2"],"endpoints":["AFE.R15.2","AFE.U1.K9"],"wire_ids":["b3b3fb1ef2c8cf1b"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:N_R16_2","aliases":[],"saved_net_ids":["AFE:N_R16_2"],"endpoints":["AFE.R16.2","AFE.U3.2"],"wire_ids":["8a230d2793f1e8ca"],"label_ids":[],"near_pins":[],"near_labels":[]}
{"net":"AFE:OUT1M","aliases":["OUT1M"],"saved_net_ids":["AFE:OUT1M"],"endpoints":["AFE.R17.2","AFE.U1.R4","AFE.U5.51"],"wire_ids":["1d60e2f5db216a7d","39882b0d5b40ef7d"],"label_ids":["06fb3c7498c938f7","6c7d3e6fba3d1628"],"near_pins":["AFE.U5.51"],"near_labels":[]}
{"net":"AFE:OUT1P","aliases":["OUT1P"],"saved_net_ids":["AFE:OUT1P"],"endpoints":["AFE.R17.1","AFE.U1.P4","AFE.U5.53"],"wire_ids":["92c404bf79e0079b","f732b3e0e8a90fee"],"label_ids":["170de9342be0836e","dd7897215ec0e60a"],"near_pins":["AFE.U1.P4","AFE.U5.53"],"near_labels":[]}
{"net":"AFE:REFB","aliases":["REFB"],"saved_net_ids":["AFE:REFB"],"endpoints":["AFE.C44.2","AFE.C63.2","AFE.U1.J9"],"wire_ids":["9bc2b9312129257c","cf51dc5968533695"],"label_ids":["76c162f0b8c51220","b68c6b8b4407822e"],"near_pins":[],"near_labels":[]}
{"net":"AFE:REFT","aliases":["REFT"],"saved_net_ids":["AFE:REFT"],"endpoints":["AFE.C45.2","AFE.C46.2","AFE.U1.J8"],"wire_ids":["62f24bf2c7d29d86","bd9e4d54ee73e75b"],"label_ids":["1fed4b67221ec99a","873cbb2be0f2e1b5"],"near_pins":[],"near_labels":[]}
{"net":"AFE:RST","aliases":["RST"],"saved_net_ids":["AFE:RST"],"endpoints":["AFE.U1.H4","AFE.U1.H5"],"wire_ids":["48a90f4629731d90"],"label_ids":["66ab5a8a42723d40"],"near_pins":[],"near_labels":[]}
{"net":"AFE:SCLK","aliases":["SCLK"],"saved_net_ids":["AFE:SCLK"],"endpoints":["AFE.R1.1","AFE.U1.H6"],"wire_ids":["58210c78dab4cd8b","e61a96449e00b9bd"],"label_ids":["4b2a1390654fc347","ecac92be4953c516"],"near_pins":[],"near_labels":[]}
{"net":"AFE:SDATA","aliases":["SDATA"],"saved_net_ids":["AFE:SDATA"],"endpoints":["AFE.R5.1","AFE.U1.H8"],"wire_ids":["571c53055a5cb228","b802674a71fd0ba2"],"label_ids":["34baed3ce36d2795","a2250bd2253571e2"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VB1","aliases":["VB1"],"saved_net_ids":["AFE:VB1"],"endpoints":["AFE.C20.2","AFE.U1.F2"],"wire_ids":["83634d5f649352e8","c0187d9c3ec28660"],"label_ids":["926f576bdb6231d0","ee8295fea585dc2c"],"near_pins":["AFE.U1.F2"],"near_labels":[]}
{"net":"AFE:VB2","aliases":["VB2"],"saved_net_ids":["AFE:VB2"],"endpoints":["AFE.C34.1","AFE.U1.D8"],"wire_ids":["8d94aa66156f5076","c04002bb7321c3d1"],"label_ids":["77c7c6044af429aa","badb428a531a9f7a"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VB3","aliases":["VB3"],"saved_net_ids":["AFE:VB3"],"endpoints":["AFE.C35.2","AFE.U1.E3"],"wire_ids":["4c9f3d2c7a7cab59","f0bea5b071839ea1"],"label_ids":["4f296ad6fab37b90","f88de18ec8eb5086"],"near_pins":["AFE.U1.E3"],"near_labels":[]}
{"net":"AFE:VB4","aliases":["VB4"],"saved_net_ids":["AFE:VB4"],"endpoints":["AFE.C36.1","AFE.U1.E7"],"wire_ids":["8cf7644ce3f5bac2","ba83fe487c9cf116"],"label_ids":["3d0e985b8d4ba11a","57bc23c221a570b5"],"near_pins":["AFE.U1.E7"],"near_labels":[]}
{"net":"AFE:VB5","aliases":["VB5"],"saved_net_ids":["AFE:VB5"],"endpoints":["AFE.C37.2","AFE.U1.F3"],"wire_ids":["0434bfcd02aada47","a3e5f3deae4cce5c"],"label_ids":["80e6b337d45a48e9","cbaa7a34937e5a4c"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VB6","aliases":["VB6"],"saved_net_ids":["AFE:VB6"],"endpoints":["AFE.C39.2","AFE.U1.F8"],"wire_ids":["92be1f86e94051ff","9a99d9ef12578fe4"],"label_ids":["7ae5de333b2385de","c8877aa43ed6b86a"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL1","aliases":["VBL1"],"saved_net_ids":["AFE:VBL1"],"endpoints":["AFE.C1.1","AFE.U1.B1"],"wire_ids":["19a8f13dc5502bad","969966cd3b043df4"],"label_ids":["3751a1f6df5bc3b4","d64283c7db2c1ec1"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL2","aliases":["VBL2"],"saved_net_ids":["AFE:VBL2"],"endpoints":["AFE.C27.1","AFE.U1.B2"],"wire_ids":["37212bf7b740b8d0","5fc9e0600f012f7a"],"label_ids":["394b3351b956b378","5b1d39bf48ecfb76"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL3","aliases":["VBL3"],"saved_net_ids":["AFE:VBL3"],"endpoints":["AFE.C28.1","AFE.U1.B3"],"wire_ids":["0937afc6f63aecfe","287fe2cfe2ecfbf6"],"label_ids":["64237038bf7d2597","ea024fe5c1698274"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL4","aliases":["VBL4"],"saved_net_ids":["AFE:VBL4"],"endpoints":["AFE.C29.1","AFE.U1.B4"],"wire_ids":["0970f4d2fb251698","5825d339495c29eb"],"label_ids":["9713880b820526ba","a56d46e4054fe1f1"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL5","aliases":["VBL5"],"saved_net_ids":["AFE:VBL5"],"endpoints":["AFE.C33.1","AFE.U1.B9"],"wire_ids":["491ce41745745f15","8de5f9c18eabbda9"],"label_ids":["bb3c1f6f1560bf51","daab0dc8ccfebb8d"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL6","aliases":["VBL6"],"saved_net_ids":["AFE:VBL6"],"endpoints":["AFE.C32.1","AFE.U1.B8"],"wire_ids":["0bed7cd57e5a74af","5e3ac4c503009fc2"],"label_ids":["419ac9bc213b9e35","4f7ea30f455acf82"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL7","aliases":["VBL7"],"saved_net_ids":["AFE:VBL7"],"endpoints":["AFE.C31.1","AFE.U1.B7"],"wire_ids":["0216e24a21059a38","0f42f00fafc6b3fe"],"label_ids":["16c04fa26dd9d34a","5fb2e8e026db010c"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VBL8","aliases":["VBL8"],"saved_net_ids":["AFE:VBL8"],"endpoints":["AFE.C30.1","AFE.U1.B6"],"wire_ids":["95882ca1a9eb6126","e523dba1dcef7852"],"label_ids":["48f19b7d74734992","5b9da1195665e25d"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VCM","aliases":["VCM"],"saved_net_ids":["AFE:VCM"],"endpoints":["AFE.C21.2","AFE.U1.G3"],"wire_ids":["3995a3923dd85c60","4c7598cee4f2e0fb"],"label_ids":["643b1f1b97664c7e","c7e84cd03f252110"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VCNTL","aliases":["VCNTL"],"saved_net_ids":["AFE:VCNTL"],"endpoints":["AFE.C42.1","AFE.R16.1","AFE.U1.D2"],"wire_ids":["8131761bfd0002a4","d9092d501baf3f19"],"label_ids":["348c884f4b6bf7fd","df2afbe968547511"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VREFH","aliases":["VREFH"],"saved_net_ids":["AFE:VREFH"],"endpoints":["AFE.C50.2","AFE.U1.F7"],"wire_ids":["1b7b6e424080c60e","e41d187e9a0ed626"],"label_ids":["e02591c779cc3dbb","edfec89a54232660"],"near_pins":[],"near_labels":[]}
{"net":"AFE:VREFL","aliases":["VREFL"],"saved_net_ids":["AFE:VREFL"],"endpoints":["AFE.C51.2","AFE.U1.G7"],"wire_ids":["3d2336fd5c198478","c3e59f57360491d2"],"label_ids":["37121bc9e92a6275","cb638f3947be8915"],"near_pins":[],"near_labels":[]}
```

## 6. Unconnected and single-terminal inventory

These inventories are exhaustive under the 0.25-unit reconstruction. A comma-separated list identifies individual pins, not a numeric range. An unconnected pin with a source name such as DNC retains that name in its component table; no intent is inferred here.

### PULSER unconnected terminals

| Component | Unconnected pin numbers |
| --- | --- |
| `PULSER.CN1` | `6`, `14` |
| `PULSER.U4` | `2` |

### PULSER single-terminal nets

| Net | Only attached terminal |
| --- | --- |
| `PULSER:1.8V NC` | `PULSER.CN1.2` |
| `PULSER:NO0` | `PULSER.U5.2` |
| `PULSER:NO1` | `PULSER.U5.4` |
| `PULSER:NO2` | `PULSER.U5.6` |
| `PULSER:NO3` | `PULSER.U5.8` |
| `PULSER:NO4` | `PULSER.U5.12` |
| `PULSER:NO6` | `PULSER.U5.16` |
| `PULSER:NO8` | `PULSER.U5.19` |
| `PULSER:NO9` | `PULSER.U5.21` |
| `PULSER:NO10` | `PULSER.U5.23` |
| `PULSER:NO12` | `PULSER.U5.29` |
| `PULSER:NO13` | `PULSER.U5.31` |
| `PULSER:NO14` | `PULSER.U5.33` |
| `PULSER:NO15` | `PULSER.U5.35` |

### AFE unconnected terminals

| Component | Unconnected pin numbers |
| --- | --- |
| `AFE.CN1` | `15` |
| `AFE.CN2` | `1`, `3`, `5`, `7`, `9`, `11`, `13`, `15`, `29`, `30`, `31`, `32`, `33`, `34`, `35`, `36`, `37`, `39`, `41`, `42`, `43`, `44`, `45`, `46`, `47`, `48`, `49`, `50` |
| `AFE.U1` | `A2`, `A3`, `A4`, `A6`, `A7`, `A8`, `A9`, `B5`, `C1`, `C9`, `D1`, `D9`, `E1`, `E9`, `F1`, `F9`, `G1`, `G9`, `H2`, `H3`, `J3`, `K2`, `K4`, `M1`, `M2`, `M8`, `M9`, `P1`, `P2`, `P3`, `P6`, `P7`, `P8`, `P9`, `R1`, `R2`, `R3`, `R6`, `R7`, `R8`, `R9` |
| `AFE.U3` | `1`, `4`, `5` |
| `AFE.U5` | `3`, `4`, `5`, `6`, `9`, `10`, `11`, `12`, `15`, `16`, `17`, `18`, `21`, `22`, `23`, `24`, `27`, `28`, `29`, `30`, `33`, `34`, `35`, `36`, `39`, `40`, `41`, `42`, `52`, `54`, `57`, `58`, `59`, `60`, `63`, `64`, `65`, `66`, `69`, `70`, `71`, `72`, `75` |
| `AFE.U6` | `3`, `4`, `5`, `6`, `9`, `10`, `11`, `12`, `15`, `16`, `17`, `18`, `21`, `22`, `23`, `24`, `27`, `28`, `29`, `30`, `34`, `36`, `40`, `42`, `45`, `46`, `47`, `48`, `52`, `54`, `58`, `60`, `64`, `66`, `69`, `71`, `75`, `77` |
| `AFE.U7` | `2` |

### AFE single-terminal nets

| Net | Only attached terminal |
| --- | --- |
| `AFE:41` | `AFE.U6.41` |

### Wire without a terminal

AFE wire group `4128d3e200c40422` has no attached component terminals or labels under the matching rule. It does not contribute an electrical connection between any listed parts.

## 7. Source annotations

The following are literal drawing TEXT records. They are source annotations, not executable instructions, proof of a physical short, or substitutions for the pin tables. Decorative title-block metadata is omitted.

### PULSER

- Source text `NC` at (1065.866142, -653.685039), record `b61bf621751af9b8`.
- Source text `Solderable / Gap` at (502.133858, -1557.314961), record `b168639ff4146721`.
- Source text `Solderable / Gap` at (219.009133, -1399.314961), record `1cba981e77cc6f04`.
- Source text `-5V Inverter` at (602.133858, -654), record `5b6ac657e6d0f529`.

### AFE

- Source text `0.1uF At each pin` at (192.708661, -679.543307), record `e3815`.
- Source text `PLACE FERRITE CLOSE TO ADC` at (312, -1011), record `e8630`.
- Source text `+1.8V_ADC` at (59, -1146), record `e8984`.
- Source text `+3.3V` at (632, -1144), record `7110600cf3a0a1d7`.
- Source text `40Mhz Clock` at (1123, -1143), record `fe53c70f9b769978`.
- Source text `ALCHITRY AU V2 ARTIX 7 FPGA PINS` at (1301, -245), record `8ee1cce13d9ecdbf`.
- Source text `DAC And 1.2V Reference` at (62, -374), record `a3976fe5b40d1252`.

## 8. Coordinate-contact audit

All distances are in the source schematic coordinate system, not millimetres. Each row identifies a contact greater than 0.0001 and no greater than 0.25 units that was accepted by the reconstruction. Exact source positions, closest active wire IDs, and distances are retained for native-editor follow-up. The four 0.31496063-unit cases in Section 2 were not accepted.

### PULSER pin-to-wire near contacts

| Endpoint | Assigned net | Pin position x, y | Wire ID | Offset |
| --- | --- | --- | --- | --- |
| `PULSER.C24.2` | `PULSER:N_C24_2` | 980.86614173, -342.68503937 | `eb3fc2a58e73d7c5` | 0.16535433 |
| `PULSER.C25.1` | `PULSER:N_C3_2` | 983.86614173, -321.68503937 | `99264b3aa2e472be` | 0.15043286 |
| `PULSER.C26.1` | `PULSER:N_C26_1` | 933.07086614, -342.51968504 | `293d1d786470e846` | 0.14195084 |
| `PULSER.Q1.5` | `PULSER:N_D1_1` | 1344.39370079, -322.07086614 | `19215d27218aa489` | 0.18897638 |
| `PULSER.Q1.8` | `PULSER:N_D1_2` | 1344.39370079, -352.07086614 | `3586a91aa5e777ab` | 0.18897638 |
| `PULSER.U2.1` | `PULSER:-5V` | 850.13385827, -612.00000000 | `15588bf15250544d` | 0.00787367 |
| `PULSER.U2.2` | `PULSER:+5V` | 750.13385827, -612.00000000 | `1bf7d88ee05136ac` | 0.00787402 |
| `PULSER.U6.3` | `PULSER:SIG2_IN` | 784.84251969, -352.51181102 | `b9cb9cfab047d5ec` | 0.17322835 |
| `PULSER.U6.13` | `PULSER:-5V` | 874.84251969, -382.51181102 | `25c0e4a9dd44c27a` | 0.17483152 |
| `PULSER.U9.1` | `PULSER:GND` | 1030.00000000, -1869.31496063 | `0ba5e284a76a0187` | 0.00061997 |
| `PULSER.U9.5` | `PULSER:1NO5` | 990.00008000, -1869.31496063 | `be76079f40eb8d09` | 0.02969606 |
| `PULSER.U9.7` | `PULSER:1NO6` | 970.00012000, -1869.31496063 | `f2009515ed303127` | 0.02969606 |
| `PULSER.U9.9` | `PULSER:1NO7` | 950.00016000, -1869.31496063 | `023c3c66a3319273` | 0.02969606 |
| `PULSER.U9.11` | `PULSER:1NO8` | 930.00020000, -1869.31496063 | `d14a0a472ea35b7f` | 0.02969606 |
| `PULSER.U9.13` | `PULSER:1NO9` | 910.00024000, -1869.31496063 | `c597d444cc1fcdc2` | 0.02969606 |
| `PULSER.U9.15` | `PULSER:1NO10` | 890.00028000, -1869.31496063 | `f0ee217c2160c935` | 0.02969606 |
| `PULSER.U9.17` | `PULSER:1NO11` | 870.00032000, -1869.31496063 | `a479472c9a6918be` | 0.04508409 |
| `PULSER.U9.19` | `PULSER:1NO12` | 850.00036000, -1869.31496063 | `b95888ec0ab48303` | 0.04504409 |
| `PULSER.U9.21` | `PULSER:1NO13` | 830.00040000, -1869.31496063 | `e411ad16b1f3968d` | 0.04500409 |
| `PULSER.U9.23` | `PULSER:1NO14` | 810.00044000, -1869.31496063 | `d673f771060b857c` | 0.04496409 |
| `PULSER.U9.25` | `PULSER:1NO15` | 790.00048000, -1869.31496063 | `977dd9f5262cbbdd` | 0.04492409 |
| `PULSER.U9.27` | `PULSER:2NO0` | 770.00052000, -1869.31496063 | `013e6ed05e44f5c8` | 0.04488409 |
| `PULSER.U9.29` | `PULSER:2NO1` | 750.00056000, -1869.31496063 | `85468b869f8b5858` | 0.01518803 |
| `PULSER.U9.33` | `PULSER:2NO3` | 710.00064000, -1869.31496063 | `39069e08bf0aca4d` | 0.04476409 |
| `PULSER.U9.35` | `PULSER:2NO4` | 690.00068000, -1869.31496063 | `8a9121db77e70321` | 0.01506803 |
| `PULSER.U9.37` | `PULSER:2NO5` | 670.00072000, -1869.31496063 | `e2bf46b3bebad673` | 0.02969606 |
| `PULSER.U9.39` | `PULSER:2NO6` | 650.00076000, -1869.31496063 | `be5ade77ac46190e` | 0.02969606 |
| `PULSER.U9.41` | `PULSER:2NO7` | 630.00080000, -1869.31496063 | `e70dd7a402a68f37` | 0.04460409 |
| `PULSER.U9.43` | `PULSER:2NO8` | 610.00084000, -1869.31496063 | `a81f0ce961708fd8` | 0.04456409 |
| `PULSER.U9.45` | `PULSER:2NO9` | 590.00088000, -1869.31496063 | `b33a11b199de2e03` | 0.04452409 |
| `PULSER.U9.47` | `PULSER:2NO10` | 570.00092000, -1869.31496063 | `efc9703dd6bef54b` | 0.01482803 |
| `PULSER.U9.49` | `PULSER:2NO11` | 550.00096000, -1869.31496063 | `19b692f4eaecff2a` | 0.00096000 |
| `PULSER.U9.51` | `PULSER:GND` | 540.00198000, -1784.19691039 | `0ba5e284a76a0187` | 0.00198000 |
| `PULSER.U9.53` | `PULSER:GND` | 560.00194000, -1784.19691039 | `0ba5e284a76a0187` | 0.00194000 |
| `PULSER.U9.60` | `PULSER:3NO15` | 630.00180000, -1784.19691039 | `4c90fe207f4b079d` | 0.01394803 |
| `PULSER.U9.90` | `PULSER:3NO0` | 930.00120000, -1784.19691039 | `1d7c97b9a7df8ae3` | 0.00120000 |
| `PULSER.U9.100` | `PULSER:GND` | 1030.00100000, -1784.19691039 | `0ba5e284a76a0187` | 0.01255621 |
| `PULSER.U13.1` | `PULSER:N_R66_2` | 1406.00000000, -815.00000000 | `3880a1223a23ff9e` | 0.03937008 |
| `PULSER.U13.2` | `PULSER:GND` | 1446.00000000, -815.00000000 | `5f22c48726c5b05c` | 0.03937008 |

### PULSER label-to-wire near contacts

| Label | Label component ID | Assigned net | Port position x, y | Wire ID | Offset |
| --- | --- | --- | --- | --- | --- |
| `3NO11` | `4195ce5b6ad9a247` | `PULSER:3NO11` | 710.00000000, -1766.17316835 | `6633ae6f4d158b92` | 0.01410803 |
| `+5V` | `d3ae0f7367050e44` | `PULSER:+5V` | 987.86614173, -362.68503937 | `6d29dfb3ca2a8541` | 0.17483152 |
| `DRIVER_EN` | `52b58f091ad6580c` | `PULSER:DRIVER_EN` | 881.88976378, -377.95275591 | `060ea0d3f46f0cf5` | 0.17483152 |
| `GND` | `4a79c06d13d02772` | `PULSER:GND` | 1063.00000000, -1760.31496063 | `0ba5e284a76a0187` | 0.11023622 |
| `GND` | `091dba555b63b797` | `PULSER:GND` | 138.77165354, -344.34645669 | `3715a5d12ebee1b4` | 0.22834646 |
| `GND` | `f79f7b7ae5a2ac56` | `PULSER:GND` | 852.13385827, -1398.31496063 | `8663528e2e6648c9` | 0.13385827 |
| `GND` | `6fadd9a3809d401d` | `PULSER:GND` | 869.13385827, -954.00000000 | `b6f379e2fdfad808` | 0.13385827 |
| `N_DRIVER_OUT_B` | `21d93f8dfcf48915` | `PULSER:N_DRIVER_OUT_B` | 1284.33858268, -341.88188976 | `b15a2dc529930aff` | 0.19685039 |
| `PULSE_OUT` | `1c9f4f2c716a1472` | `PULSER:PULSE_OUT` | 1435.33858268, -337.88188976 | `f26b7760c66c7892` | 0.06299213 |
| `P_DRIVER_OUT_A` | `10299b216fa53157` | `PULSER:P_DRIVER_OUT_A` | 1284.33858268, -321.88188976 | `23566d31402c6f99` | 0.19685039 |

### AFE pin-to-wire near contacts

| Endpoint | Assigned net | Pin position x, y | Wire ID | Offset |
| --- | --- | --- | --- | --- |
| `AFE.R8.1` | `AFE:+3.3_VDD` | 1664.85432107, -300.24273469 | `b4af8cdeea836e80` | 0.05605419 |
| `AFE.U1.E3` | `AFE:VB3` | 762.00000000, -456.00000000 | `f0bea5b071839ea1` | 0.13385827 |
| `AFE.U1.E5` | `AFE:GND` | 762.00000000, -436.00000000 | `72647b51fbe67f4b` | 0.03128623 |
| `AFE.U1.E7` | `AFE:VB4` | 762.00000000, -416.00000000 | `8cf7644ce3f5bac2` | 0.13385827 |
| `AFE.U1.E8` | `AFE:+5_VDD` | 762.00000000, -406.00000000 | `d366766c21abcbb7` | 0.19685039 |
| `AFE.U1.F2` | `AFE:VB1` | 762.00000000, -376.00000000 | `83634d5f649352e8` | 0.13385457 |
| `AFE.U1.N4` | `AFE:GND` | 912.00000000, -601.00000000 | `8e54544e3408e536` | 0.16241947 |
| `AFE.U1.P4` | `AFE:OUT1P` | 912.00000000, -691.00000000 | `92c404bf79e0079b` | 0.13385827 |
| `AFE.U5.1` | `AFE:GND` | 1273.71280691, -752.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.2` | `AFE:GND` | 1333.71280691, -752.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.7` | `AFE:GND` | 1273.71280691, -722.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.8` | `AFE:GND` | 1333.71280691, -722.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.13` | `AFE:GND` | 1273.71280691, -692.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.14` | `AFE:GND` | 1333.71280691, -692.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.19` | `AFE:GND` | 1273.71280691, -662.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.20` | `AFE:GND` | 1333.71280691, -662.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.25` | `AFE:GND` | 1273.71280691, -632.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.26` | `AFE:GND` | 1333.71280691, -632.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.31` | `AFE:GND` | 1273.71280691, -602.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.32` | `AFE:GND` | 1333.71280691, -602.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.37` | `AFE:GND` | 1273.71280691, -572.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.38` | `AFE:GND` | 1333.71280691, -572.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.43` | `AFE:GND` | 1273.71280691, -542.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.44` | `AFE:GND` | 1333.71280691, -542.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.45` | `AFE:LCLKM` | 1273.71280691, -532.30708559 | `2a1be363ab921a62` | 0.02445246 |
| `AFE.U5.46` | `AFE:FCLKM` | 1333.71280691, -532.30708559 | `ca3fd6b3791a0305` | 0.11031847 |
| `AFE.U5.47` | `AFE:LCLKP` | 1273.71280691, -522.30708559 | `c19c9c72e457682a` | 0.02445246 |
| `AFE.U5.48` | `AFE:FCLKP` | 1333.71280691, -522.30708559 | `82235c2e1fa88d97` | 0.11031847 |
| `AFE.U5.49` | `AFE:GND` | 1273.71280691, -512.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.50` | `AFE:GND` | 1333.71280691, -512.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.51` | `AFE:OUT1M` | 1273.71280691, -502.30708559 | `39882b0d5b40ef7d` | 0.02450332 |
| `AFE.U5.53` | `AFE:OUT1P` | 1273.71280691, -492.30708559 | `f732b3e0e8a90fee` | 0.02445246 |
| `AFE.U5.55` | `AFE:GND` | 1273.71280691, -482.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.56` | `AFE:GND` | 1333.71280691, -482.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.61` | `AFE:GND` | 1273.71280691, -452.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.62` | `AFE:GND` | 1333.71280691, -452.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.67` | `AFE:GND` | 1273.71280691, -422.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.68` | `AFE:GND` | 1333.71280691, -422.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.73` | `AFE:GND` | 1273.71280691, -392.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.74` | `AFE:GND` | 1333.71280691, -392.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U5.76` | `AFE:N_R10_1` | 1333.71280691, -382.30708559 | `ffcdb0ebf723ffe5` | 0.11031847 |
| `AFE.U5.77` | `AFE:N_R9_2` | 1273.71280691, -372.30708559 | `494168cb2fe8b3e3` | 0.10648151 |
| `AFE.U5.78` | `AFE:N_R11_1` | 1333.71280691, -372.30708559 | `c43429ac333b0958` | 0.11031847 |
| `AFE.U5.79` | `AFE:GND` | 1273.71280691, -362.30708559 | `3cd95a451b63378f` | 0.02445246 |
| `AFE.U5.80` | `AFE:GND` | 1333.71280691, -362.30708559 | `3d7be7c9721e6339` | 0.11031847 |
| `AFE.U6.1` | `AFE:GND` | 1573.03004688, -775.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.2` | `AFE:GND` | 1633.03004688, -775.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.7` | `AFE:GND` | 1573.03004688, -745.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.8` | `AFE:GND` | 1633.03004688, -745.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.13` | `AFE:GND` | 1573.03004688, -715.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.14` | `AFE:GND` | 1633.03004688, -715.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.19` | `AFE:GND` | 1573.03004688, -685.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.20` | `AFE:GND` | 1633.03004688, -685.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.25` | `AFE:GND` | 1573.03004688, -655.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.26` | `AFE:GND` | 1633.03004688, -655.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.31` | `AFE:GND` | 1573.03004688, -625.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.32` | `AFE:GND` | 1633.03004688, -625.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.35` | `AFE:35` | 1573.03004688, -605.18355859 | `0423eef546dc3347` | 0.18600154 |
| `AFE.U6.37` | `AFE:GND` | 1573.03004688, -595.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.38` | `AFE:GND` | 1633.03004688, -595.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.43` | `AFE:GND` | 1573.03004688, -565.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.44` | `AFE:GND` | 1633.03004688, -565.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.49` | `AFE:GND` | 1573.03004688, -535.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.50` | `AFE:GND` | 1633.03004688, -535.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.55` | `AFE:GND` | 1573.03004688, -505.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.56` | `AFE:GND` | 1633.03004688, -505.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.61` | `AFE:GND` | 1573.03004688, -475.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.62` | `AFE:GND` | 1633.03004688, -475.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.67` | `AFE:GND` | 1573.03004688, -445.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.68` | `AFE:GND` | 1633.03004688, -445.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.70` | `AFE:ADS_RST` | 1633.03004688, -435.18355859 | `ee8cc476c7686ec4` | 0.05917610 |
| `AFE.U6.72` | `AFE:N_R5_2` | 1633.03004688, -425.18355859 | `f666a90c20661d5f` | 0.05917610 |
| `AFE.U6.73` | `AFE:GND` | 1573.03004688, -415.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.74` | `AFE:GND` | 1633.03004688, -415.18355859 | `c394cc1f3527fed0` | 0.05917610 |
| `AFE.U6.76` | `AFE:CS` | 1633.03004688, -405.18355859 | `fb851ff48fceea11` | 0.05917610 |
| `AFE.U6.78` | `AFE:N_R1_2` | 1633.03004688, -395.18355859 | `ebad74c143db1ef9` | 0.05917610 |
| `AFE.U6.79` | `AFE:GND` | 1573.03004688, -385.18355859 | `321331f1fe2758e1` | 0.08002930 |
| `AFE.U6.80` | `AFE:GND` | 1633.03004688, -385.18355859 | `c394cc1f3527fed0` | 0.05917610 |

### AFE label-to-wire near contacts

| Label | Label component ID | Assigned net | Port position x, y | Wire ID | Offset |
| --- | --- | --- | --- | --- | --- |
| `5V-USB` | `1afe4edbe45a06ab` | `AFE:5V-USB` | 1886.00000000, -698.00000000 | `11ec6c558ebc2d4a` | 0.04724409 |
| `33` | `4f0f73ca6127b5b5` | `AFE:33` | 1545.00000000, -615.00000000 | `8e89f8262553575e` | 0.18600154 |
| `39` | `cd37a28dff509811` | `AFE:39` | 1546.00000000, -586.00000000 | `9e87f093cdb3ef4e` | 0.03004688 |
| `41` | `5eac4477240f26b2` | `AFE:41` | 1546.00000000, -575.00000000 | `5517f21970f5b083` | 0.18600154 |
| `51` | `eb3913c036b8da21` | `AFE:51` | 1548.00000000, -525.00000000 | `2709ec3422851de9` | 0.18600154 |
| `53` | `1db95708130a3ac3` | `AFE:53` | 1543.00000000, -515.00000000 | `c07b504b4073f5ce` | 0.18600154 |
| `57` | `d7ed1a1f6410e486` | `AFE:57` | 1540.00000000, -496.00000000 | `cba9fd24b16aae3b` | 0.18600154 |
| `59` | `028a500d9adebd7c` | `AFE:59` | 1546.00000000, -484.00000000 | `7f80fda5d2469b40` | 0.18600154 |
| `63` | `a5d44cbf1b34ebbf` | `AFE:63` | 1544.00000000, -466.00000000 | `86d7d659206196db` | 0.18600154 |
| `+3.3_VDD` | `5613a64590943de3` | `AFE:+3.3_VDD` | 668.39370079, -285.25196850 | `ce2a2c7e54e60ae4` | 0.17322835 |
| `+5_VDD` | `be83870342e604f7` | `AFE:+5_VDD` | 660.56692913, -465.86614173 | `d366766c21abcbb7` | 0.13385827 |
| `CLKM` | `5190cde3c8927697` | `AFE:CLKM` | 921.56692913, -300.86614173 | `c053730fe79431c1` | 0.13385827 |

## 9. Extraction rules and validation

1. Read the two `.epro2` ZIP archives without modifying the sources. Parse every `.epru` record and identify SCH_PAGE component, attribute, wire, and line records plus the referenced DEVICE and SYMBOL records. Records with no body are excluded. Each archive contains one schematic and one page.
2. Resolve each component’s selected symbol part and all of its PIN records. Apply source pin attributes and any instance pin overrides. Rotate counterclockwise in the schematic coordinate system, apply horizontal mirroring after rotation, and translate to the component position. The official [EasyEDA component-format reference](https://prodocs.easyeda.com/en/format/schematic/component/) describes the transform order and pin-attribute overrides.
3. Treat LINE records sharing an active WIRE parent as one wire group. Retain the group’s electrical identity even when described by multiple segments. Use endpoint-on-segment contact to join distinct groups; do not join bare interior crossings. No distinct active WIRE groups required a geometric join at the strict tolerance in these files.
4. Match pins and port anchors to active wire segments with a 0.25-unit distance limit; match coincident pin/port points at 0.0001 units. Merge exact, case-sensitive global-net and port names only within the same board. WIRE NET properties in the supplied records are empty; names are carried by the placed label/port symbols. The [EasyEDA pin-format reference](https://prodocs.easyeda.com/en/format/schematic/pin/) identifies pin coordinates as the external connection endpoint.
5. Exclude LINE records whose WIRE parent is absent from the active schematic record set: 577 pulser segments and 516 AFE segments. They are retained in the source archives but do not establish active connections here. Exclude title-block artwork and non-electrical drawing records from the component inventory. Do not use cached thumbnail artwork as an authoritative replacement for active records.
6. Expand each BOM designator list, require unique references, and check each row quantity against its list. Compare schematic and BOM reference sets exactly. Compare effective schematic Value, Manufacturer Part, and Supplier Part against the supplied BOM: no differences in those fields were found; the population flags described in Section 2 remain a separate discrepancy.
7. Require each symbol terminal to occur once in its component pin table and either once in the net index or once in the unconnected inventory. Check endpoint uniqueness, BOM coverage, and exact agreement between the two representations. Include extra numbered symbol terminals and exposed pads rather than silently dropping them to match a part-name pin count.
8. Compare reconstruction at 0.25 and 0.5 units. AFE net memberships are unchanged; the only pulser changes are the four ground candidates documented in Section 2. Native-editor connectivity was not exported or verified. EasyEDA supports [exporting its native netlist](https://prodocs.easyeda.com/en/schematic/export-netlist/) for a subsequent authoritative comparison.
9. Apply the owner-confirmed physical override by shorting pins 1 and 2 of each of R17–R64, merging its saved nets into the appropriate leaf input net. Verify 48 bridges, 16 COM terminals per leaf on its assigned common node, and preservation of three separate input-bank nets. Preserve saved net IDs for reconstruction of the original schematic.

### Validation totals

| Check | PULSER | AFE |
| --- | --- | --- |
| BOM rows | 23 | 32 |
| Matched component references | 116 | 111 |
| Symbol terminals | 565 | 614 |
| Active WIRE groups | 291 | 180 |
| Active wire LINE segments | 853 | 791 |
| Named port / global-net instances | 218 | 160 |
| Pins with accepted near-wire contacts | 39 | 78 |
| Labels with accepted near-wire contacts | 10 | 12 |
| BOM-only / schematic-only references | 0 / 0 | 0 / 0 |

