# WaterProject: IBM Z Datathon 2026

**Theme:** Real-Time AI for Critical Decisions

**Live dashboard:** https://maggiesapplejuice.github.io/WaterProject/ (the FlowState console as a static copy, results computed on IBM LinuxONE; the watch screen is at `/watch.html`). The live version with the recompute button runs on the team's LinuxONE server, see "The live demo" below.

## The problem

In July 2026, a Clayton County, Georgia pump station failed overnight and residents lost water pressure.
The utility later said a cyberattack may have caused it. The FBI and CISA reported attacks on water
utilities in several states in which attackers reached internet-exposed controllers and changed their
settings (CISA advisory AA26-097A). Small utilities usually cannot tell an attack from a breakdown quickly.

## What we built

A **controller check** for a Siemens-controlled water process, running on IBM LinuxONE. A model learns,
from normal operation only, what the controller normally commands to its valve and pump given the water
level, its setpoints, flow, pressure and demand over the last 30 seconds. When an attacker changes or
replays a command, the actual command stops matching the expected one and an alarm is raised. A local
language model then writes a plain-English incident brief.

## Results (HAI 22.04 and 23.05, rules fixed before testing, tested once)

| Measure | Result |
|---|---|
| Attacks on the water process caught | **11 of 11**, median 20 seconds to alarm |
| False alarms | **1.25 per day** (95% range 0.6 to 2.4) over 173 attack-free hours |
| Alarms during the 97 attacks on the boiler and turbine | 0 |

| Version of the check | Caught | False alarms per day | Alarms from attacks elsewhere |
|---|---|---|---|
| Main: learned from 22.04 + 23.05 | 11 of 11 | 1.25 | 0 |
| Learned from 22.04 only | 11 of 11 | 7.8 | 3 |
| Neural network on the Telum accelerator | 10 of 11 | 0.56 | 0 |

**Limits:** only 11 attacks hit the water process, so the true catch rate could be as low as about 70%;
one lab testbed; HAI's water attacks change or replay valve and pump commands, so other attack styles are
untested; network traffic is not included. The two comparison versions were run after the main one.

## The dataset

**HAI (HIL-based Augmented ICS) security dataset**: https://github.com/icsdataset/hai (CC BY-SA 4.0).
We use only its **water process (P3)**, a loop that pumps water into an upper tank, run by a
**Siemens S7-300 PLC**, with demand set by a hydro-turbine simulation (P4_HT). Reading descriptions come
from HAI's technical document.

| Used for | Files | Hours |
|---|---|---|
| Learn normal behavior | HAI 22.04 train1–5, HAI 23.05 train1–3 | 401 |
| Set the alarm level | HAI 22.04 train6, HAI 23.05 train4 | 127 |
| Test once | HAI 22.04 test1–4, HAI 23.05 test1–2 | 179 |

HAI 22.04 and 23.05 share the same testbed setup. The test files contain 110 attacks: 11 on the water
process, 97 on the boiler and turbine, and 2 whose documented target is contradictory.

**Problems found in the data and how we handled them**
- HAI 22.04's files carry one attack label for all processes, not one per process as the document says.
  Water-process attacks were identified by matching each labeled attack to HAI's attack tables.
- Two attack-table entries (A301, A305) contradict themselves and are left out of every count. A304 lists
  boiler target points for a water-process scenario code and is counted as a water attack.
- HAI 23.05's `label-test2.csv` records times only to the minute. Labels are aligned to data rows by
  position, with a check that every row falls in the same minute.

## Running it on IBM LinuxONE

Everything runs on our LinuxONE Community Cloud server (IBM z17, Telum II, RHEL 9.8) inside the official
Jupyter Lab ML container, which has pandas, XGBoost, PyTorch with the NNPA accelerator plugin and llama.cpp.

1. Tunnel from your laptop: `ssh -i <team-key>.pem -L 38888:localhost:38888 linux1@<server-ip>`, then open
   http://localhost:38888/lab (token: ask in the team chat). Jupyter listens only on the server's localhost.
2. On the server, from `~/WaterProject`: `bash scripts/download_data.sh` gets HAI 22.04, 23.05, HAI's
   technical document and the language model.
3. Run the notebooks in order:
   - `00_environment_check`: proof of IBM Z and the Telum accelerator
   - `01_hai_water_process`: the water process, its readings and its attacks
   - `02_controller_check`: train, calibrate, test once; saves results for the dashboard
   - `03_incident_brief`: the local language model writes a brief for a real detection
4. Dashboard: `podman exec -w /home/ibm-user/WaterProject notebook python dashboard/build_data.py`, then
   `python3 dashboard/render.py`, then serve it with
   `podman exec -d -w /home/ibm-user/WaterProject/dashboard notebook python -m http.server 38890 --bind 127.0.0.1`
   and tunnel port 38890 the same way.
5. Live demo (the watch screen, the console and the simulated attack files):
   `podman exec -d -w /home/ibm-user/WaterProject notebook sh -c "python demo/replay_server.py > /tmp/replay.log 2>&1"`,
   tunnel port 38891 the same way, then open http://localhost:38891 (watch screen) or
   http://localhost:38891/console (console). Details, the stop command and the video shot list are in `demo/README.md`.

pip cannot build numpy or pandas on the server itself (no s390x packages, no compiler), so run all
Python inside the container.

## The live demo

`demo/replay_server.py` replays a recording of the Siemens water process second by second, as if it were the
one-way tap feed, scores every second with the controller check on LinuxONE, and shows the result on two pages:

- **Watch screen** (`/`): the operator's supplemental screen. Alarm banner, plant schematic with both paths,
  current readings, the incident brief (facts and first steps at once, the Granite explanation about 40 s
  later), and the last ten minutes of charts. The scenario picker offers four real HAI attacks (A214, A310,
  A104, A414), a normal stretch, one synthetic replay attack, and every CSV in `demo/attacks/`.
- **Console** (`/console`): one plant, one check. Check performance, time to alarm for all 11 attacks, the
  plant figure with the live mismatch, device status and the command traces. The server's current results are
  injected on every request; the "Recompute on IBM LinuxONE" button re-runs notebook 02 and rebuilds them
  (about 70 s). `?attack=A214` opens another recorded attack.

**Simulated attack files.** `demo/attacks/FORMAT.md` gives the CSV format (HAI's 11 water-process tags, one row
per second, plus an `attack` label). `make_attack.py` cuts an attack-free stretch from HAI, injects one of six
attack kinds and verifies the result with the saved model. Two verified samples are included: a replayed pump
command (alarm 13 s after the change) and a held valve command (24 s), with no false alarms before either.
Only the attacked command column is changed; the tank level is not re-simulated, so the "where the level
should be" line stays close to the recorded level during these synthetic attacks. The alarm does not depend
on it.

The demo is a replay of recorded and simulated data, not a live plant. The one-way tap is the deployment
design; HAI records controller commands and readings, which approximate what the tap would see.

## Repository layout

| Path | Contents |
|---|---|
| `src/data_loading.py` | Loads HAI's water-process readings and labels; identifies water-process attacks |
| `src/water_model.py` | The controller check, the fixed alarm rule and the evaluation |
| `src/alerts.py`, `src/replay.py` | Shared alert format; replays recorded data as a live feed |
| `scripts/download_data.sh` | Downloads HAI 22.04 and 23.05, the document and the language model |
| `notebooks/` | The four notebooks above, plus `run_controller_check.py` (notebook 02 as a script, used by the recompute button) |
| `dashboard/` | Builds and renders the dashboard from the notebook results |
| `demo/replay_server.py` | The live demo server: replay, scoring, incident brief, watch screen, console, recompute endpoint |
| `demo/ui/` | The watch screen (`index.html`) and an offline copy with baked results (`offline.html`) |
| `demo/console/` | The console template, served with the current results injected, and its theme (`plant.css`) |
| `demo/attacks/` | Simulated attack files: `FORMAT.md`, `make_attack.py`, two verified samples |
| `demo/README.md` | How to run, stop and record the demo |

`data/` and `models/` are downloaded, not committed.

## Open-source libraries and models

pandas, NumPy, SciPy, XGBoost, PyTorch with torch-nnpa (IBM zDNN), matplotlib, Jupyter Lab, llama.cpp
(llama-cpp-python) and IBM Granite 3.3 2B Instruct, big-endian build for IBM Z
(https://huggingface.co/taronaeo/Granite-3.3-2B-Instruct-BE-GGUF, Apache 2.0). Container image:
`registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x` (https://github.com/linuxone-community-cloud/jupyter-lab-ml).

## Problem references

- CISA advisory AA26-097A: https://www.cisa.gov/news-events/cybersecurity-advisories/aa26-097a
- Georgia water system attack: https://thecurrentga.org/2026/08/06/expert-says-georgia-water-system-attack-highlights-critical-security-deficiencies/

## Notes

- All project code was written during the datathon window (Oct 17–18, 2026), with AI assistance (Claude).
- The project was reset on Oct 17 to use one dataset, HAI's Siemens water process. Earlier work on other
  datasets was removed.
