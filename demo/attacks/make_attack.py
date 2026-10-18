"""Make a simulated attack episode for the WaterProject replay server from a real stretch of HAI data.

The output CSV is one row per second with the 11 water-process tags the controller check reads, in the raw
Siemens counts HAI records, plus an `attack` label (1 while the injected attack runs). The sensor columns are
left exactly as recorded; only the attacked command column (and, for the level-freeze kind, the level
reading) is changed, in the same way HAI's own attacks AP35-AP39 change them. See FORMAT.md next to this file.

Run inside the container, from ~/WaterProject:

    python demo/attacks/make_attack.py --source test1 --start "2021-07-10 12:47:00" \
        --kind pump_replay --out demo/attacks/sample_pump_replay.csv --verify

    python demo/attacks/make_attack.py --scan --source test1        # list quiet attack-free 15-minute stretches

Kinds (what the attacker does to the controller's output, modelled on HAI's attack catalogue):
    pump_replay   LCP01D replaced by its own value --shift seconds earlier (HAI AP35, as in A212/A310/A419)
    pump_offset   LCP01D pushed by --delta counts (and clipped to 0..27648)
    pump_hold     LCP01D frozen at --value, or at its value when the attack starts
    valve_hold    LCV01D frozen at --value, or at its value when the attack starts (HAI AP39 style, as in A214)
    valve_offset  LCV01D pushed by --delta counts, then restored when the attack ends (HAI AP37, as in A104)
    pump_freeze_level  LIT01 (level reading) frozen on the operator screen while LCP01D is pushed by --delta (HAI AP36, as in A414)

--verify scores the file with the saved controller check (data/processed/controller_check.pkl) the same way
the server does, and prints seconds to alarm, alarms before the attack and the peak mismatch. The first
--warmup rows are treated as the server's warm-up (scored, not shown), so alarms there are reported separately.
"""
import argparse, pickle, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.data_loading import load_hai, COLUMNS, PROCESSED   # noqa: E402

OUT_COLUMNS = ["timestamp"] + COLUMNS + ["attack"]
FULL_SCALE = 27648          # Siemens analog full scale, raw counts
KINDS = ["pump_replay", "pump_offset", "pump_hold", "valve_hold", "valve_offset", "pump_freeze_level"]


def cut_window(version, source, start, n):
    """n consecutive seconds of `source` starting at `start`, all 11 tags plus the HAI attack flag."""
    df = load_hai(version, [source])
    ts = df.timestamp.to_numpy()
    i0 = int(np.searchsorted(ts, np.datetime64(pd.Timestamp(start))))
    if i0 >= len(df) or i0 + n > len(df):
        raise SystemExit(f"{source} runs {df.timestamp.iloc[0]} .. {df.timestamp.iloc[-1]}; "
                         f"{start} + {n} s does not fit")
    w = df.iloc[i0:i0 + n][OUT_COLUMNS].reset_index(drop=True).copy()
    gaps = w.timestamp.diff().dt.total_seconds().iloc[1:]
    if (gaps != 1).any():
        raise SystemExit(f"window has {int((gaps != 1).sum())} gaps/duplicates in the timestamps; pick another start")
    return w


def inject(df, kind, a0, a1, shift, delta, value):
    """Overwrite rows a0..a1-1 of the attacked column in place, return a one-line description."""
    df["attack"] = 0
    if kind == "pump_replay":
        if a0 < shift:
            raise SystemExit(f"--lead must be at least --shift ({shift}) so the replayed values exist")
        df.loc[a0:a1 - 1, "P3_LCP01D"] = df["P3_LCP01D"].shift(shift).iloc[a0:a1].to_numpy().astype(int)
        what = f"pump command LCP01D replaced by its value {shift} s earlier"
    elif kind == "pump_offset":
        v = (df["P3_LCP01D"].iloc[a0:a1] + delta).clip(0, FULL_SCALE).astype(int)
        df.loc[a0:a1 - 1, "P3_LCP01D"] = v.to_numpy(); what = f"pump command LCP01D pushed by {delta:+d} counts"
    elif kind == "pump_hold":
        v = int(df["P3_LCP01D"].iloc[a0]) if value is None else int(value)
        df.loc[a0:a1 - 1, "P3_LCP01D"] = v; what = f"pump command LCP01D held at {v} counts"
    elif kind == "valve_hold":
        v = int(df["P3_LCV01D"].iloc[a0]) if value is None else int(value)
        df.loc[a0:a1 - 1, "P3_LCV01D"] = v; what = f"valve command LCV01D held at {v} counts"
    elif kind == "valve_offset":
        v = (df["P3_LCV01D"].iloc[a0:a1] + delta).clip(-FULL_SCALE, FULL_SCALE).astype(int)
        df.loc[a0:a1 - 1, "P3_LCV01D"] = v.to_numpy(); what = f"valve command LCV01D pushed by {delta:+d} counts"
    elif kind == "pump_freeze_level":
        df.loc[a0:a1 - 1, "P3_LIT01"] = int(df["P3_LIT01"].iloc[a0])
        v = (df["P3_LCP01D"].iloc[a0:a1] + delta).clip(0, FULL_SCALE).astype(int)
        df.loc[a0:a1 - 1, "P3_LCP01D"] = v.to_numpy()
        what = f"level reading LIT01 frozen at {int(df['P3_LIT01'].iloc[a0])} while pump command LCP01D pushed by {delta:+d} counts"
    else:
        raise SystemExit(f"unknown kind {kind}; choose from {KINDS}")
    df.loc[a0:a1 - 1, "attack"] = 1
    return what


def verify(df, a0, a1, warmup):
    """Score like the server: whole file in one causal pass, saved model, saved threshold, 10 s hold rule."""
    m = pickle.load(open(PROCESSED / "controller_check.pkl", "rb"))
    exp = m.expected(df)
    score = m.score(df)
    alarm = m.alarms(df, score)
    thr = m.threshold
    starts = np.flatnonzero(alarm & ~np.r_[False, alarm[:-1]])
    hits = np.flatnonzero(alarm[a0:])
    gap = {t: (df[t].to_numpy() - exp[t].to_numpy()) for t in ("P3_LCV01D", "P3_LCP01D")}
    worst = {t: int(np.abs(gap[t][a0:a1]).max()) for t in gap}
    rep = {
        "threshold": round(thr, 3),
        "rows": len(df), "warmup_rows": warmup, "attack_rows": [a0, a1 - 1],
        "seconds_to_alarm": int(hits[0]) if len(hits) else None,
        "alarm_seconds_during_attack": int(alarm[a0:a1].sum()),
        "alarm_seconds_after_attack": int(alarm[a1:].sum()),
        "false_alarm_starts_before_attack(shown rows)": int(((starts >= warmup) & (starts < a0)).sum()),
        "alarm_rows_in_warmup": int(alarm[:warmup].sum()),
        "peak_score_over_threshold_before_attack": round(float(score[warmup:a0].max() / thr), 3),
        "peak_score_over_threshold_during_attack": round(float(score[a0:a1].max() / thr), 3),
        "peak_command_gap_counts(valve,pump)": worst,
        "peak_gap_in_sd_units(valve,pump)": {t: round(worst[t] / m.sd[t], 1) for t in worst},
    }
    return rep


def scan(version, source, window=900, margin=1800):
    """Attack-free windows of `window` seconds (at least `margin` seconds from any real attack), with the
    saved model's peak score in each, so you can pick a quiet stretch to build on."""
    m = pickle.load(open(PROCESSED / "controller_check.pkl", "rb"))
    df = load_hai(version, [source])
    a = df.attack.to_numpy()
    score = m.score(df); alarm = m.alarms(df, score)
    print(f"{source}: {len(df)} rows {df.timestamp.iloc[0]} .. {df.timestamp.iloc[-1]}, {int(a.sum())} attack rows")
    print("start                 peak_score/threshold  alarm_s  level_%_min..max")
    for i0 in range(0, len(df) - window, window):
        i1 = i0 + window
        if a[max(0, i0 - margin):min(len(a), i1 + margin)].any():
            continue
        seg = df.iloc[i0:i1]
        print(f"{seg.timestamp.iloc[0]}  {score[i0:i1].max() / m.threshold:6.3f}  {int(alarm[i0:i1].sum()):7d}  "
              f"{seg.P3_LIT01.min() / FULL_SCALE * 100:5.1f}..{seg.P3_LIT01.max() / FULL_SCALE * 100:5.1f}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", default="22.04", help="HAI version folder under data/raw (22.04 or 23.05)")
    p.add_argument("--source", default="test1", help="HAI file name without .csv, e.g. test1 or train3")
    p.add_argument("--start", default="2021-07-10 12:47:00", help="timestamp of the first row of the output")
    p.add_argument("--lead", type=int, default=240, help="seconds of normal data before the attack (includes the server's 60 s warm-up)")
    p.add_argument("--duration", type=int, default=180, help="attack length in seconds")
    p.add_argument("--tail", type=int, default=480, help="seconds of normal data after the attack")
    p.add_argument("--kind", default="pump_replay", choices=KINDS)
    p.add_argument("--shift", type=int, default=60, help="pump_replay: how many seconds earlier the replayed value comes from")
    p.add_argument("--delta", type=int, default=4000, help="*_offset / pump_freeze_level: counts added to the command")
    p.add_argument("--value", type=int, default=None, help="*_hold: counts to hold at (default: the value at attack start)")
    p.add_argument("--warmup", type=int, default=60, help="rows the server treats as warm-up (scored, not shown)")
    p.add_argument("--out", default=None, help="output CSV path (default demo/attacks/<kind>_<source>_<start>.csv)")
    p.add_argument("--verify", action="store_true", help="score the output with the saved controller check and report")
    p.add_argument("--scan", action="store_true", help="only list quiet attack-free stretches of --source, then exit")
    args = p.parse_args()

    if args.scan:
        scan(args.version, args.source); return
    n = args.lead + args.duration + args.tail
    a0, a1 = args.lead, args.lead + args.duration
    df = cut_window(args.version, args.source, args.start, n)
    if df.attack.any():
        raise SystemExit(f"the chosen stretch already contains {int(df.attack.sum())} s of a real HAI attack; "
                         f"run with --scan to find a quiet one")
    what = inject(df, args.kind, a0, a1, args.shift, args.delta, args.value)
    out = Path(args.out) if args.out else ROOT / "demo" / "attacks" / f"{args.kind}_{args.source}_{pd.Timestamp(args.start):%Y%m%d_%H%M%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, date_format="%Y-%m-%d %H:%M:%S")
    print(f"wrote {out}: {len(df)} rows, {df.timestamp.iloc[0]} .. {df.timestamp.iloc[-1]}")
    print(f"attack rows {a0}..{a1 - 1} ({df.timestamp.iloc[a0]} .. {df.timestamp.iloc[a1 - 1]}): {what}")
    print(f"shown lead-in (after the server's {args.warmup} s warm-up): {a0 - args.warmup} s")
    if args.verify:
        rep = verify(pd.read_csv(out, parse_dates=["timestamp"]), a0, a1, args.warmup)
        for k, v in rep.items():
            print(f"  {k}: {v}")
        if rep["seconds_to_alarm"] is None or rep["seconds_to_alarm"] >= args.duration:
            print("  RESULT: NO ALARM during the attack. Try a larger --delta / --shift or a different --kind or --start.")
        elif rep["false_alarm_starts_before_attack(shown rows)"]:
            print("  RESULT: alarms before the attack starts; pick a quieter --start (see --scan).")
        else:
            print(f"  RESULT: OK, alarm {rep['seconds_to_alarm']} s after the attack begins, none before it.")


if __name__ == "__main__":
    main()
