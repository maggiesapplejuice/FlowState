"""Live demo: replay real HAI attacks on the Siemens water process as the one-way tap feed, score each
second with the controller check on IBM LinuxONE, and serve the watch UI.

Run inside the Jupyter container, from ~/WaterProject:
    podman exec -d -w /home/ibm-user/WaterProject notebook python demo/replay_server.py
then on your laptop:  ssh -L 38891:localhost:38891 ...   and open http://localhost:38891

The scoring is causal: every feature looks only at the current and earlier seconds, and the alarm rule
only at earlier scores. The server scores a loaded episode in one pass (same arithmetic as live, done
on this machine) and then releases one second at a time at the chosen speed.
"""
import json, pickle, platform, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_loading import load_hai, FILES, attack_episodes, ATTACK_TYPES, PROCESSED, NAMES
from src.water_model import ControllerCheck, LevelReference, TARGETS, RULE

PORT = 38891
WARMUP = 60          # extra seconds loaded before the shown window so lag features and the alarm rule have history
FULL_SCALE = 27648.0  # Siemens analog full scale: the tank level is recorded in raw counts (27648 = 100 %)
UI = ROOT / "demo" / "ui"
CONSOLE = ROOT / "demo" / "console" / "template.html"
PLANT_THEME = ROOT / "demo" / "console" / "plant.css"   # optional restyle for the single-plant view, read per request
RESULTS_JSON = ROOT / "dashboard" / "data.json"
RECOMPUTE = {"state": "idle", "error": None, "started": None}
MODEL_PKL = PROCESSED / "controller_check.pkl"
LEVEL_PKL = PROCESSED / "level_reference.pkl"
BRIEF_MODEL = ROOT / "models" / "granite-3.3-2b-instruct-be.Q4_K_M.gguf"
ATTACKS = ROOT / "demo" / "attacks"   # simulated attack files (CSV, one row per second; format in demo/attacks/FORMAT.md)
FILE_COLUMNS = ["timestamp", "P3_LIT01", "P3_LH01", "P3_LL01", "P3_LCV01D", "P3_LCP01D", "P3_FIT01", "P3_PIT01", "P4_HT_FD", "P4_HT_PO", "P4_HT_PS", "P4_LD"]

DEMOS = {  # id: (version, lead-in seconds before the attack, seconds after it ends, note)
    "A214": ("22.04", 180, 150, "Valve command changed for more than 10 minutes"),
    "A310": ("22.04", 180, 150, "Pump command replaced with an earlier value, valve pushed and restored"),
    "A104": ("22.04", 180, 150, "Valve command pushed up or down, then restored"),
    "A414": ("22.04", 180, 150, "Pump command changed while the level reading is frozen on the operator screen"),
}
NORMAL = ("22.04", "2021-07-10 09:00:00", 900)       # a quiet stretch: version, start, seconds
SYNTHETIC = ("22.04", "2021-07-10 10:00:00", 180, 120)  # version, start, lead-in, attack length (pump command replayed)

FIRST_STEPS = ["Switch the affected pump or valve to manual and check the tank level directly.",
               "Disconnect the controller from the internet and remote-access tools.",
               "Change default and shared passwords on the controller and operator screens.",
               "Compare the controller program with your last known-good copy.",
               "Report to CISA and your local FBI field office."]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def platform_info():
    cpu = open("/proc/cpuinfo").read()
    return {"arch": platform.machine(), "nnpa": "nnpa" in cpu.split("features")[1].split("\n")[0],
            "machine_type": cpu.split("machine = ")[1].split()[0] if "machine = " in cpu else None,
            "os": [l.split("=")[1].strip().strip('"') for l in open("/etc/os-release") if l.startswith("PRETTY_NAME")][0]}


def get_models():
    """The controller check (the alarm) and the level reference (a display line). Trained once, then cached."""
    have = MODEL_PKL.exists() and LEVEL_PKL.exists()
    if have:
        log("loading the trained controller check and level reference")
        lr = pickle.load(open(LEVEL_PKL, "rb"))
        if not isinstance(lr, LevelReference):   # an older cache held the bare regressor
            lr, lr.model = LevelReference(), lr
        return pickle.load(open(MODEL_PKL, "rb")), lr
    log("training on normal operation only, about 40 s")
    fit = pd.concat([load_hai("22.04", FILES[("22.04", "train")][:5]), load_hai("23.05", FILES[("23.05", "train")][:3])], ignore_index=True)
    cal = pd.concat([load_hai("22.04", ["train6"]), load_hai("23.05", ["hai-train4"])], ignore_index=True)
    m = ControllerCheck().fit(fit).calibrate(cal)
    lr = LevelReference().fit(fit)
    pickle.dump(m, open(MODEL_PKL, "wb")); pickle.dump(lr, open(LEVEL_PKL, "wb"))
    return m, lr


class Replay:
    def __init__(self):
        self.lock = threading.Lock()
        self.model, self.level_ref = get_models()
        self.platform = platform_info()
        log("loading HAI 22.04 test files")
        self.test = load_hai("22.04", FILES[("22.04", "test")])
        self.eps = attack_episodes(self.test)
        self.llm = None
        self.llm_lock = threading.Lock()   # one brief at a time: a seek during a brief must not start a second model load
        self.episode = None
        self.reset_state()

    def reset_state(self):
        self.i = 0; self.playing = False; self.speed = 1.0; self.alarm_on = False
        self.alarms = []; self.brief = None; self.brief_status = "none"; self.t_last = time.time()

    # ---------- episodes
    def slice(self, version, i0, i1):
        """Rows i0..i1 plus WARMUP seconds before them (cut off again after scoring)."""
        return self.test.iloc[max(0, i0 - WARMUP):i1].reset_index(drop=True)

    def load_episode(self, name):
        with self.lock:
            self.reset_state()
            if name in DEMOS:
                version, lead, tail, note = DEMOS[name]
                e = self.eps[self.eps.id == name].iloc[0]
                df = self.slice(version, max(0, e.i0 - lead), min(len(self.test), e.i1 + tail))
                kind, label = "real", f"{name}: {note}"
            elif name == "normal":
                version, start, secs = NORMAL
                i0 = int(np.searchsorted(self.test.timestamp.values, np.datetime64(start)))
                df = self.slice(version, i0, i0 + secs); kind, label = "normal", "Normal operation (no attack)"
            elif name == "synthetic":
                version, start, lead, length = SYNTHETIC
                i0 = int(np.searchsorted(self.test.timestamp.values, np.datetime64(start)))
                df = self.slice(version, i0, i0 + lead + length + 150)
                # Synthetic attack: the pump command is replaced by the value it had 60 s earlier (a replay attack)
                a0 = min(WARMUP, i0) + lead
                df.loc[a0:a0 + length - 1, "P3_LCP01D"] = df["P3_LCP01D"].shift(60).iloc[a0:a0 + length].to_numpy()
                df.loc[a0:a0 + length - 1, "attack"] = 1
                kind, label = "synthetic", "Synthetic replay attack on the pump command (not from HAI)"
            elif name.startswith("file:"):
                df, version, kind, label = self.load_file(name[5:])
            else:
                raise KeyError(name)
            t0 = time.time()
            exp = self.model.expected(df)
            score = self.model.score(df)
            alarm = self.model.alarms(df, score)
            scored_s = time.time() - t0
            level_exp = self.level_ref.expected_level(df, exp)
            w = min(WARMUP, len(df) - 1)   # drop the warm-up rows from everything shown
            df, exp, score, alarm = df.iloc[w:].reset_index(drop=True), exp.iloc[w:].reset_index(drop=True), score[w:], alarm[w:]
            df["level_pct"] = df["P3_LIT01"] / FULL_SCALE * 100
            df["level_expected_pct"] = level_exp[w:] / FULL_SCALE * 100
            a = df.attack.to_numpy()
            starts = np.flatnonzero((a == 1) & (np.r_[0, a[:-1]] == 0))
            t_attack = int(starts[0]) if len(starts) else None
            self.episode = {"name": name, "kind": kind, "label": label, "version": version, "n": len(df),
                            "t_attack": t_attack, "scored_seconds": round(scored_s, 2),
                            "start_time": str(df.timestamp.iloc[0]), "threshold": self.model.threshold}
            self.df, self.exp, self.score, self.alarm = df, exp, score, alarm
            log(f"episode {name}: {len(df)} s scored on {self.platform['arch']} in {scored_s:.2f} s")
            return self.episode

    @staticmethod
    def attack_files():
        return sorted(p for p in ATTACKS.glob("*.csv") if p.is_file()) if ATTACKS.is_dir() else []

    def load_file(self, fname):
        """A simulated attack file from demo/attacks/: scored like every other episode. Its first WARMUP rows are
        the warm-up and are hidden after scoring, so the file should start 60 s before the stretch to show."""
        path = (ATTACKS / Path(fname).name).resolve()
        if path.suffix != ".csv" or not path.is_file() or ATTACKS.resolve() not in path.parents:
            raise KeyError(f"no attack file named {fname} in demo/attacks/")
        df = pd.read_csv(path)
        missing = [c for c in FILE_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path.name} lacks columns {missing}; see demo/attacks/FORMAT.md")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["attack"] = (df["attack"].fillna(0).astype(int) if "attack" in df.columns else 0)
        df = df.reset_index(drop=True)
        if len(df) < WARMUP + 60:
            raise ValueError(f"{path.name} has {len(df)} rows; at least {WARMUP + 60} are needed")
        return df, "file", "file", f"Attack file {path.name} ({len(df)} s, {int(df.attack.sum())} s labeled attack)"

    # ---------- clock
    def tick(self):
        with self.lock:
            if self.episode is None or not self.playing:
                self.t_last = time.time(); return
            now = time.time()
            steps = int((now - self.t_last) * self.speed)
            if steps <= 0:
                return
            self.t_last += steps / self.speed
            for _ in range(steps):
                if self.i >= self.episode["n"] - 1:
                    self.playing = False; break
                self.i += 1
                on = bool(self.alarm[self.i])
                if on and not self.alarm_on:
                    self.alarms.append({"t": self.i, "time": str(self.df.timestamp.iloc[self.i])})
                    self.start_brief()
                self.alarm_on = on

    # ---------- brief
    def start_brief(self):
        if self.brief_status != "none":
            return
        self.brief_status = "writing"
        i = self.i
        gap = {t: float(abs(self.df[t].iloc[i] - self.exp[t].iloc[i]) / self.model.sd[t]) for t in TARGETS}
        worst = max(gap, key=gap.get)
        what = "valve position command" if worst == "P3_LCV01D" else "pump speed command"
        since = (i - self.episode["t_attack"]) if self.episode["t_attack"] is not None and i >= self.episode["t_attack"] else None
        lvl = self.df.level_pct.iloc[i]; lo_, hi_ = self.df.P3_LL01.iloc[i], self.df.P3_LH01.iloc[i]
        facts = (f"Verdict: attack likely. On the Siemens-controlled water process, the {what} stopped matching what the "
                 f"controller normally commands for this water level, at {self.score[i] / self.model.threshold:.1f} times the alarm level. "
                 f"The water level itself is normal: {lvl:.0f}%, inside its normal range of {lo_:.0f}% to {hi_:.0f}%.")
        self.brief = {"facts": facts, "explanation": None, "steps": FIRST_STEPS, "seconds_after_change": since, "written_in_s": None}
        threading.Thread(target=self.write_brief, args=(facts,), daemon=True).start()

    def write_brief(self, facts):
        t0 = time.time()
        try:
          with self.llm_lock:
            if self.llm is None:
                from llama_cpp import Llama
                self.llm = Llama(model_path=str(BRIEF_MODEL), n_ctx=2048, n_threads=3, verbose=False)
            system = ("You write incident briefs for operators at small water utilities who are not security experts. "
                      "Use only the facts given and never contradict them. Do not invent details. Write exactly two short sentences: "
                      "what most likely happened (a command to the pump or valve was changed, likely by someone who got into the controller), "
                      "and why the system thinks so. Do not call the water level abnormal if the facts say it is normal.")
            out = self.llm.create_chat_completion(messages=[{"role": "system", "content": system}, {"role": "user", "content": facts}],
                                                  max_tokens=90, temperature=0.0)
            text = out["choices"][0]["message"]["content"].strip()
        except Exception as e:  # the brief is optional: the facts and steps are already on screen
            text = f"(language model unavailable: {e})"
        with self.lock:
            if self.brief is not None:
                self.brief["explanation"] = text; self.brief["written_in_s"] = round(time.time() - t0)
                self.brief_status = "done"

    # ---------- state for the UI
    def state(self, since=None):
        self.tick()
        with self.lock:
            if self.episode is None:
                return {"episode": None, "platform": self.platform, "episodes": self.episode_list()}
            i = self.i
            lo = 0 if since is None else max(0, int(since) + 1)
            idx = range(lo, i + 1)
            row = self.df.iloc[i]
            series = {"t": [k - (self.episode["t_attack"] or 0) for k in idx],
                      "level": self.df.level_pct.to_numpy()[lo:i + 1].round(2).tolist(),
                      "level_expected": self.df.level_expected_pct.to_numpy()[lo:i + 1].round(2).tolist(),
                      "high": self.df.P3_LH01.to_numpy()[lo:i + 1].round(2).tolist(),
                      "low": self.df.P3_LL01.to_numpy()[lo:i + 1].round(2).tolist(),
                      "flow": self.df.P3_FIT01.to_numpy()[lo:i + 1].round(1).tolist(),
                      "pressure": self.df.P3_PIT01.to_numpy()[lo:i + 1].round(1).tolist(),
                      "valve": self.df.P3_LCV01D.to_numpy()[lo:i + 1].round(1).tolist(),
                      "valve_expected": self.exp.P3_LCV01D.to_numpy()[lo:i + 1].round(1).tolist(),
                      "pump": self.df.P3_LCP01D.to_numpy()[lo:i + 1].round(1).tolist(),
                      "pump_expected": self.exp.P3_LCP01D.to_numpy()[lo:i + 1].round(1).tolist(),
                      "score": (self.score[lo:i + 1] / self.model.threshold).round(3).tolist(),
                      "alarm": self.alarm[lo:i + 1].astype(int).tolist()}
            return {"episode": self.episode, "platform": self.platform, "episodes": self.episode_list(),
                    "i": i, "t": i - (self.episode["t_attack"] or 0), "clock": str(row.timestamp), "playing": self.playing,
                    "speed": self.speed, "alarm_on": self.alarm_on, "alarms": self.alarms, "brief": self.brief,
                    "brief_status": self.brief_status, "attack_now": int(row.attack),
                    "now": {"level": round(float(row.level_pct), 2), "level_raw": int(row.P3_LIT01), "level_expected": round(float(row.level_expected_pct), 2), "high": float(row.P3_LH01), "low": float(row.P3_LL01),
                            "flow": round(float(row.P3_FIT01), 1), "pressure": round(float(row.P3_PIT01), 1),
                            "valve": round(float(row.P3_LCV01D), 1), "valve_expected": round(float(self.exp.P3_LCV01D.iloc[i]), 1),
                            "pump": round(float(row.P3_LCP01D), 1), "pump_expected": round(float(self.exp.P3_LCP01D.iloc[i]), 1),
                            "demand": round(float(row.P4_HT_PS), 2), "score": round(float(self.score[i] / self.model.threshold), 3)},
                    "series": series}

    def episode_list(self):
        out = [{"id": k, "label": v[3], "kind": "real"} for k, v in DEMOS.items()]
        out += [{"id": "normal", "label": "Normal operation", "kind": "normal"}, {"id": "synthetic", "label": "Synthetic replay attack", "kind": "synthetic"}]
        out += [{"id": "file:" + p.name, "label": p.stem.replace("_", " "), "kind": "file"} for p in self.attack_files()]
        return out


REPLAY = None


PLANT_CSS = """<style id="plant-mode">
#back, #back2, .prog, #town-name, #town-sub { display: none !important; }
.townbar { display: none !important; }
.navright .chips { margin-left: 0 !important; margin-right: 6px; flex-wrap: nowrap !important; }
.topbar .wrap { flex-wrap: nowrap !important; }
.topbar .navright { flex-shrink: 0; }
@media (max-width: 1180px) { .topbar .wrap { flex-wrap: wrap !important; } }
@media (max-width: 900px) { .navright .chips { display: none; } }
</style>"""

PLANT_JS = """<script id="plant-mode-js">
(function () {
  // Single-plant console: the town view of the team's console, opened directly, with the region map removed.
  const $ = (s) => document.querySelector(s);
  const tab = document.querySelector("#tabs a[href='#overview']");
  if (tab) { const t = [...tab.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim()); if (t) t.textContent = "Overview"; }
  const chips = document.querySelector(".townbar .chips"), right = $(".navright");
  if (chips && right) right.insertBefore(chips, right.firstChild);
  const home = $("#nav-home");
  if (home) home.addEventListener("click", (e) => { e.preventDefault(); e.stopImmediatePropagation(); window.scrollTo({ top: 0, behavior: "smooth" }); }, true);
})();
</script>"""


def console_page(query):
    """The team's console, with the server's current results injected at request time.

    Default: the single-plant view (one water process, one controller check), opened on ?attack=<id> (default A104).
    ?view=region gives the team's multi-town overview unchanged."""
    data = json.loads(RESULTS_JSON.read_text())
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = CONSOLE.read_text().replace("/*__DATA__*/", payload, 1)
    head = f"<script>window.DATA_GENERATED={json.dumps(data.get('generated_utc', ''))};</script>"
    if query.get("view", [""])[0] != "region":
        ids = [t.get("id") for t in data.get("traces", [])]
        want = query.get("attack", ["A104"])[0].upper()
        k = ids.index(want) + 1 if want in ids else 1
        # The console opens whatever #town-N names, paused at the start of that replay; set it before its script runs.
        head += (f"<script>if(!location.hash)history.replaceState(null,'','#town-{k}');"
                 "if(!document.documentElement.dataset.theme)document.documentElement.dataset.theme='dark';</script>") + PLANT_CSS
        theme = f"<style id=\"plant-theme\">{PLANT_THEME.read_text()}</style>" if PLANT_THEME.is_file() else ""
        page = page.replace("</body>", theme + PLANT_JS + "</body>", 1)
    return page.replace("<head>", "<head>" + head, 1)


def recompute():
    """Retrain and rescore everything on this machine: notebook 02's logic via dashboard/build_data.py."""
    RECOMPUTE.update(state="running", error=None, started=time.time())
    try:
        subprocess.run([sys.executable, str(ROOT / "notebooks" / "run_controller_check.py")], check=True, cwd=ROOT, capture_output=True, text=True, timeout=1800)
        subprocess.run([sys.executable, str(ROOT / "dashboard" / "build_data.py")], check=True, cwd=ROOT, capture_output=True, text=True, timeout=600)
        RECOMPUTE.update(state="done")
    except subprocess.CalledProcessError as e:
        RECOMPUTE.update(state="error", error=(e.stderr or "")[-400:])
    except Exception as e:
        RECOMPUTE.update(state="error", error=str(e))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console for our own log lines
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/state":
            return self.send_json(REPLAY.state(q.get("since", [None])[0]))
        if u.path == "/api/recompute_status":
            return self.send_json(RECOMPUTE)
        if u.path in ("/console", "/console/"):
            body = console_page(q).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            return self.wfile.write(body)
        if u.path.startswith("/api/"):
            return self.send_json({"error": "unknown"}, 404)
        path = UI / ("index.html" if u.path in ("/", "") else u.path.lstrip("/"))
        if not path.is_file() or UI not in path.resolve().parents:
            return self.send_json({"error": "not found"}, 404)
        body = path.read_bytes()
        ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript", "css": "text/css", "json": "application/json"}.get(path.suffix[1:], "application/octet-stream")
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        try:
            if u.path == "/api/recompute":
                if RECOMPUTE["state"] != "running":
                    threading.Thread(target=recompute, daemon=True).start()
                return self.send_json({"ok": True, "state": RECOMPUTE["state"]})
            if u.path == "/api/load":
                ep = REPLAY.load_episode(q.get("episode", ["A214"])[0]); return self.send_json(ep)
            if u.path == "/api/play":
                with REPLAY.lock: REPLAY.playing = True; REPLAY.t_last = time.time()
            elif u.path == "/api/pause":
                with REPLAY.lock: REPLAY.playing = False
            elif u.path == "/api/speed":
                with REPLAY.lock: REPLAY.speed = float(q.get("x", ["1"])[0]); REPLAY.t_last = time.time()
            elif u.path == "/api/seek":
                with REPLAY.lock:
                    REPLAY.i = max(0, min(int(q.get("t", ["0"])[0]), REPLAY.episode["n"] - 1)); REPLAY.alarm_on = False; REPLAY.alarms = []
                    REPLAY.brief = None; REPLAY.brief_status = "none"; REPLAY.t_last = time.time()
            else:
                return self.send_json({"error": "unknown"}, 404)
            return self.send_json({"ok": True})
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)


if __name__ == "__main__":
    REPLAY = Replay()
    REPLAY.load_episode("A214")
    log(f"watch UI at http://127.0.0.1:{PORT}  (tunnel this port; it is not reachable from outside the server)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
