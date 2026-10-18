# Watercheck: regional monitoring and guided demo

Source of truth: `hai-water-controller-check`, commit `dd0a85bed9e2e3fdd6f501590b94fae5c1fe8bf6`. Model source, notebooks, and `dashboard/data.json` remain unchanged. No BATADAL or AquaSentinel code/data is used.

## Run

```sh
python3 dashboard/render.py
python3 -m http.server 8030 --bind 127.0.0.1 --directory dashboard
```

Open http://127.0.0.1:8030. The generated `dashboard/index.html` is standalone and can also be opened directly. No build dependencies, external fonts, CDN requests, or hosted inference are required. Continue using the branch's notebook and `dashboard/build_data.py` workflow to refresh model outputs.

Source files: `template.html` (structure), `app.css` (presentation), `core.js` (replay-state helpers), `app.js` (interactions), `render.py` (standalone bundle). Run `node dashboard/tests/replay.test.js` for timestamp and alarm-state checks.

## Product modes

### Server overview

Six fictional towns arranged around a shared IBM LinuxONE service. Regional replay advances each town's independent timeline; network styling, command scores, sparklines and the attention queue update with recorded outputs. Clicking a network node, town card or queue item opens that town at its current position. Filtering shows towns with unreviewed recorded alerts.

Town assignments: Cedar Creek/A214, Millbrook/A231, Pine Ridge/A104, Willow Falls/A212, Lakewood/A304, Brookfield/A419. Names, districts, layout, network paths and shared routing are illustrations. These are six presentations of HAI's one P3 water testbed, not six measured utilities. Moving indicators mean replay activity, not measured packets. CPU, memory, throughput and network telemetry are explicitly not connected. There is no multi-tenant backend.

### Monitoring

Four synchronized signals: upper tank level, valve command, pump command and normalized mismatch score. Last-90-second charts share a timestamp; signals have independent vertical scales. Pump/valve plots include model expectations. A focus selector expands one signal. Current readings, residuals, last-60-second ranges, event timeline, recorded sampling spacing and full-recording playback controls support investigation.

Raw tank and command values are preserved. The branch's level description says percent, but exported values exceed 100; engineering-unit conversion and safe limits are not established. Flow, pressure, demand and setpoints are model inputs but are not exported in the supplied dashboard traces. The UI does not invent them.

### Guided demo

Four clickable chapters: normal operation, command change, saved detection, explanation/investigation. Start guided demo plays from −30 seconds at 2× and pauses exactly at the saved detection time. A transient threshold excursion is not called a new persistent alarm. Chart focus makes the detection readable; full recording remains available. Clicking equipment switches command plots. Presentation mode hides navigation; Escape restores it.

The saved Granite explanation is shown only for A214. Other records use labeled deterministic summaries. The original A214 brief's safe-limit claim remains explicitly unverified. Brief display is an on-demand replay of saved text, not a claim that generation finishes at detection time.

### Incident library and evidence

All 11 incident records can be searched and filtered by local review state. Model evidence retains the measured results, uncertainty, training/calibration/test split, main XGBoost model versus comparison models, and LinuxONE execution provenance. Telum timing does not describe the main XGBoost model.

## Reviews and reports

Investigation checklists and notes are persisted in browser localStorage. Town investigations are keyed by town plus incident; general library reviews use incident-only keys. Saved reviews survive reloads; replay positions reset on reload. Local storage is neither shared nor authenticated nor tamper-evident. Reviewed does not mean resolved.

Download report generates a readable, printable HTML file containing the current investigation form, source and scope. The fallback opens the generated report if a browser blocks downloads. The report includes current draft form values even if they have not been saved. All notes are escaped as text.

No controls operate pumps, valves, accounts, network connections or remote servers.

## Datathon fit

Source: [Participant Guidebook](https://docs.google.com/document/d/1tt0ZhUyirXDtHIEum3JhG-ZIj6y-YpUc5e15mPT78w4/edit), read October 17, 2026.

| Rubric category (10 points each) | Demonstration support |
|---|---|
| Community value / theme | Shared monitoring concept for small utilities; operator-centered investigation |
| Novelty | Controller-command consistency approach from the team's branch |
| LinuxONE / AI technical design | XGBoost → persistent check → local Granite, plus separate Telum comparison |
| Execution / delivery | Regional view → town telemetry → guided incident → explanation and review |

Suggested presentation: show server overview, open Cedar Creek, run the guided A214 example, read its saved Granite explanation, then show Model evidence. Show the actual LinuxONE instance and notebook separately: this browser alone is not proof of a running server deployment. Keep the submission video at most three minutes, include the team name, SSF2026, repository and open-source resource links. Verify completion of both required AI/ML labs.

## Redesign decisions

| Earlier problem | New behavior | Purpose |
|---|---|---|
| Alert shown before replay began | Alarm appears only after saved detection timestamp | Tell the detection story accurately |
| Static diagram and long empty chart | Synchronized equipment highlights and focused detection window | Show where the command diverges |
| One generic system screen | Regional server view plus town-specific monitoring | Demonstrate shared-server concept |
| Evidence buried behind navigation | Inline explanation, investigation action and event timeline | Make the operator's next step clear |
| Dense source facts dominate overview | Separate evidence view with provenance and limits | Keep monitoring readable |

## Verification

Replay helper tests cover all 11 traces: sample selection never reads a future point, alarms do not precede saved detection, focus windows include the detection, historical alerts persist, and threshold excursions alone do not become alarms. Also verify desktop/mobile layouts, regional transitions, town drill-down position, investigation persistence/isolation, presentation mode and report generation in the browser after changes.
