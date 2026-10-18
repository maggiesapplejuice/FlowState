"""The controller check: does the Siemens controller's valve and pump command match what it normally does?

A model learns, from normal operation only, what the level controller commands (valve LCV01D, pump LCP01D)
given the water level, its setpoints, the flow, the pressure and the hydro-turbine demand over the last
30 seconds. An attacker who changes or replays a command creates a gap between the actual command and the
expected one. The alarm rule is fixed in advance and calibrated on held-out normal data only.
"""
import numpy as np
import pandas as pd
from scipy.stats import chi2
from xgboost import XGBRegressor

INPUTS = ["P3_LIT01", "P3_LH01", "P3_LL01", "P4_HT_FD", "P4_HT_PO", "P4_HT_PS", "P4_LD", "P3_FIT01", "P3_PIT01"]
TARGETS = ["P3_LCV01D", "P3_LCP01D"]
LAGS = (5, 15, 30)
RULE = {"quantile": 0.999, "smooth_s": 10, "hold_s": 10, "grace_s": 60}


def segments(df):
    """Recording segments: a new one starts after any gap over 5 seconds."""
    return (df.timestamp.diff().dt.total_seconds().fillna(999) > 5).cumsum().to_numpy()


def features(df):
    seg = segments(df)
    g = df.groupby(seg)
    f = pd.DataFrame(index=df.index)
    for c in INPUTS:
        f[c] = df[c]
        for lag in LAGS:
            f[f"{c}_lag{lag}"] = g[c].shift(lag)
    for c in TARGETS:  # the controller's own command 30 seconds ago is legitimate context
        f[f"{c}_lag30"] = g[c].shift(30)
    return f.bfill().ffill()


class ControllerCheck:
    def __init__(self, rule=RULE):
        self.rule = dict(rule)
        self.models, self.sd, self.threshold = {}, {}, None

    def fit(self, normal):
        X = features(normal).to_numpy()[::3]
        for t in TARGETS:
            m = XGBRegressor(n_estimators=300, max_depth=6, learning_rate=0.1, subsample=0.8,
                             colsample_bytree=0.8, tree_method="hist", n_jobs=3)
            m.fit(X, normal[t].to_numpy()[::3])
            self.models[t] = m
        return self

    def expected(self, df):
        X = features(df).to_numpy()
        return pd.DataFrame({t: self.models[t].predict(X) for t in TARGETS}, index=df.index)

    def raw_score(self, df):
        exp = self.expected(df)
        return np.max([np.abs(df[t].to_numpy() - exp[t].to_numpy()) / self.sd[t] for t in TARGETS], axis=0)

    def calibrate(self, normal_holdout):
        exp = self.expected(normal_holdout)
        self.sd = {t: float(np.std(normal_holdout[t].to_numpy() - exp[t].to_numpy())) for t in TARGETS}
        s = self.score(normal_holdout)
        self.threshold = float(np.quantile(s, self.rule["quantile"]))
        return self

    def score(self, df):
        seg = segments(df)
        return pd.Series(self.raw_score(df)).groupby(seg).transform(
            lambda x: x.rolling(self.rule["smooth_s"], min_periods=1).median()).to_numpy()

    def alarms(self, df, score=None):
        s = self.score(df) if score is None else score
        flag = s > self.threshold
        seg = segments(df)
        grp = np.cumsum(np.r_[True, (flag[1:] != flag[:-1]) | (seg[1:] != seg[:-1])])
        run = pd.Series(flag.astype(int)).groupby(grp).cumsum().to_numpy()
        return flag & (run >= self.rule["hold_s"])


def poisson_range(k, hours):
    """95% range for an event rate per day, from k events in `hours`."""
    lo = chi2.ppf(0.025, 2 * k) / 2 if k else 0.0
    hi = chi2.ppf(0.975, 2 * (k + 1)) / 2
    return lo / hours * 24, hi / hours * 24


def evaluate(df, alarm, episodes, grace_s=RULE["grace_s"]):
    """Per-attack catches and time to flag; false alarms = alarms that start in attack-free time."""
    ts = df.timestamp.to_numpy()
    rows = []
    for _, e in episodes.iterrows():
        b = min(e.i1 + grace_s, len(alarm) - 1)
        hit = np.flatnonzero(alarm[e.i0:b + 1])
        rows.append({**e.to_dict(), "caught": len(hit) > 0,
                     "seconds_to_flag": float((ts[e.i0 + hit[0]] - ts[e.i0]) / np.timedelta64(1, "s")) if len(hit) else None})
    res = pd.DataFrame(rows)
    clean = df["attack"].to_numpy() == 0
    ac = alarm & clean
    starts = np.flatnonzero(ac & ~np.r_[False, ac[:-1]])
    hours = clean.sum() / 3600
    lo, hi = poisson_range(len(starts), hours)
    fa = {"false_alarms": int(len(starts)), "attack_free_hours": round(hours, 1),
          "per_day": round(len(starts) / hours * 24, 2), "per_day_range": [round(lo, 2), round(hi, 2)],
          "times": [str(df.timestamp.iloc[i]) for i in starts]}
    return res, fa


class LevelReference:
    """Where the tank level should be: the level 30 s ago plus the change the controller's *normal*
    commands would have produced. During an attack the actual level drifts away from this line.
    This is a display reference, not the alarm: on normal data it is accurate to about 0.7 % of
    scale, and a drift of up to about 2 % happens in normal operation too.
    """
    H = 30

    def __init__(self):
        self.model = None

    def _features(self, df, valve, pump):
        seg = segments(df)
        g = lambda s: pd.Series(np.asarray(s), index=df.index).groupby(seg)
        f = pd.DataFrame(index=df.index)
        f["level_prev"] = g(df.P3_LIT01).shift(self.H)
        f["flow_prev"] = g(df.P3_FIT01).shift(self.H)
        f["demand"] = df.P4_HT_PS
        f["load"] = df.P4_LD
        f["valve_mean"] = g(valve).transform(lambda s: s.rolling(self.H, min_periods=1).mean())
        f["pump_mean"] = g(pump).transform(lambda s: s.rolling(self.H, min_periods=1).mean())
        return f.bfill().ffill()

    def fit(self, normal):
        from xgboost import XGBRegressor
        y = (normal.P3_LIT01 - normal.P3_LIT01.groupby(segments(normal)).shift(self.H)).bfill()
        X = self._features(normal, normal.P3_LCV01D, normal.P3_LCP01D)
        self.model = XGBRegressor(n_estimators=300, max_depth=5, learning_rate=0.1, subsample=0.8,
                                  tree_method="hist", n_jobs=3)
        self.model.fit(X.to_numpy()[::3], y.to_numpy()[::3])
        return self

    def expected_level(self, df, expected_commands):
        """Level (raw counts) the tank should be at if the controller had issued its normal commands."""
        prev = df.P3_LIT01.groupby(segments(df)).shift(self.H).bfill()
        X = self._features(df, expected_commands["P3_LCV01D"], expected_commands["P3_LCP01D"])
        return prev.to_numpy() + self.model.predict(X.to_numpy())
