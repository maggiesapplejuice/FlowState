# FlowState: architecture and supporting documents

Supporting documents for our IBM Z Datathon 2026 submission (theme: Real-Time AI for Critical Decisions).

| Document | What it covers |
|---|---|
| [Architecture](ARCHITECTURE.md) | How a utility, the IBM LinuxONE server and people connect, where every piece of data goes, and what actually ran on LinuxONE |
| [Solution flowchart](SOLUTION_FLOWCHART.md) | What happens to each reading, every second |
| [Technical notes](TECHNICAL_NOTES.md) | The model, the demo scenarios, LinuxONE evidence, security, scale, what is built vs simulated, limits, open-source links |

Diagram files, in [`images/`](images/) (PNG for slides and uploads, SVG for zooming):

| Diagram | PNG | SVG |
|---|---|---|
| Architecture | [architecture-diagram.png](images/architecture-diagram.png) | [architecture-diagram.svg](images/architecture-diagram.svg) |
| What ran on LinuxONE | [as-built-pipeline.png](images/as-built-pipeline.png) | [as-built-pipeline.svg](images/as-built-pipeline.svg) |
| Solution flowchart | [solution-flowchart.png](images/solution-flowchart.png) | [solution-flowchart.svg](images/solution-flowchart.svg) |

![Architecture diagram](images/architecture-diagram.png)

## The idea in one paragraph

One AI service on IBM LinuxONE checks whether a water utility's controller is doing what it normally does. A model learns, from normal operation only, what the Siemens controller commands to its valve and pump for the current water level, setpoints, flow, pressure and demand. When an attacker changes or replays a command, the actual command stops matching the expected one. The check raises an alarm within seconds, and IBM Granite, running on the same server, writes a plain-English brief with first steps.

## What data goes where, in plain words

1. **At the utility**, the Siemens controller already measures the tank's level, flow and pressure and decides the pump speed and valve position: 11 readings, every second.
2. **A one-way tap** copies those 11 readings and sends them over an encrypted link to the IBM LinuxONE server. It cannot send anything back, so the server can never operate the utility's pumps or valves. *(The deployment design. For the datathon, recordings replay this feed.)*
3. **On LinuxONE, the controller check** predicts what the controller *should* command and scores the gap to what it *did* command. *(Built.)*
4. **The alarm rule** raises an alarm only when the gap stays above the alarm level for 10 seconds, so brief blips don't alarm. *(Built.)*
5. **IBM Granite 3.3 2B**, on the same server, turns the alarm's facts into a short brief. The facts and first steps show at once; Granite's explanation follows. *(Built.)*
6. **The watch screen** sits beside the operator's usual screen: alarm banner, current readings, brief and first steps. **The console** shows the check's performance and can recompute the results on LinuxONE. *(Built.)*

No outside AI service is used: the data and the AI stay on the LinuxONE server.

## Results at a glance

HAI 22.04 and 23.05 water process, rule fixed before testing, tested once on 179 hours:

| Measure | Result |
|---|---|
| Attacks on the water process caught | **11 of 11**, median 20 seconds to alarm |
| False alarms | **1.25 per day** (95% range 0.57 to 2.37) over 172.8 attack-free hours |
| Alarms during the 97 attacks on other processes | **0** |

## Links

- Console (static copy, results computed on IBM LinuxONE): <https://maggiesapplejuice.github.io/WaterProject/>
- Watch screen (static copy): <https://maggiesapplejuice.github.io/WaterProject/watch.html>
- Live demo on LinuxONE: see [`demo/README.md`](../../demo/README.md)
- Dataset: [HAI security dataset](https://github.com/icsdataset/hai) (CC BY-SA 4.0)
