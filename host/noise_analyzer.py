#!/usr/bin/env python3
"""Desktop app and CLI for single-element waveform/noise diagnosis.

Examples:

    python noise_analyzer.py
    python noise_analyzer.py --simulate --frames 128
    python noise_analyzer.py --capture --element 23 --frames 256
    python noise_analyzer.py --analyze noise_captures/.../capture.npz

The hardware path fires only the selected aperture element through the existing
transmit sequencer.  It does not require or modify FPGA source/bitstreams.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import traceback

import numpy as np

from noise_analysis import (
    ADC_FULL_SCALE_COUNTS,
    AnalysisResult,
    CaptureCancelled,
    CaptureData,
    CaptureError,
    CaptureSettings,
    SingleElementCapture,
    analyze_capture,
    export_bundle,
    load_capture_npz,
    simulate_capture,
)


APP_TITLE = "Single-element waveform & noise analyzer"
DEFAULT_OUTPUT_ROOT = Path(__file__).with_name("noise_captures")


def timestamped_output(root: Path, element: int, source: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(root) / f"noise_E{element:02d}_{source}_{stamp}"


def concise_summary(result: AnalysisResult) -> str:
    report = result.report
    s = report["summary"]
    lines = [
        f"Assessment: {report['overall_status']}",
        f"Graded imaging region: {s['analysis_start_depth_cm']:.2f} cm onward (expected limiter interval excluded)",
        f"Random noise: {s['random_rms_counts']:.3f} counts ({s['random_rms_dbfs']:.2f} dBFS RMS)",
        f"Repeatable component: {s['coherent_rms_counts']:.3f} counts ({s['coherent_rms_dbfs']:.2f} dBFS RMS)",
        f"Peak: {s['peak_counts']:.1f} counts ({s['peak_dbfs']:.2f} dBFS); clipped {s['clipped_samples_percent']:.8f}%",
        f"Effective bits from random noise: {s['effective_bits_from_random_noise']:.3f}",
        "",
    ]
    for item in report["findings"]:
        lines.append(f"[{item['severity'].upper()}] {item['summary']}")
    regions = report["time_depth_localization"]["localized_regions"]
    if regions:
        lines.extend(["", "Strongest localized regions:"])
        for region in regions[:4]:
            excess = max(region["max_random_excess_db"], region["max_total_excess_db"])
            lines.append(
                f"  {region['start_us']:.1f}–{region['end_us']:.1f} us  "
                f"({region['start_depth_cm']:.2f}–{region['end_depth_cm']:.2f} cm): "
                f"{region['classification']}, +{excess:.1f} dB"
            )
    return "\n".join(lines)


def run_analysis(data: CaptureData, output: Path) -> tuple[AnalysisResult, dict[str, Path]]:
    result = analyze_capture(data)
    paths = export_bundle(data, result, output)
    return result, paths


class NoiseAnalyzerApp:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1180x850")
        self.root.minsize(980, 720)
        self.events: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.latest_output: Path | None = None
        self.latest_result: AnalysisResult | None = None
        self._build()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text=APP_TITLE, font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")
        ttk.Label(
            outer,
            text="Captures repeated shots from one physical element, separates repeatable artifacts from random noise, "
                 "and exports an LLM-ready evidence bundle. Hardware capture fires the pulser; it is stopped on completion.",
            wraplength=1120,
        ).pack(anchor="w", pady=(2, 10))

        settings = ttk.LabelFrame(outer, text="Capture settings", padding=10)
        settings.pack(fill="x")
        self.vars = {
            "element": tk.StringVar(value="0"),
            "frames": tk.StringVar(value="128"),
            "depth_cm": tk.StringVar(value="14"),
            "analysis_start_depth_cm": tk.StringVar(value="3"),
            "sound_speed_m_s": tk.StringVar(value="1496"),
            "delay_us": tk.StringVar(value="5"),
            "damp_us": tk.StringVar(value="50"),
            "tgc_start": tk.StringVar(value="834"),
            "tgc_end": tk.StringVar(value="834"),
            "pulse_pairs": tk.StringVar(value="2"),
            "pulse_width_ns": tk.StringVar(value="100"),
            "pulse_dead_ns": tk.StringVar(value="40"),
            "signed_adc": tk.BooleanVar(value=False),
            "output_root": tk.StringVar(value=str(DEFAULT_OUTPUT_ROOT)),
        }
        fields = [
            ("Element (0–47)", "element", 0, 0),
            ("Repeated frames", "frames", 0, 2),
            ("Capture span (cm)", "depth_cm", 0, 4),
            ("Sound speed (m/s)", "sound_speed_m_s", 0, 6),
            ("Pulse → capture (µs)", "delay_us", 1, 0),
            ("Post-window damp (µs)", "damp_us", 1, 2),
            ("TGC start", "tgc_start", 1, 4),
            ("TGC end", "tgc_end", 1, 6),
            ("Pulse pairs", "pulse_pairs", 2, 0),
            ("Pulse width (ns)", "pulse_width_ns", 2, 2),
            ("Dead time (ns)", "pulse_dead_ns", 2, 4),
            ("Analyze from (cm)", "analysis_start_depth_cm", 2, 6),
        ]
        for label, key, row, col in fields:
            ttk.Label(settings, text=label).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=4)
            ttk.Entry(settings, textvariable=self.vars[key], width=10).grid(
                row=row, column=col + 1, sticky="ew", padx=(0, 14), pady=4
            )
        ttk.Checkbutton(
            settings, text="ADC outputs 12-bit two's-complement (off = offset-binary)",
            variable=self.vars["signed_adc"],
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=4)
        for col in (1, 3, 5, 7):
            settings.columnconfigure(col, weight=1)

        note = ttk.Label(
            settings,
            text="For hardware-noise localization, keep TGC start and end equal. A ramp is allowed but is reported as a confound.",
            foreground="#825b00",
        )
        note.grid(row=4, column=0, columnspan=8, sticky="w", pady=(5, 0))

        outrow = ttk.Frame(outer)
        outrow.pack(fill="x", pady=(10, 4))
        ttk.Label(outrow, text="Save under").pack(side="left")
        ttk.Entry(outrow, textvariable=self.vars["output_root"]).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(outrow, text="Choose…", command=self._choose_output).pack(side="left")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(4, 8))
        self.capture_button = ttk.Button(actions, text="Capture hardware (fires selected element)", command=self._capture)
        self.capture_button.pack(side="left")
        self.sim_button = ttk.Button(actions, text="Run fault-rich simulation", command=self._simulate)
        self.sim_button.pack(side="left", padx=8)
        self.load_button = ttk.Button(actions, text="Analyze saved capture…", command=self._load)
        self.load_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel_event.set, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.open_button = ttk.Button(actions, text="Open latest report folder", command=self._open_output, state="disabled")
        self.open_button.pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.pack(fill="x")
        self.status = ttk.Label(outer, text="Ready")
        self.status.pack(anchor="w", pady=(3, 8))

        panes = ttk.Panedwindow(outer, orient="vertical")
        panes.pack(fill="both", expand=True)
        plot_box = ttk.LabelFrame(panes, text="Analysis preview", padding=6)
        result_box = ttk.LabelFrame(panes, text="Summary", padding=6)
        panes.add(plot_box, weight=3)
        panes.add(result_box, weight=2)
        self.canvas = tk.Canvas(plot_box, background="#0a0e12", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw_preview())
        self.summary = tk.Text(result_box, height=10, wrap="word", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(result_box, command=self.summary.yview)
        self.summary.configure(yscrollcommand=scrollbar.set)
        self.summary.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.summary.insert("1.0", "Run a simulation to exercise the complete analyzer without hardware, or capture one element from the FT601.\n")
        self.summary.configure(state="disabled")

    def settings(self) -> CaptureSettings:
        try:
            return CaptureSettings(
                element=int(self.vars["element"].get()),
                frames=int(self.vars["frames"].get()),
                depth_cm=float(self.vars["depth_cm"].get()),
                analysis_start_depth_cm=float(self.vars["analysis_start_depth_cm"].get()),
                sound_speed_m_s=float(self.vars["sound_speed_m_s"].get()),
                delay_us=float(self.vars["delay_us"].get()),
                damp_us=float(self.vars["damp_us"].get()),
                tgc_start=int(self.vars["tgc_start"].get()),
                tgc_end=int(self.vars["tgc_end"].get()),
                signed_adc=bool(self.vars["signed_adc"].get()),
                pulse_pairs=int(self.vars["pulse_pairs"].get()),
                pulse_width_ns=float(self.vars["pulse_width_ns"].get()),
                pulse_dead_ns=float(self.vars["pulse_dead_ns"].get()),
            ).validated()
        except ValueError as exc:
            raise ValueError(f"One or more capture settings is not a valid number: {exc}") from exc

    def _choose_output(self) -> None:
        from tkinter import filedialog
        selected = filedialog.askdirectory(initialdir=self.vars["output_root"].get())
        if selected:
            self.vars["output_root"].set(selected)

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (self.capture_button, self.sim_button, self.load_button):
            button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.cancel_event.clear()

    def _start(self, kind: str, source=None) -> None:
        from tkinter import messagebox
        try:
            settings = self.settings()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        output_root = Path(self.vars["output_root"].get())
        self._busy(True)
        self.progress.configure(value=0, maximum=settings.frames)
        self.status.configure(text="Starting…")

        def progress(done: int, total: int) -> None:
            self.events.put(("progress", done, total))

        def work() -> None:
            try:
                if kind == "hardware":
                    data = SingleElementCapture().capture(settings, progress, self.cancel_event)
                    source_name = "hardware"
                elif kind == "simulation":
                    data = simulate_capture(settings)
                    progress(settings.frames, settings.frames)
                    source_name = "simulation"
                else:
                    data = load_capture_npz(Path(source))
                    source_name = "reanalyzed"
                out = timestamped_output(output_root, int(data.settings.get("element", 0)), source_name)
                result, paths = run_analysis(data, out)
                self.events.put(("done", result, paths, out))
            except CaptureCancelled as exc:
                self.events.put(("cancelled", str(exc)))
            except Exception as exc:
                self.events.put(("error", str(exc), traceback.format_exc()))

        self.worker = threading.Thread(target=work, name="noise-capture", daemon=True)
        self.worker.start()

    def _capture(self) -> None:
        from tkinter import messagebox
        if not messagebox.askokcancel(
            APP_TITLE,
            "Hardware capture will arm the pulser and repeatedly fire only the selected element. "
            "Confirm the probe and HV bench setup are safe to run. The app stops the pulser when capture finishes.",
        ):
            return
        self._start("hardware")

    def _simulate(self) -> None:
        self._start("simulation")

    def _load(self) -> None:
        from tkinter import filedialog
        selected = filedialog.askopenfilename(
            title="Choose capture.npz", filetypes=[("Noise capture", "*.npz"), ("All files", "*.*")]
        )
        if selected:
            self._start("saved", selected)

    def _poll(self) -> None:
        from tkinter import messagebox
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, done, total = event
                    self.progress.configure(maximum=total, value=done)
                    self.status.configure(text=f"Captured {done}/{total} clean frames…")
                elif event[0] == "done":
                    _, result, paths, out = event
                    self.latest_result, self.latest_output = result, out
                    self._busy(False)
                    self.open_button.configure(state="normal")
                    self.status.configure(text=f"Complete — evidence bundle saved to {out}")
                    self.summary.configure(state="normal")
                    self.summary.delete("1.0", "end")
                    self.summary.insert("1.0", concise_summary(result))
                    self.summary.configure(state="disabled")
                    self._draw_preview()
                elif event[0] == "cancelled":
                    self._busy(False)
                    self.status.configure(text="Capture cancelled; pulser stopped.")
                elif event[0] == "error":
                    _, message, detail = event
                    self._busy(False)
                    self.status.configure(text="Failed")
                    print(detail, file=sys.stderr)
                    messagebox.showerror(APP_TITLE, message)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _draw_preview(self) -> None:
        result = self.latest_result
        cv = self.canvas
        cv.delete("all")
        w, h = max(100, cv.winfo_width()), max(100, cv.winfo_height())
        if result is None:
            cv.create_text(w / 2, h / 2, text="Analysis plots appear here", fill="#708895", font=("Segoe UI", 14))
            return
        margin_l, margin_r, margin_t, gap = 58, 15, 24, 32
        pw = w - margin_l - margin_r
        ph = max(55, (h - margin_t - 2 * gap - 20) / 3)

        def panel(y, title):
            cv.create_rectangle(margin_l, y, margin_l + pw, y + ph, outline="#33505f", fill="#0a0e12")
            cv.create_text(margin_l, y - 6, anchor="sw", text=title, fill="#b9cad4", font=("Segoe UI", 10, "bold"))

        def line(values, y, ymin, ymax, color, width=1):
            a = np.asarray(values, dtype=float)
            count = max(2, int(pw))
            if a.size > count:
                idx = np.linspace(0, a.size - 1, count).astype(int)
                a = a[idx]
            den = max(ymax - ymin, 1e-12)
            pts = []
            for i, value in enumerate(a):
                pts.extend((margin_l + pw * i / max(1, a.size - 1), y + ph * (ymax - value) / den))
            if len(pts) >= 4:
                cv.create_line(*pts, fill=color, width=width)

        y = margin_t
        panel(y, "Repeatable waveform (cyan) and random σ envelope")
        mean, std = result.mean_waveform, result.random_std_waveform
        lim = max(1.0, float(np.percentile(np.abs(mean) + std, 99.5)))
        line(mean + std, y, -lim, lim, "#31576c")
        line(mean - std, y, -lim, lim, "#31576c")
        line(mean, y, -lim, lim, "#4dffd2", 2)
        cv.create_text(5, y + ph / 2, anchor="w", text="counts", fill="#708895")

        y += ph + gap
        panel(y, "Receive-window RMS: total (yellow), random (pink), repeatable (cyan)")
        blocks = result.time_blocks
        arrays = [np.array([b[k] for b in blocks]) for k in (
            "total_rms_dbfs", "random_rms_dbfs", "coherent_rms_dbfs"
        )]
        lo = min(-110.0, min(float(np.min(a)) for a in arrays) - 2)
        hi = min(0.0, max(float(np.max(a)) for a in arrays) + 2)
        for a, color in zip(arrays, ("#f2cf66", "#ff7a90", "#4dffd2")):
            line(a, y, lo, hi, color, 2)
        cv.create_text(5, y + ph / 2, anchor="w", text="dBFS", fill="#708895")

        y += ph + gap
        panel(y, "PSD: random (pink), repeatable (cyan), 0–20 MHz")
        p = 10 * np.log10(np.maximum(result.random_psd, np.finfo(float).tiny))
        pc = 10 * np.log10(np.maximum(result.coherent_psd, np.finfo(float).tiny))
        hi = max(float(np.percentile(p[1:], 99.8)), float(np.percentile(pc[1:], 99.8))) + 5
        lo = hi - 90
        line(p, y, lo, hi, "#ff7a90", 2)
        line(pc, y, lo, hi, "#4dffd2", 1)
        cv.create_text(5, y + ph / 2, anchor="w", text="PSD", fill="#708895")

    def _open_output(self) -> None:
        if self.latest_output is None:
            return
        try:
            os.startfile(self.latest_output)  # type: ignore[attr-defined]
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror(APP_TITLE, f"Could not open {self.latest_output}: {exc}")

    def _close(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.status.configure(text="Stopping capture safely…")
            self.root.after(200, self._wait_close)
        else:
            self.root.destroy()

    def _wait_close(self) -> None:
        if self.worker and self.worker.is_alive():
            self.root.after(200, self._wait_close)
        else:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--capture", action="store_true", help="capture from FT601 and exit")
    mode.add_argument("--simulate", action="store_true", help="create/analyze a fault-rich simulated capture and exit")
    mode.add_argument("--analyze", type=Path, metavar="CAPTURE.NPZ", help="reanalyze a saved capture and exit")
    parser.add_argument("--output", type=Path, help="exact output folder (CLI modes only)")
    parser.add_argument("--element", type=int, default=0)
    parser.add_argument("--frames", type=int, default=128)
    parser.add_argument("--depth-cm", type=float, default=14.0)
    parser.add_argument("--analysis-start-cm", type=float, default=3.0,
                        help="ignore expected limiter/ringdown before this physical depth")
    parser.add_argument("--sound-speed", type=float, default=1496.0, metavar="M/S")
    parser.add_argument("--delay-us", type=float, default=5.0)
    parser.add_argument("--damp-us", type=float, default=50.0)
    parser.add_argument("--tgc", type=int, nargs=2, default=(834, 834), metavar=("START", "END"))
    parser.add_argument("--signed-adc", action="store_true", help="AFE output is 12-bit two's-complement")
    parser.add_argument("--pulse-pairs", type=int, default=2)
    parser.add_argument("--pulse-width-ns", type=float, default=100.0)
    parser.add_argument("--pulse-dead-ns", type=float, default=40.0)
    return parser


def cli_settings(args) -> CaptureSettings:
    return CaptureSettings(
        element=args.element,
        frames=args.frames,
        depth_cm=args.depth_cm,
        analysis_start_depth_cm=args.analysis_start_cm,
        sound_speed_m_s=args.sound_speed,
        delay_us=args.delay_us,
        damp_us=args.damp_us,
        tgc_start=args.tgc[0],
        tgc_end=args.tgc[1],
        signed_adc=args.signed_adc,
        pulse_pairs=args.pulse_pairs,
        pulse_width_ns=args.pulse_width_ns,
        pulse_dead_ns=args.pulse_dead_ns,
    ).validated()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.capture or args.simulate or args.analyze):
        NoiseAnalyzerApp().run()
        return 0

    try:
        if args.analyze:
            data = load_capture_npz(args.analyze)
            source = "reanalyzed"
        else:
            settings = cli_settings(args)
            if args.simulate:
                data = simulate_capture(settings)
                source = "simulation"
            else:
                print(
                    f"Capturing {settings.frames} frames from element {settings.element}; "
                    "the pulser will fire and will be stopped afterward."
                )

                def progress(done, total):
                    print(f"\r{done}/{total} clean frames", end="", flush=True)

                data = SingleElementCapture().capture(settings, progress=progress)
                print()
                source = "hardware"
        output = args.output or timestamped_output(
            DEFAULT_OUTPUT_ROOT, int(data.settings.get("element", 0)), source
        )
        result, paths = run_analysis(data, output)
        print(concise_summary(result))
        print(f"\nEvidence bundle: {output.resolve()}")
        for name, path in paths.items():
            print(f"  {name:10s} {path.name}")
        return 0
    except (CaptureError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
