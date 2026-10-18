# Demo: WaterProject Watch on IBM LinuxONE

The live demo replays real attacks on the Siemens-controlled water process (HAI 22.04) as if they
were the one-way tap feed, scores every second with the controller check on IBM LinuxONE, and shows
the result on the operator's watch screen.

## Files

| File | What it does |
|---|---|
| `replay_server.py` | Runs on the server. Trains or loads the controller check, loads the HAI test files, scores an episode, releases one second at a time, writes the incident brief with the local language model, and serves the watch UI. |
| `ui/index.html` | The watch UI: alarm banner, plant schematic, current readings, incident panel, last-10-minutes charts, demo controls. The tank-level chart and tile also show **where the level should be**: the level 30 s ago plus the change the controller's normal commands would have produced (`LevelReference` in `src/water_model.py`). It is a display reference, accurate to about 0.7 % of scale on normal data; the alarm is still the controller check. |
| `bake.py` | Builds `ui/offline.html`, a copy of the UI with every episode's scores, alarms and briefs baked in. Needs no server. Use it as a fallback for recording and as the shareable version. |

The look follows the team's console design: Outfit type, a blue gradient banner that turns red on alarm, translucent rounded cards, pill buttons, with a dark variant that follows the system setting.

## Scenarios

| Scenario | What it is | Alarm |
|---|---|---|
| A214 (real) | Valve command changed for more than 10 minutes | 17 s after the change begins |
| A310 (real) | Pump command replaced with an earlier value, valve pushed and restored | 19 s |
| A104 (real) | Valve command pushed up or down, then restored | 22 s |
| A414 (real) | Pump command changed while the level reading is frozen on the operator screen | 29 s |
| Normal | A quiet 15-minute stretch | none |
| Synthetic | Pump command replaced by its value 60 s earlier, injected by us into normal data | 13 s |

Each episode shows 3 minutes before the attack. The scoring is causal: every feature uses only the
current and earlier seconds. The server scores a loaded episode in one pass on this machine (same
arithmetic as second-by-second scoring) and then plays it back at the chosen speed.

## Run it

On the server, from `~/WaterProject` (the container must be running):

```
podman exec -d -w /home/ibm-user/WaterProject notebook sh -c "python demo/replay_server.py > /tmp/replay.log 2>&1"
podman exec notebook tail -3 /tmp/replay.log      # wait for "watch UI at http://127.0.0.1:38891"
```

On your laptop, open a tunnel and leave it running, then open http://localhost:38891:

```
ssh -i <team-key>.pem -L 38891:localhost:38891 linux1@<server-ip>
```

The server listens only on the server's own localhost. Nothing is reachable from outside.

To stop it (the container has no `pkill`):

```
podman exec notebook sh -c 'for d in /proc/[0-9]*; do tr "\0" " " < $d/cmdline 2>/dev/null | grep -q replay_server && kill ${d#/proc/}; done'
```

## Build the offline copy

```
podman exec -w /home/ibm-user/WaterProject/demo notebook python bake.py
```

Writes `ui/offline.html` (about 5 minutes: it writes one brief per episode with the language model).
Open the file in any browser; it also serves at http://localhost:38891/offline.html while the server runs.

## Recording the video (3 minutes total for the whole submission)

Suggested shots, with the demo part kept to about 60 seconds:

1. **Problem (20 s):** the Clayton County incident; attackers changed controller settings; operators
   couldn't tell an attack from a breakdown.
2. **Proof of IBM Z (15 s):** a terminal on the server showing `hostname`, `uname -m` (`s390x`) and
   `grep -m1 features /proc/cpuinfo` (contains `nnpa`), then `podman ps` showing the container.
3. **Demo (60 s):** the watch UI on scenario A214. Click "Jump to 30 s before the attack" and Play at
   1×. Narrate: the main operator screen looks normal, the water level is in range. At +17 s the
   banner turns to ALARM: the valve command no longer matches what the controller normally does.
   Show the incident panel: facts, first steps, then the brief arriving (speed up this wait in the
   edit, or use the offline copy where it appears after 4 s).
4. **Evidence (30 s):** the dashboard page: 11 of 11 water-process attacks caught, 1.25 false alarms
   a day, 0 alarms during 97 attacks elsewhere; one testbed and 11 attacks, so a small test.
5. **Why LinuxONE (20 s):** plant data stays on a machine the utility controls; the check and the
   brief both run there; the neural-network version runs on the Telum accelerator.
6. **Scaling (15 s):** the tap and the physics are brand-independent; only the protocol adapter
   changes per controller brand; threat feed and registry change per country.

Record with QuickTime (File > New Screen Recording) or OBS. Use the live UI through the tunnel; if
the tunnel misbehaves, record `ui/offline.html` instead, which plays the same episodes.
