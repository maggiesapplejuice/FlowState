# Simulated attack files for the WaterProject replay server

A simulated attack is a plain CSV in this folder (`demo/attacks/` on the server): one row per second of the
Siemens-controlled water process, in the raw values HAI records, plus an `attack` label that says where the
injected attack really runs. The server scores every row with the controller check (the XGBoost model in
`data/processed/controller_check.pkl`) exactly as it scores the real HAI episodes, then plays the file back
second by second on the watch UI.

Two ready-made files are here, both built from a real, attack-free stretch of HAI 22.04 `test1.csv`:

| File | Source stretch | Attack (rows 240-419, 3 min) | Verified result |
|---|---|---|---|
| `sample_pump_replay.csv` | 2021-07-10 12:47:00 - 13:01:59 (900 rows) | pump command `P3_LCP01D` replaced by its own value 60 s earlier (HAI AP35, like A212 / A310 / A419) | alarm 13 s after the attack begins, 0 false alarms before it, peak 8.6x the alarm threshold |
| `sample_valve_hold.csv` | 2021-07-10 20:00:00 - 20:14:59 (900 rows) | valve command `P3_LCV01D` frozen at 16032 counts (HAI AP39 style, like A214) | alarm 24 s after the attack begins, 0 false alarms before it, peak 28.3x the alarm threshold |

"Verified" means: scored on the LinuxONE server with the saved model, saved threshold (6.598) and the 10 s
hold rule, via `make_attack.py --verify` (see the end of this file).

## Columns (in this order)

| Column | Meaning | Unit / range in HAI | Used by |
|---|---|---|---|
| `timestamp` | wall-clock time of the sample, `YYYY-MM-DD HH:MM:SS`, one row per second, no gaps | - | model (gap detection), UI clock |
| `P3_LIT01` | upper-tank water level reading | raw Siemens counts, 27648 = 100 % (HAI test1 runs 6038-19878, i.e. 22-72 %) | model input, UI (shown as %) |
| `P3_LH01` | high water-level setpoint | percent (70 in all of HAI 22.04) | model input, UI |
| `P3_LL01` | low water-level setpoint | percent (25 in all of HAI 22.04) | model input, UI |
| `P3_LCV01D` | valve position command from the controller | raw counts, 0-27648 scale (test1: -112..17792) | **model target** (checked), UI |
| `P3_LCP01D` | pump speed command from the controller | raw counts, 0-27648 scale (test1: 0..13824) | **model target** (checked), UI |
| `P3_FIT01` | flow into the upper tank | raw counts (test1: 5..5477) | model input, UI |
| `P3_PIT01` | pressure into the upper tank | raw counts (test1: 1..4169) | model input, UI |
| `P4_HT_FD` | hydro-turbine frequency deviation | Hz-ish float (about -0.03..0.03) | model input |
| `P4_HT_PO` | hydro-turbine output power | MW (0..84) | model input |
| `P4_HT_PS` | hydro-turbine scheduled power (the demand) | MW (0.716 constant in test1) | model input, level reference, UI "demand" |
| `P4_LD` | total electrical load demand | MW (235..496) | model input, level reference |
| `attack` | ground-truth label: 1 while the injected attack is running, else 0 | 0/1 integer, no blanks | UI marker and "seconds since the change"; **not** seen by the model |

All 13 columns are required. Integer columns stay integers (as HAI records them); the P4 columns are floats.
The names are HAI's own tag names, so any HAI 22.04 / 23.05 row can be copied in unchanged. `attack` is
the only non-HAI column; in HAI 22.04 the equivalent is `Attack`.

What the model actually uses: the 9 inputs (`P3_LIT01`, `P3_LH01`, `P3_LL01`, `P4_HT_FD`, `P4_HT_PO`,
`P4_HT_PS`, `P4_LD`, `P3_FIT01`, `P3_PIT01`) at the current second and 5, 15 and 30 s earlier, plus each
command 30 s earlier, to predict the two commands (`P3_LCV01D`, `P3_LCP01D`). The alarm is on the gap
between the actual and the expected command. Display-only: `attack`, and the `P3_LH01` / `P3_LL01` /
`P4_HT_PS` tiles (those three are also model inputs). `P4_LD` and `P4_HT_FD` / `P4_HT_PO` are model inputs
that the UI does not show.

## Timing rules

* **Sampling**: exactly 1 row per second, consecutive timestamps. A jump of more than 5 s starts a new
  "recording segment" in the model (lag features reset), so do not splice stretches together.
* **Warm-up**: the server scores the whole file but hides the first **60 rows** (`WARMUP = 60` in
  `replay_server.py`), the same as for the real episodes. The lag features need 30 s of history, and in
  the first ~30 rows they are back-filled, which can produce a spurious alarm there (the pump-replay sample
  has 5 such rows inside its warm-up). Those rows are never shown, so this is harmless **as long as the
  loader drops the first 60 rows after scoring**, like `Replay.load_episode` does.
* **Minimum rows before the attack**: 90 (60 warm-up + 30 so the first shown rows already have real lag
  history). Recommended: **240**, which gives the standard 3-minute lead-in on screen after the warm-up,
  identical to the real episodes. For `pump_replay` the lead-in must also be at least `--shift` rows.
* **Attack length**: anything; 2-3 minutes shows well. The alarm needs 10 consecutive seconds over the
  threshold after a 10 s running median, so the earliest possible catch is about 13 s after the change.
* **Tail**: a few minutes of normal rows after the attack, so the alarm can be seen clearing.
* Keep files small: 900 rows (15 min) is about 80 KB.

## What an attack looks like in the file

Only the attacked command column (and, for the level-freeze kind, `P3_LIT01`) is changed; the sensor
columns stay exactly as recorded. That mirrors what the one-way tap sees when an attacker rewrites the
controller's output, and it is how the server's built-in "synthetic" episode is made. Limitation to be
honest about: the tank level in the file does **not** respond to the injected command, because the
physics was not re-simulated; the alarm does not depend on that (it compares the command with what the
controller should be commanding), but the "where the level should be" reference line will stay close to
the real level during these synthetic attacks.

## Three example rows (from `sample_pump_replay.csv`, around the attack start at row 240)

```
timestamp,P3_LIT01,P3_LH01,P3_LL01,P3_LCV01D,P3_LCP01D,P3_FIT01,P3_PIT01,P4_HT_FD,P4_HT_PO,P4_HT_PS,P4_LD,attack
2021-07-10 12:50:59,9032,70,25,5520,7944,7,1379,-0.0008,23.22046,0.716041982,383.31885,0
2021-07-10 12:51:00,9127,70,25,6224,0,7,1134,-7e-05,26.16827,0.716041982,387.02618,1
2021-07-10 12:51:01,9153,70,25,6880,0,7,968,0.00036,29.58624,0.716041982,391.36646,1
```

At 12:51:00 the pump command drops from 7944 to 0 (the value it had 60 s earlier, when the pump was off)
while the level is 33 % and rising: the controller should still be pumping. The check flags it 13 s later.

## Making more files

Everything runs inside the `notebook` container, from `~/WaterProject` on the server:

```
podman exec -w /home/ibm-user/WaterProject notebook python demo/attacks/make_attack.py \
    --source test1 --start "2021-07-10 12:47:00" --kind pump_replay \
    --out demo/attacks/sample_pump_replay.csv --verify

podman exec -w /home/ibm-user/WaterProject notebook python demo/attacks/make_attack.py \
    --source test1 --start "2021-07-10 20:00:00" --kind valve_hold \
    --out demo/attacks/sample_valve_hold.csv --verify
```

Options: `--source` (HAI file: test1..test4, train1..train6), `--start` (first row of the output),
`--lead` (rows before the attack, default 240), `--duration` (default 180), `--tail` (default 480),
`--kind` (`pump_replay`, `pump_offset`, `pump_hold`, `valve_hold`, `valve_offset`, `pump_freeze_level`),
`--shift` (pump_replay, default 60 s), `--delta` (offset kinds, default +4000 counts), `--value` (hold kinds).
`--verify` prints seconds-to-alarm, false alarms before the attack and peak mismatch, and ends with a
`RESULT:` line; a pump replay that starts while the pump is steady can take a minute or more to alarm,
so if `--verify` reports a slow catch, move `--start` by a minute or two and re-run.
`--scan --source test1` lists the attack-free 15-minute stretches of a file with the model's peak
score in each, to pick a quiet stretch to build on. The script refuses stretches that contain a real HAI
attack and stretches with timestamp gaps.

Dataset: HAI (HIL-based Augmented ICS) security dataset, https://github.com/icsdataset/hai, CC BY-SA 4.0.
