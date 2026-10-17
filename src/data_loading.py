"""Load the project's one dataset: HAI's water process, run by a Siemens S7-300 PLC.

HAI (HIL-based Augmented ICS) security dataset, https://github.com/icsdataset/hai (CC BY-SA 4.0).
The water process (P3) pumps water into an upper tank; a hydro-turbine simulation (P4_HT) sets the demand.
Descriptions below are from HAI's technical document (v4.0, May 2023).
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"

WATER_TAGS = {
    "P3_LIT01": "Upper tank water level (%)",
    "P3_LH01": "High water level setpoint (%)",
    "P3_LL01": "Low water level setpoint (%)",
    "P3_LCV01D": "Valve position command",
    "P3_LCP01D": "Pump speed command",
    "P3_FIT01": "Flow into the upper tank",
    "P3_PIT01": "Pressure into the upper tank",
}
HYDRO_TAGS = {
    "P4_HT_FD": "Hydro turbine frequency deviation",
    "P4_HT_PO": "Hydro turbine output power (MW)",
    "P4_HT_PS": "Hydro turbine scheduled power (MW)",
    "P4_LD": "Total electrical load demand (MW)",
}
COLUMNS = list(WATER_TAGS) + list(HYDRO_TAGS)
NAMES = {**WATER_TAGS, **HYDRO_TAGS}

FILES = {
    ("22.04", "train"): [f"train{i}" for i in range(1, 7)],
    ("22.04", "test"): [f"test{i}" for i in range(1, 5)],
    ("23.05", "train"): [f"hai-train{i}" for i in range(1, 5)],
    ("23.05", "test"): ["hai-test1", "hai-test2"],
}


def load_hai(version, files):
    """Water-process columns plus an `attack` flag (1 = any attack running) for the given HAI files."""
    frames = []
    for name in files:
        folder = RAW / f"hai-{version}"
        cols = ["timestamp"] + COLUMNS + (["Attack"] if version == "22.04" else [])
        df = pd.read_csv(folder / f"{name}.csv", usecols=cols, parse_dates=["timestamp"])
        if version == "22.04":
            df = df.rename(columns={"Attack": "attack"})
        elif name.startswith("hai-test"):
            # HAI 23.05 label-test2.csv stores times rounded to the minute, so labels cannot be joined on
            # time. Label and data files have the same rows in the same order: align them by position and
            # check that every row falls in the same minute.
            lab = pd.read_csv(folder / (name.replace("hai-test", "label-test") + ".csv"), parse_dates=["timestamp"])
            if len(lab) != len(df):
                raise ValueError(f"{name}: {len(df)} data rows but {len(lab)} label rows")
            off = (df.timestamp.dt.floor("min").to_numpy() - lab.timestamp.dt.floor("min").to_numpy())
            bad = int((np.abs(off.astype("timedelta64[s]").astype(int)) > 60).sum())
            if bad:
                raise ValueError(f"{name}: {bad} label rows more than a minute away from their data row")
            df["attack"] = lab["label"].to_numpy()
        else:
            df["attack"] = 0
        df["attack"] = df["attack"].fillna(0).astype(int)
        df["version"], df["file"] = version, name
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)


# Attacks that hit the water process, from HAI's own attack tables (technical document pp. 31-35).
# Start times are matched to the dataset's attack labels (they agree within about 20 seconds).
ATTACK_TYPES = {
    "AP35": "Pump command replaced with an earlier value",
    "AP36": "Pump command changed while the level reading is frozen",
    "AP37": "Valve command pushed up or down, then restored",
    "AP38": "Valve command changed while the level reading is frozen",
    "AP39": "Valve command changed for more than 10 minutes",
}
WATER_ATTACKS = pd.DataFrame([
    # id, version, documented start, water scenario(s), simultaneous attack elsewhere
    ("A104", "22.04", "2021-07-10 15:39", "AP37", None),
    ("A205", "22.04", "2021-07-13 21:10", "AP37", None),
    ("A212", "22.04", "2021-07-14 08:11", "AP35", None),
    ("A214", "22.04", "2021-07-14 11:23", "AP39", None),
    ("A303", "22.04", "2021-07-14 23:22", "AP37", "boiler"),
    ("A304", "22.04", "2021-07-15 01:41", "AP38", None),   # table lists P1 target points: a typo in HAI's document
    ("A310", "22.04", "2021-07-15 09:52", "AP35+AP37", None),
    ("A404", "22.04", "2021-07-15 15:08", "AP37", "turbine"),
    ("A414", "22.04", "2021-07-16 07:20", "AP36", "turbine"),
    ("A419", "22.04", "2021-07-16 14:59", "AP35", "boiler"),
    ("A231", "23.05", "2022-08-19 04:34", "AP35", "boiler"),
], columns=["id", "version", "documented_start", "scenario", "also_hits"])
# HAI's table entries whose target is contradictory (a water scenario code with boiler points, or the reverse).
# They are left out of both the water and non-water counts and reported separately.
AMBIGUOUS = pd.DataFrame([("A301", "22.04", "2021-07-14 18:21"), ("A305", "22.04", "2021-07-15 02:09")],
                         columns=["id", "version", "documented_start"])


def attack_episodes(df):
    """Each unbroken run of attack seconds, tagged as a water-process attack, ambiguous, or elsewhere."""
    a = df["attack"].to_numpy()
    starts = [i for i in range(len(a)) if a[i] == 1 and (i == 0 or a[i - 1] == 0)]
    ends = [i for i in range(len(a)) if a[i] == 1 and (i == len(a) - 1 or a[i + 1] == 0)]
    eps = pd.DataFrame({"i0": starts, "i1": ends})
    eps["start"], eps["end"] = df.timestamp.values[eps.i0], df.timestamp.values[eps.i1]
    eps["version"] = df.version.values[eps.i0]
    eps["seconds"] = eps.i1 - eps.i0 + 1
    eps["id"], eps["target"], eps["scenario"], eps["also_hits"] = None, "elsewhere", None, None
    for table, target in [(WATER_ATTACKS, "water"), (AMBIGUOUS, "ambiguous")]:
        for _, row in table.iterrows():
            same = eps[eps.version == row.version]
            if same.empty:
                continue
            gap = (same.start - pd.Timestamp(row.documented_start)).abs()
            j = gap.idxmin()
            if gap[j] <= pd.Timedelta("5min"):
                eps.loc[j, ["id", "target"]] = [row.id, target]
                if target == "water":
                    eps.loc[j, ["scenario", "also_hits"]] = [row.scenario, row.also_hits]
    return eps
