"""Replay a recorded dataset as if it were a live utility feed.

Story mode (speed=1.0) sends one reading per recorded second, for the demo video.
Batch mode (speed=None) sends everything as fast as possible, for the scoreboard.
"""
import time


def replay(df, speed=None, start=None, end=None, time_col="timestamp"):
    """Yield rows of `df` in time order, optionally limited to [start, end]."""
    view = df
    if start is not None:
        view = view[view[time_col] >= start]
    if end is not None:
        view = view[view[time_col] <= end]
    prev_t = None
    for _, row in view.iterrows():
        if speed and prev_t is not None:
            gap = (row[time_col] - prev_t).total_seconds()
            if 0 < gap < 60:  # skip long recording gaps instead of waiting
                time.sleep(gap / speed)
        prev_t = row[time_col]
        yield row
