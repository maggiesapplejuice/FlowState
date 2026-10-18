# Technical notes

## The model: a controller check

Does the controller command what it normally commands for these conditions?

**Inputs (9 readings):** upper tank level (`P3_LIT01`), high and low level setpoints (`P3_LH01`, `P3_LL01`), flow and pressure into the tank (`P3_FIT01`, `P3_PIT01`), and four hydro-turbine demand values (`P4_HT_FD`, `P4_HT_PO`, `P4_HT_PS`, `P4_LD`). Each is also used as it was 5, 15 and 30 seconds ago, along with each command 30 seconds ago.

**Predicted (2):** valve position command (`P3_LCV01D`) and pump speed command (`P3_LCP01D`).

**Model:** XGBoost regressors (300 trees, depth 6), learned from normal operation only.

**Score:** the larger gap between actual and expected command, divided by its normal variation, as a 10-second median.

**The alarm rule, fixed before testing:**
- Alarm level: the 99.9th percentile of the score on 127 hours of held-out normal data.
- An alarm needs 10 seconds above that level.
- An attack counts as caught if the alarm starts while it runs or within 60 seconds after it ends.

**Data split (HAI 22.04 and 23.05, water process P3):** learn normal behavior on 401 hours, set the alarm level on 127 hours, test once on 179 hours.

**Where the level should be:** the watch screen also shows a display reference for the tank level: the level 30 seconds ago plus the change the controller's normal commands would have produced (`LevelReference` in `src/water_model.py`, accurate to about 0.7 % of scale on normal data). The alarm is still the controller check.

### Results

| Version of the check | Caught | False alarms per day (95% range) | Alarms from attacks elsewhere |
|---|---|---|---|
| **Main:** XGBoost learned from HAI 22.04 + 23.05 | 11 / 11 | 1.25 (0.57–2.37) | 0 / 97 |
| XGBoost learned from HAI 22.04 only | 11 / 11 | 7.78 (5.87–10.1) | 3 / 97 |
| Neural network on the Telum II accelerator | 10 / 11 | 0.56 (0.15–1.42) | 0 / 97 |

The two comparison versions were run after the main one. False alarms are counted over 172.8 attack-free test hours. The median time to alarm is 20 seconds, including the 10-second hold.

## The demo scenarios

From [`demo/README.md`](../../demo/README.md) and [`demo/attacks/FORMAT.md`](../../demo/attacks/FORMAT.md):

| Scenario | What it is | Alarm |
|---|---|---|
| A214 (real) | Valve command changed for more than 10 minutes | 17 s after the change begins |
| A310 (real) | Pump command replaced with an earlier value, valve pushed and restored | 19 s |
| A104 (real) | Valve command pushed up or down, then restored | 22 s |
| A414 (real) | Pump command changed while the level reading is frozen on the operator screen | 29 s |
| Normal | A quiet 15-minute stretch | none |
| Synthetic | Pump command replaced by its value 60 s earlier, injected into normal data | 13 s |
| `sample_valve_hold.csv` (simulated file) | Valve command frozen, injected into normal data | 24 s, no false alarm before it |

The scoring is causal: every feature uses only the current and earlier seconds.

## LinuxONE evidence

**The machine:** IBM z17, machine type 9175, architecture s390x (big-endian), with the Telum II on-chip AI accelerator (`nnpa` in `/proc/cpuinfo`). Red Hat Enterprise Linux 9.8 host; the Jupyter container reports RHEL 10.2. 3 processors and 7.3 GB of memory, shared by the team. Hosted by the IBM LinuxONE Community Cloud at Marist College, Poughkeepsie NY.

**What ran on it:**
- Training, calibration and the one test of the controller check (XGBoost).
- The neural-net comparison on the Telum II accelerator: 645,600 rows scored in 0.08 s, against 0.22 s on the CPU.
- IBM Granite 3.3 2B Instruct, big-endian GGUF for s390x, through llama.cpp: an incident brief in 69 s.
- The replay server: scores each episode second by second with the saved check, writes the briefs, serves the watch screen and console, and re-runs notebook 02 on request (about 70 s).

**Commands that show it (run on the server):**

```sh
hostname                          # the team's server
uname -m                          # s390x
grep -m1 features /proc/cpuinfo   # includes nnpa (the Telum AI accelerator)
podman ps                         # the Jupyter Lab ML container
```

## Security and privacy

**In place today:**
- The model, the alarm rule and the language model all run on the LinuxONE server. No outside AI service is called.
- Granite only sees the alarm's facts, and it has no controls: it writes text.
- Jupyter and the replay server listen on the server's localhost. People reach them through an SSH tunnel with a key; apart from SSH, nothing on the server is reachable from the internet.
- The watch screen and console cannot operate pumps, valves, accounts or networks.

**Added in a real rollout:**
- A one-way tap at each utility: LinuxONE can see the controller but never command it.
- An encrypted link and a separate key for each utility, so one utility cannot send or read another's data.
- Sign-in for operators, with each response step recorded by name.

## Scale: many utilities, one server

Each utility would send one row of about a dozen numbers per second. On the Telum II accelerator, the neural-net version scored 645,600 rows in 0.08 seconds, about 8 million rows a second. That is the scoring step alone. Reading the data in, building features, the screens and the network were not measured end to end on LinuxONE, so we do not claim a utility count.

The language model is the slow part: about a minute per brief on 3 shared processors. It runs only when an alarm is raised, never on every reading.

The tap and the physics are brand-independent: for another controller brand only the protocol adapter changes, and for another country the threat feed and the registry of utilities.

## Built vs simulated

| Part | Status | Notes |
|---|---|---|
| Controller check, alarm rule, test results | Built | trained, calibrated and tested once on LinuxONE |
| Telum II neural-net comparison | Built | timed on LinuxONE; the main model is XGBoost |
| IBM Granite incident briefs | Built | written on LinuxONE by the local model |
| Replay server, watch screen and console | Built | score every second on LinuxONE; recompute re-runs notebook 02 there |
| Attack scenarios in the demo | Real and simulated | four real HAI attacks, a normal stretch, and synthetic attacks injected into normal HAI data |
| The feed itself | Replayed | recordings stand in for a live plant; the one-way tap is the deployment design |
| One-way taps, per-utility keys, operator sign-in, many utilities on one server | Deployment design | not part of the datathon build |

## Limits

- Only 11 attacks hit the water process, so the true catch rate could be as low as about 70% (the 95% lower bound for 11 of 11 is 71.5%).
- One lab testbed. HAI's water attacks change or replay valve and pump commands; other attack styles are untested.
- Network traffic is not part of the check.
- Synthetic attacks change only the attacked command column; the tank level is not re-simulated.

## Open-source software and data

**Model and server**
- [XGBoost](https://xgboost.ai), [pandas](https://pandas.pydata.org), [NumPy](https://numpy.org), [SciPy](https://scipy.org), [matplotlib](https://matplotlib.org)
- [PyTorch](https://pytorch.org) with IBM's NNPA plugin, built on [IBM zDNN](https://github.com/IBM/zDNN)
- [JupyterLab](https://jupyter.org) in the [LinuxONE Jupyter Lab ML image](https://github.com/linuxone-community-cloud/jupyter-lab-ml), run with [Podman](https://podman.io)
- [llama.cpp](https://github.com/ggml-org/llama.cpp) through [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)
- [IBM Granite 3.3 2B Instruct](https://huggingface.co/ibm-granite/granite-3.3-2b-instruct) (Apache 2.0), [big-endian GGUF for IBM Z](https://huggingface.co/taronaeo/Granite-3.3-2B-Instruct-BE-GGUF)

**Data and screens**
- [HAI security dataset](https://github.com/icsdataset/hai) 22.04 and 23.05 (CC BY-SA 4.0), water process P3
- [Outfit](https://fonts.google.com/specimen/Outfit) font
- [IBM LinuxONE Community Cloud](https://linuxone.cloud.marist.edu)

**Problem sources**
- [CISA advisory AA26-097A](https://www.cisa.gov/news-events/cybersecurity-advisories/aa26-097a)
- [Georgia water system attack (The Current, August 2026)](https://thecurrentga.org/2026/08/06/expert-says-georgia-water-system-attack-highlights-critical-security-deficiencies/)
