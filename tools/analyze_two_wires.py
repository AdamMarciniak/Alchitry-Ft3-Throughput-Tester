#!/usr/bin/env python3
"""Optimize replay-only focusing settings against two wire responses.

The search uses ordinary DAS magnitude.  Coherence weighting and display
compression are added only after the physical focusing parameters are chosen.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
from bench_client import request  # noqa: E402
from bench_render import wire_metrics  # noqa: E402


BOX = [-25.0, 25.0, 5.0, 35.0]
SEARCHES = {
    # Target positions after removing the acquired per-element transmit trim.
    "left": [-10.0, -4.0, 16.5, 21.5],
    "right": [5.0, 11.0, 18.0, 23.5],
}


def merged(base, change):
    result = copy.deepcopy(base)
    for section, values in change.items():
        result.setdefault(section, {}).update(values)
    return result


def clean_number(value):
    return None if value is None or not math.isfinite(value) else float(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path)
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    session = args.session.resolve()
    control = args.control_dir.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    base_patch = {
        "receive": {
            "avg_sweeps": 1,
            "frequency_compounding": False,
            "bg_subtract": False,
            "dejitter_on": False,
            "matched_filter": False,
        },
        "beamformer": {"cf": 0.0},
        "display": {
            "debug_view": 1,
            "auto_gain": False,
            "dyn_db": 72.0,
            "gain_db": 25.0,
            "curve": 0.9,
        },
    }
    trials = []
    anchors = {}
    baseline_metrics = None
    counter = 0

    def render(label, patch):
        nonlocal counter, baseline_metrics
        counter += 1
        name = f"{counter:03d}-{label}"
        directory = output / name
        response = request(
            control,
            {
                "op": "render",
                "session": str(session),
                "frame": 0,
                "settings": patch,
                "box_mm": BOX,
                "search_mm": SEARCHES["left"],
                "output": str(directory),
            },
            timeout=60,
        )
        mag = np.load(directory / "magnitude.npy", allow_pickle=False)
        target_metrics = {}
        for target, search in SEARCHES.items():
            anchor = anchors.get(target)
            values = wire_metrics(mag, BOX, search, anchor, exclusion_mm=3.0)
            values = {key: clean_number(value) if isinstance(value, float) else value
                      for key, value in values.items()}
            target_metrics[target] = values
            if anchor is None:
                anchors[target] = values["peak_position_mm"]
        if baseline_metrics is None:
            baseline_metrics = target_metrics

        valid = True
        parts = []
        for target, values in target_metrics.items():
            baseline = baseline_metrics[target]
            lateral = values["lateral_width_6db_mm"]
            axial = values["axial_width_6db_mm"]
            dx = abs(values["peak_position_mm"][0] - baseline["peak_position_mm"][0])
            dz = abs(values["peak_position_mm"][1] - baseline["peak_position_mm"][1])
            # A candidate is not allowed to win by jumping from the wire to a
            # different bright point on its curved sidelobe.
            if (lateral is None or axial is None or values["peak"] < 0.35 * baseline["peak"]
                    or dx > 1.5 or dz > 2.0):
                valid = False
                continue
            parts.append(math.log(lateral / baseline["lateral_width_6db_mm"])
                         + 0.15 * math.log(axial / baseline["axial_width_6db_mm"])
                         + 0.20 * math.log(max(values["clutter_to_target_energy"], 1e-12)
                                           / max(baseline["clutter_to_target_energy"], 1e-12))
                         + 0.15 * max(0.0, math.log(baseline["peak"] / values["peak"])))
        score = float(np.mean(parts)) if valid and len(parts) == 2 else None
        item = {
            "name": name,
            "score": score,
            "patch": copy.deepcopy(patch),
            "targets": target_metrics,
            "image": response["image"],
            "settings": str(directory / "settings.json"),
        }
        trials.append(item)
        widths = ", ".join(
            f"{key}={value['lateral_width_6db_mm']:.3f}mm"
            if value["lateral_width_6db_mm"] is not None else f"{key}=unresolved"
            for key, value in target_metrics.items()
        )
        print(f"{name}: score={score!s} {widths}", flush=True)
        return item

    baseline = render("baseline", base_patch)
    current = baseline

    def group(label, changes):
        nonlocal current
        entering = copy.deepcopy(current["patch"])
        items = [render(f"{label}-{index:02d}", merged(entering, change))
                 for index, change in enumerate(changes)]
        candidates = [item for item in items if item["score"] is not None]
        if candidates:
            best = min(candidates, key=lambda item: item["score"])
            if current["score"] is None or best["score"] < current["score"]:
                current = best
        print(f"SELECT {label}: {current['name']} score={current['score']}", flush=True)

    # Coarse coordinate search, followed by local refinement.  Keeping each
    # group based on one entering state prevents an ordering advantage inside a
    # group and makes the output reproducible.
    group("radius", [{"beamformer": {"R_mm": value}}
                     for value in (56, 58, 60, 61.1, 62, 64, 66, 67.52, 70)])
    group("pitch", [{"beamformer": {"pitch_mm": value}}
                    for value in np.arange(0.328, 0.3481, 0.0025)])
    group("speed", [{"beamformer": {"c_m_s": value}}
                    for value in range(1470, 1561, 10)])
    group("timezero", [{"beamformer": {"t0_ns": value}}
                       for value in range(1700, 2701, 100)])

    settings_path = Path(current["settings"])
    chosen = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    centre = chosen["beamformer"]
    group("radius-fine", [{"beamformer": {"R_mm": round(centre["R_mm"] + value, 2)}}
                          for value in np.arange(-3.0, 3.01, 0.5)])
    chosen = json.loads(Path(current["settings"]).read_text(encoding="utf-8-sig"))
    centre = chosen["beamformer"]
    group("pitch-fine", [{"beamformer": {"pitch_mm": round(centre["pitch_mm"] + value, 4)}}
                         for value in np.arange(-0.006, 0.0061, 0.001)])
    group("speed-fine", [{"beamformer": {"c_m_s": value}}
                         for value in range(int(centre["c_m_s"] - 20), int(centre["c_m_s"] + 21), 5)])
    group("timezero-fine", [{"beamformer": {"t0_ns": value}}
                            for value in np.arange(centre["t0_ns"] - 100,
                                                   centre["t0_ns"] + 101, 25)])

    group("aperture-apod", [
        {"beamformer": {"accept_deg": accept, "apod": apod}}
        for accept in (18, 22, 26, 30, 36, 45, 60)
        for apod in (0.0, 0.25, 0.5, 0.75, 1.0)
    ])
    group("band", [
        {"receive": {"bandpass_on": True, "band_f0_mhz": f0, "band_bw_mhz": bw}}
        for f0 in (3.0, 3.5, 4.0, 4.5, 5.0)
        for bw in (3.0, 4.0, 5.0, 6.0)
    ])
    group("matched", [{"receive": {"matched_filter": value}} for value in (False, True)])

    # Coherence weighting is a final visualization choice.  It is not allowed
    # to win the physical-resolution search because it is nonlinear and can
    # suppress real gelatin backscatter along with sidelobes.
    physical = current
    weighted = render("weighted-detail", merged(physical["patch"], {
        "beamformer": {"cf": 0.35},
        "display": {"debug_view": 0, "dyn_db": 60.0, "gain_db": 24.0, "curve": 0.85},
    }))
    tissue = render("weighted-tissue", merged(physical["patch"], {
        "beamformer": {"cf": 0.15},
        "display": {"debug_view": 0, "dyn_db": 66.0, "gain_db": 25.0, "curve": 0.9},
    }))

    selected_settings = json.loads(Path(tissue["settings"]).read_text(encoding="utf-8-sig"))
    selected_settings["transmit"]["armed"] = False
    selected_settings["note"] = (
        "Two-wire gelatin replay optimization; ordinary-DAS focus selected on both wires, "
        "then modest CF=0.15 retained to preserve backscatter."
    )
    (output / "selected-settings.json").write_text(
        json.dumps(selected_settings, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "session": str(session),
        "box_mm": BOX,
        "anchors_mm": anchors,
        "baseline": baseline,
        "selected_physical": physical,
        "selected_tissue_display": tissue,
        "wire_detail_display": weighted,
        "trials": trials,
    }
    (output / "analysis.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "analysis": str(output / "analysis.json"),
        "settings": str(output / "selected-settings.json"),
        "physical": physical["name"],
        "tissue": tissue["name"],
        "detail": weighted["name"],
    }, indent=2))


if __name__ == "__main__":
    main()
