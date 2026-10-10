"""Frame times shared by both video readers."""
import numpy as np


def sample_timestamps(
    duration: float,
    samples_per_video: int = 4,
    sample_every_seconds: float = 0.0,
    max_samples_per_video: int = 0,
) -> list[float]:
    if duration <= 0:
        return []
    if sample_every_seconds > 0:
        if duration < sample_every_seconds:
            timestamps = [duration / 2]
        else:
            start = min(max(1.0, sample_every_seconds / 2), duration / 2)
            stop = max(start, duration - start)
            timestamps = list(np.arange(start, stop + 0.001, sample_every_seconds))
        if max_samples_per_video > 0:
            if len(timestamps) > max_samples_per_video:
                timestamps = [float(t) for t in np.linspace(timestamps[0], timestamps[-1], max_samples_per_video)]
        return [round(float(timestamp), 3) for timestamp in timestamps]
    if duration < 5:
        return [duration / 2]
    fractions = np.linspace(0.15, 0.85, samples_per_video)
    return [round(float(duration * fraction), 3) for fraction in fractions]

