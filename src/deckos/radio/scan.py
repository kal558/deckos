"""Find stations in an `rtl_power` sweep."""
from __future__ import annotations

import statistics

SAME_STATION_HZ = 150e3


def find_peaks(csv_text: str, threshold_db: float = 8.0, merge_hz: float = SAME_STATION_HZ) -> list[float]:
    """Frequencies of signals standing `threshold_db` above the median noise floor.

    rtl_power CSV rows: date, time, low_hz, high_hz, step_hz, samples, dB, dB, ...
    Adjacent strong bins closer than `merge_hz` are one station (the strongest bin wins).
    """
    bins: list[tuple[float, float]] = []
    for line in csv_text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            lo, step = float(parts[2]), float(parts[4])
            powers = [float(p) for p in parts[6:] if p not in ("", "nan", "-nan")]
        except ValueError:
            continue
        bins += [(lo + (i + 0.5) * step, p) for i, p in enumerate(powers)]
    if not bins:
        return []
    floor = statistics.median(p for _, p in bins)
    strong = [(f, p) for f, p in bins if p > floor + threshold_db]
    peaks: list[tuple[float, float]] = []
    for f, p in sorted(strong):
        if peaks and f - peaks[-1][0] < merge_hz:
            if p > peaks[-1][1]:
                peaks[-1] = (f, p)
        else:
            peaks.append((f, p))
    return [f for f, _ in peaks]
