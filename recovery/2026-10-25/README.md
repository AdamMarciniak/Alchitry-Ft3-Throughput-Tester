# Ultrasound recovery snapshot - October 25, 2026

Branch: `Latest-Working-10-25-2026-before-gps-tracker-upload`

This snapshot preserves the existing source, host tools, presets, and every BIN
candidate found in the workspace before starting the GPS tracker project. The
owner reports that the last loaded FPGA image works well, but cannot identify
which BIN was loaded. All five candidates are retained without rebuilding them.
No FPGA programming or hardware changes were performed while making this backup.

## Choose the existing image

Every directory below contains `alchitry_top.bin`. Full SHA-256 hashes, original
paths, sizes, and timestamps are in `candidates.json`.

| Directory | Evidence |
| --- | --- |
| `last-recorded-programmed-8841d2b2` | The programming receipt records this exact BIN loaded into Au V2 RAM on September 9, 2026 at 09:34 Vancouver time. Includes the receipt, programming log, frozen source, and build reports. This is the strongest recorded programming evidence. |
| `vivado-output-2026-09-07` | Existing Vivado project implementation output from September 7. Includes BIN, BIT, the eye-persistence build script, and available timing/DRC reports. No receipt identifies it as the persistent flash image. |
| `latest-built-ae607960` | Newer September 9 checked build with capture-ready interlock. The associated documentation explicitly says it had not been programmed or tested on hardware in that change. Includes frozen source and reports. |
| `earlier-checked-build` | Earlier September 7 checked build, including its frozen source and reports. |
| `legacy-tracked-2026-08-02` | Original BIN already tracked at `bitstreams/alchitry_top.bin`, preserved unchanged. |

The current source tree is newer than the last recorded programmed image.
The three checked builds include their own original `source/` directories and
manifests; use those frozen inputs when investigating a particular BIN. The
Vivado and legacy BINs have no verified frozen source-to-BIN mapping here.
These artifacts are copies of existing files, not a readback of the FPGA or its
configuration flash. A manual load outside the recorded harness is not ruled out.

## Return to the ultrasound project

1. Check out this branch in a separate checkout or clone:

   ```powershell
   git clone --branch Latest-Working-10-25-2026-before-gps-tracker-upload --single-branch https://github.com/AdamMarciniak/Alchitry-Ft3-Throughput-Tester.git ultrasound-recovery
   cd ultrasound-recovery
   powershell -NoProfile -ExecutionPolicy Bypass -File recovery/2026-10-25/verify.ps1
   ```

2. In the Alchitry loader, select the Au V2 and the saved `alchitry_top.bin`
   from the candidate directory you intend to restore. Start with the
   last-recorded-programmed candidate if you want to reproduce the recorded
   September 9 RAM load. Program RAM for a temporary load; select flash if you
   intend the image to survive a power cycle. Flash programming replaces the
   image used by your other project. Close acquisition tools before programming.

3. Restore the ultrasound wiring and use the saved host tools and presets.
   `host-settings/latest.json` and `latest.png` preserve the most recent saved
   host settings and screenshot (September 9). The JSON includes the trim table;
   its saved armed state is historical context, not an instruction to start TX.
   See `../../docs/ultrasound-debug-setup.json` for the recorded setup and
   `../../docs/autonomous-wire-bench.md` for the controlled host workflow.

Loading the archived BIN avoids the possibility that rebuilding produces a
different image. `verify.ps1` only checks files; it does not access hardware.
Raw RF recordings and local scratch/build directories remain local; the recovery
files include the selected original build reports and all existing BINs.

## Integrity

`SHA256SUMS.json` hashes every other file in this recovery directory. The Git
attributes disable line-ending conversion for this archive so frozen source and
manifest hashes survive a fresh checkout. The original build manifests and the
programming receipt were also checked against their archived files.
