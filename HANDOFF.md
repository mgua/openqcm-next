# HANDOFF — Developer notes (openQCM NEXT)

> Technical starting point to continue development of the software and of the
> `impedance-analysis` branch. Working language: Italian in chat, English in the repo.
> Last updated: 2026-09-01.
>
> Starting a new session: paste [`docs/SESSION_PROMPT.md`](docs/SESSION_PROMPT.md)
> as the first message. It is a shortcut into this file, not a replacement for it.

---

## 1. Software architecture

**Multiprocessing** pipeline that keeps acquisition separate from the UI:

```
Serial/Multiscan/Calibration process  →  Worker (queues → ring buffers)  →  MainWindow (Qt, 50 ms timer)
        (child process)                                                        PyQtGraph + CSV
```

Package `software/openQCM/`:
- `core/`: `constants.py` (config), `worker.py` (multiprocessing, ring buffers), `ringBuffer.py`,
  **`resonance.py`** (peak detection, dissipation band, SG filter + spline — see below),
  **`averaging.py`** (robust averaging of the ring buffers — see below)
- `processors/`: `Serial.py` (SerialProcess), `Multiscan.py` (multi-overtone; conductance on the impedance branch), `Calibration.py` (peak detection), `Parser.py`
- `ui/`: `mainWindow.py` (controller, ~4000 lines), `mainWindow_ui.py` (**programmatic UI builder**,
  GUI redesign R1; the old generated `mainWindow_new_ui.py` stays as reference only), `theme.py`,
  `popUp.py`, **`rawDataView.py`** (live Raw Data View), **`peakDataView.py`** (last Peak
  Detection), **`dataLogView.py`** (File > Open Log), **`plotMenu.py`** (the one plot right-click
  menu), **`widgets.py`** (combo/spin boxes that paint their own chevron)
- `common/`: `fileStorage.py`, `logger.py`, `architecture.py`, `switcher.py`,
  **`sweepDump.py`** (development-only raw sweep dump, off by default)
- Entry point: `run.py` → `openQCM.app.OPENQCM().run()`

### `core/logAnalysis.py` — the two-window comparison, and the four numbers it fixed

The statistics behind Tools > Log Data — a starting stretch of a run against a final one — used to
live inside `data_view/main.py` as ~350 lines of per-overtone copy-paste. That package is **gone**
(retired 2026-08-27); the analysis is here, without Qt, and Datalog View's panel reads it rather
than deriving its own.

⚠️ **Four defects went out with the move, and the numbers the old window printed for them were
wrong, not differently rounded.** Measured on a probe with a quiet 7th overtone and a noisy 9th:

| | old | correct |
|---|---|---|
| 9th overtone Hadamard, final window | 0.03 | 1.30 |

- the 9th overtone read `f_3_hadamard` — the **7th's** — divided by 9, in both blocks;
- the final window was normalised by the initial window's length, `6*(j-i)` for `6*(l-k)`;
- the Hadamard loop read `x[i-1]`, so a window starting at sample 0 folded the **last** sample of
  the run into its first term through negative indexing (129099 against 0 on a probe with one large
  value at the end);
- a window reaching past the end of the run lost its last sample, because the index search was a
  `for`/`break` that fell out holding the last index rather than one past it. Not an edge case: it
  is what happens whenever a final window is asked to run to the end.

Everything else is the legacy behaviour on purpose — window selection is identical wherever the old
rule was defined, and the fundamental's Hadamard over the initial window agrees to 1e-12.

⚠️ **Three of the four reported quantities are independent of the caller's reference**: `shift`
(a difference of means), `std` and `hadamard` all survive a constant subtracted from the series.
Only the per-window `mean` moves with it. That is what lets Datalog View keep a draggable zero
while the analysis is on screen, and it is gated — moving the reference leaves the rendered report
character-for-character identical. Do not add a reference-dependent number to `format_report`
without revisiting that.

⚠️ The harness comparing this module against the legacy implementation is pinned to **`600a33b`**,
the last commit where `data_view/main.py` exists. It cannot run against HEAD.

### ⚠️ `core/resonance.py` is the only place the band may be computed

`savitzky_golay` + `parameters_finder` used to exist in **three** copies (`Multiscan.py`,
`Serial.py`, `sweep_data/plot_sweep_spline.py`). That is how openQCM Q-1 ended up drawing a band
that was not the measured one, and in NEXT the third copy **had already drifted**: it returned the
index of the last sample above the threshold instead of interpolating, overstating the band by up
to 2%. Everything — both acquisition processes and every viewer — now calls this module.

**If you need the band, import it. Do not re-derive it.** A viewer that quietly disagrees with the
instrument is worse than one that does not draw the band at all.

Things about the chain that surprise people, all commented in the module:
- The threshold is a **drop in dB below the maximum** (`Constants.THRESHOLD_DB = 0.3`), *not* a
  fraction of it as in Q-1. The sweep is baseline-corrected and crosses zero, so a proportional
  threshold would track the baseline rather than the peak.
- It applies to `spline(SG(mag − polynomial baseline))`, never to the raw amplitude.
- The two edges are **linearly interpolated** between adjacent spline points, so they are
  frequencies in Hz despite the historical `i_leading` / `i_trailing` names.
- `Qfac` is an **alias for the bandwidth**, and the logged dissipation is the **bandwidth in MHz,
  not `1/Q`**. Check this before you put either number on screen.
- The fundamental and overtone branches have been numerically identical since VER 0.1.4, hence the
  single code path.
- The polynomial order of the full-span baseline is `Constants.BASELINE_POLY_ORDER` (8). It was a bare
  literal in **seven** call sites, which is how a viewer ends up correcting a baseline the instrument
  never used. Anything that reproduces the measurement reads it from there.

## 2. Branches

- **`main`**: development line. Reconstructed history (`v0.1.5` → `v0.1.6-dev` → `v0.1.6-dev-073`)
  plus all current development (entry point, serial connection, dependencies, README, fixes).
- **`impedance-analysis`** (tag `v0.1.6G-test`): conductance-based impedance analysis. It is *ahead*
  of `main` on that feature and aligned with `main` on everything else.

### ⚠️ Moving work between `main` and `impedance-analysis` (updated 2026-07-28)

`main` **does not carry the impedance analysis.** It was merged in twice (PRs #1 and #2) and then
reverted by `1b3fe81`, which restored `main` byte-for-byte to `52a42a9`. A merge
`impedance-analysis → main` is planned for the future but is Marco's decision, not a routine step.

That revert leaves a trap in **both** directions, because the merge base between the two branches is
`c83a820` — a commit that *had* the impedance code. Git therefore reads `main` as "deleted the
impedance code" and propagates that deletion. So:

- **`main` → branch: cherry-pick, never `git merge main`.**

      git fetch origin
      git --no-pager log --oneline 1b3fe81..origin/main   # what is new on main
      git cherry-pick 1b3fe81..origin/main

  A plain `git merge main` conflicts on nine files and, where there is no textual conflict,
  **silently** deletes `sweep_data/plot_conductance.py` from the branch, restores the three dead
  Qt-Designer UI files and re-tracks `Calibration_5MHz.txt`. Verified with
  `git merge-tree --write-tree`.

- **branch → `main`: revert the revert FIRST**, then merge:

      git checkout main && git revert --no-edit 1b3fe81

  Resolving a direct merge by hand instead keeps `main`'s deletions wherever there is no textual
  conflict, leaving a hybrid that compiles and measures wrong.

- **Keep commits on `main` small and single-topic**: cherry-pick operates per commit, so one commit
  mixing three unrelated changes forces all three conflicts to be resolved at once.
  `processors/Multiscan.py` is where the two lines of work actually meet.

Full reasoning, measurements and the file-by-file list: `HANDOFF.md` on the `impedance-analysis`
branch, section "Working with `main`".

⚠️ Note the instruction that stood here before 2026-07-28 — "to align the impedance branch, run
`git merge main` from it" — is now **wrong**: it is precisely the operation that silently deletes the
branch's work.

## 3. Current state on `main`

### Serial connection (refactored) — how it works now
The serial connection is a **dedicated feature** (explicit connect, independent from the operation
mode). Methods in `software/openQCM/ui/mainWindow.py`:
- `_setup_serial_connection_ui()` — creates the **Connect/Disconnect** and **Refresh** buttons at
  runtime (in the Start/Stop row) plus the connection state.
- `_toggle_serial_connection()` — Connect: per-port lock file (`_acquire_port_lock`, `fcntl` on Unix)
  + open a **persistent exclusive** handle `_serial_lock` (`_open_serial_lock`), then firmware check.
  Disconnect: close `_serial_lock` + release the lock file.
- `_serial_write()` / `_serial_query()` — the GUI queries (set temperature, TEC on/off, PID, firmware)
  write/read on `_serial_lock` instead of opening the port ad-hoc.
- **Hand-off**: `start()` closes `_serial_lock` (gives the port to the acquisition process);
  `stop()` calls `_reacquire_serial_lock()` before the shutdown queries.
- `_refresh_ports()` — rescans devices; **Start** is enabled only once connected (`_enable_ui`).

### Raw Data View, and the two things it must never become

`ui/rawDataView.py` (**Tools → Raw Data View**) shows the live amplitude and phase sweep per
overtone, with the peak, the dissipation band and the threshold drawn on the fit. Ported from Q-1
v3.0 and extended to NEXT's five overtones as tabs. Two design rules hold it up, and both are easy
to break by accident:

1. **It pulls; nothing pushes into it.** The dialog owns a 300 ms timer and asks the acquisition
   object for its buffers. Do not add a `set_data()` or a signal from the worker: the pull model is
   the only reason a closed dialog costs *nothing* instead of merely being idle, and the reason the
   acquisition never waits on the GUI.
2. **It shows what is being measured** (`012b843`). Multiscan: one tab per overtone. Single
   frequency: the one overtone being interrogated, tab bar hidden — `SerialProcess` ships its sweep
   into the slot of that overtone exactly as multiscan fills five, and the view asks the host
   `current_single_overtone()` (0 = fundamental; cBox_Speed lists the overtones highest first, the
   F1..F9 mapping). Before that the view read the `*_multi` buffers, which only multiscan filled,
   and a single run showed "Waiting for data" for ever.
3. **It reads memory only, never a file.** The sweep dump is a separate development tool
   (`common/sweepDump.py`, below) and shares no state and no code with it. Verified by deleting the
   dump module and every reference to it and checking the dialog draws byte-identical arrays.

⚠️ **Re-resolve the worker on every tick** — `getattr(host, 'worker', None)`. START/STOP replace
that object; a reference cached at construction leaves the view frozen with nothing to say so. This
is the classic porting bug and it is silent.

The analysis runs in the GUI thread at **full sample resolution** so the band drawn is the band
logged; only what goes into the plot is decimated (`Constants.FREQ_STEP_PLOT`). Never clamp
`spline_points` or decimate the fit to save time — that draws a band the instrument did not
measure, which is exactly the failure this module exists to prevent. Only the visible tab is
analysed, so the cost is one spline per tick. Each tab frames the resonance once on its first fit
and then leaves the axes alone: at full scale a 62 Hz band inside an 18 kHz span is invisible, but
re-framing every tick would be unusable.

### The other views: Peak Data View, Datalog View, Tec Current

Four auxiliary windows now, and the difference between them is the thing to keep straight.

| window | menu | reads | live? |
|---|---|---|---|
| Raw Data View | Tools | the acquisition buffers, in memory | yes, 300 ms pull |
| Peak Data View | Tools | `Calibration_*MHz.txt` + `PeakFrequencies.txt` | no, snapshot on open |
| Datalog View | File > Open Log… | a `logged_data/*.csv` the user picks | no, snapshot on open |
| Tec Current | Tools | the worker's TEC-current buffer, handed over by `_update_plot` | yes, pushed every tick |

**Following a theme change while open.** The application QSS reaches a child dialog's frame, never
its pyqtgraph canvas, so every view has an `apply_theme()` that repaints what it took from
`theme.PLOT`, and `_apply_theme` walks the open views (the datalog list included) and calls it.
Tec Current `b42e9a9`, Raw Data View `3116187`, Peak Data View and Datalog View `ed71499`. Peak Data
View is the one that *redraws*: its corrected curve, raw dots and labels are palette-coloured, so it
keeps the arguments of its last `_draw()` and draws them again. A new view must ship with
`apply_theme()` or it will be the one that stays dark on the light theme.

Tec Current is the one that is *pushed*: the main window calls its
`update_plot()` from `_update_plot()`, as the old `SecondWindow` was, so the acquisition never waits
on it. Otherwise it follows the other three — `theme.PLOT` colours, the shared `PlotMenu`, one
instance, closed with the main window (and on STOP, since it shows a running acquisition).

⚠️ **pyqtgraph 0.11 downsampling, two traps** (`9169e64`). `setDownsampling(mode="peak")` only
chooses the method: `auto=True` (or a factor) is what switches it on, and Peak Data View drew every
one of its 100001 samples per curve on every pan for months because of that (measured: 1170 ms per
pan). And it works only while no bare `ScatterPlotItem` is in the plot: `updateDownsampling()` calls
`setDownsampling()` on every item, a ScatterPlotItem has none, the loop dies at the first one. Points
go in as `PlotDataItem`s in symbol mode (`pen=None, symbol=...`), same look, downsampled and clipped
with the curves. A third trap (`4abe377`): auto mode keeps `autoDownsampleFactor` = 5 samples per pixel
*before* 'peak' takes min and max, i.e. ~8 drawn points per pixel per curve; the view sets it to 1 on
every item (`_budget()`), one min and one max per pixel, nothing visible lost. After the three:
full span 14 ms render / 44 ms pan, zoomed 2 / 26 ms (was 352 / 1170). **Check it on a screen, not by
reading**: `OPENQCM_PLOT_DEBUG=1 python3 run.py` prints, on every change of view, the samples given
and drawn per curve and the paint time. Raw Data View is unaffected: its sweeps are 18001 points and
it has no downsampling to break.

**Reading files is right in the last two and wrong in the first.** Peak Detection runs once and writes
its two files; a datalog is a finished run. There is nothing in memory to read in either case, and
those files *are* the record. Raw Data View is the opposite: the sweeps are in memory, and reading the
dump instead is what coupled Q-1's viewer to a debugging tool.

⚠️ **Peak Data View reconstructs two things**, because neither is stored: the baseline (from
`BASELINE_POLY_ORDER`, on the same arrays the detector used) and the phase peak. The second is not an
oversight to fix — `PeakFrequencies.txt` holds the amplitude peak **twice**
(`np.column_stack([f, f])` in `Calibration.py`), so the phase peak has to be re-derived. It is drawn
beside the amplitude peak on purpose: their disagreement is the diagnostic.

⚠️ **Datalog View has a format trap.** `FileStorage.CSVsave_Multi` always writes a **14-column
header**, but the data rows **skip** every overtone whose frequency or dissipation is zero. Measured
across 33 logs: a 10 MHz sensor writes **10-column** rows under that header. Reading columns by header
name invents two overtones on every such run. Pairs are therefore taken positionally, the row width
decides how many there are, and the harmonic order is derived from the frequencies because the file
does not record which overtones were selected.

Frequency and dissipation are shown as the shift from a **movable reference cursor** (the mean of
`REFERENCE_SAMPLES` = 5 samples). Absolute values are unreadable: five overtones on one axis span
5 to 45 MHz against a signal of a few hundred Hz.

Each control row carries **two** colour swatches, one beside the frequency value and one beside the
dissipation value. It carried one until 2026-08-27, when the two panels stopped sharing a colour;
a single swatch would now claim a curve it does not match.

**`File > Open Log…` is the only way in.** Until 2026-08-27 `Tools > Log Data` raised a second,
matplotlib viewer of the same files (`data_view/`, now removed); the entry was kept for a few
commits, then dropped as well — it opened this same window, so it was two menu items for one thing.
The old viewer's two-window comparison came along, as the panel below.

The **Two-window analysis** pane is hidden until the button in the Reference card is pressed, and
the two shaded bands on the plots appear and disappear with it — bands with no report say nothing,
and a report whose extent the reader cannot see is worse than none. Each band is mirrored on both
shift panels and kept in step by the same re-entry guard as the reference cursors, because the
panels are x-linked and a band on one of them would leave the other reader guessing. The numbers
come from `core/logAnalysis.py`; see §1 for what they mean and what they deliberately ignore.

### PID Control, and why `config.txt` is the memory

**Tools → PID Control** (`ui/pidControlDialog.py`) re-exposes what the sidebar redesign hid: the
TEC controller's cycling time and P/I/D shares, the two presets `Constants` has always carried
(factory 50/1000/200/100, openQCM 50/500/50/300) plus Custom, and Set PID. The old sidebar
widgets (`tab_2`) and the three functions only they used are gone (`51034e8`): the window is the only
PID editor there is.

Three facts decide everything about this window, all three **measured at the bench on 2026-09-08**:

1. **The MTD415T is volatile.** A power cycle returns it to the factory values whatever anyone
   sent before; no firmware version writes it anything at start-up (`P_SET = "P1000"` is declared
   in every sketch and used in none). Only the PC ever sets the PID.
2. **Who holds the port decides the path.** In Standby the GUI holds it; during a measurement the
   acquisition process does, and the GUI cannot write.
3. **`_Temperature_PID_control` in `Multiscan.py`/`Serial.py` re-reads `config.txt` at every sweep
   and sends what changed**, starting from a memory of zero — so at the first sweep of every START
   it sends all four rows of the file, whatever the controller had. That is the mechanism that
   used to put Default #1 back at every START, and it used to be silent.

So the file is the memory, and the dialog never touches the serial port: it emits
`apply_requested(C, P, I, D)` and `mainWindow._apply_pid` chooses:

| state | what happens | the observable |
|---|---|---|
| Standby | rows 1–4 of `config.txt` written, C/P/I/D sent on the persistent handle, then `C? P? I? D?` asked | the four values **the controller reports**, in the status line and the log: "all four match", "MISMATCH on P", "did not answer" |
| acquisition running | rows 1–4 written, nothing sent by the GUI | the process reports `PID sent to the controller: P600` for each parameter it actually forwards — once, at the next sweep, and only for what changed |
| not connected | Set PID is disabled | — |

⚠️ **A print() in the acquisition process never reaches the System Log tab** — `LogStream` mirrors
the GUI process only. Text for the operator goes through `ParserProcess.add_message()`; the worker
drains that queue with the data queues (`consume_queue_message`, also once in `Worker.stop()`) and
prints it in the GUI process, which is what puts it in the console, the tab and the log file at
once. The four PID lines are the first users.

**Read PID** (`_read_pid`) is the other direction, on demand: `C? P? I? D?`, the answers go into
the spin boxes and the status line says "same as config.txt" or "config.txt has …". It shows, it
does not save — the file changes only on Set PID, so *read, then set* is how the controller's values
become the file's. Enabled whenever a board is connected; **who answers depends on who holds the
port**. Standby: the GUI asks. Measuring: the GUI raises `ParserProcess.pid_read_request` (an Event
on the parser both processes hold), the process takes it in the quiet gap where it already reads
the TEC current with `A?` — the only moment the board is listening — asks through the shared
`common/pidQuery.read_pid()` and answers through `add_pid()`; the worker drains that queue with the
others and `_update_plot` hands the answer to `_show_pid_reported`, tagged "read by the acquisition
between sweeps". About 0.8 s once, on request only; the answer arrives within one overtone sweep.

Only rows 1–4 are written: the old PID Set also raised the flag that re-sends the temperature
set-point, for nothing. Set PID follows the connection, not the TEC switch — the controller takes
its parameters with the TEC off.

**The PID rows survive STOP and restart.** `stop()` and `__init__` used to call
`_set_PID_T_default()`, which rewrote the whole file; measured consequence: after a Set PID during
an acquisition the controller held P800 and the file 500, and the next START sent 500 again. Both
now call `_reset_temperature_config()`, which puts set-point and flags back and leaves rows 1–4.
The full-default write survives only as the fallback for an unreadable file. **TEC Reset** used to
call it too; since `8a4d25e` it writes nothing: the data sheet (6.3) resets the error register by the
"c" command or by toggling the Enable pin, which is what the button does (X0 / X1 / X0), and the
controller is not powered down, so it keeps set-point and PID through the reset and the file must
too. **During a measurement the process runs the reset** (`0b3e77c`): the GUI's X writes are skipped
then, and the config flag alone is sampled once per sweep, so a 0 / 1 / 0 could arrive as one X0
(bench, thermal latch-up test). Same mechanism as Read PID -- `tec_reset_request` on the parser,
`common/tecReset.reset_sequence()` between two sweeps, "TEC reset done by the acquisition: X0, X1,
X0" in the System Log. Every X the process forwards from the flag is logged too ("TEC switched by
the acquisition: X1"), as the PID parameters are. **Bench, 2026-09-10, impedance worktree**: latch-up
forced at 10 °C, one WARNING line; RESET requested 11:45:15, "TEC reset done" 11:45:21, "error
cleared" 11:45:22; ON then T SET 25, one "TEC switched: X1", no further error.

**An error locks the temperature buttons** (`dcbac95`). The register rides in the processes' status
message (7th element) and `_update_tec_error_lock()` runs after every `_update_TEC_status()`: error
→ ON/OFF and T SET disabled, pill "Error: … — press RESET", RESET the only live control; clear → released
(toggle per connection, T SET per TEC switch). The lock follows the register, not the end of the reset.
RESET is disabled from the press until the register is seen again (≤ 10 s). From Standby the button
asks `E?` after its sequence and logs "error register now N", since nobody samples it there.
Bench, 2026-09-10, during a multiscan: locked at the WARNING line, RESET the only live control;
"reset done" → "error cleared" → "TEC controls released", ON back, T SET grey until ON. **STOP does
not clear the lock** (`43f4590`): STOP redraws the card to idle, so `stop()` ends by putting the lock back
if the last register had an error — the bench had found the card idle with RESET grey while the
latch-up still stood. On connect the GUI asks `E?` once and sets the lock from the answer ("TEC error
register on connect: N"). Bench, 2026-09-10: latch-up, STOP → card still locked, RESET live; RESET from
Standby → OFF / ON / OFF, "TEC controls released", "error register now 1 (clear)"; Disconnect and
Connect with the error standing → locked from the connect-time E?. Every path of the lock is bench-verified.

**The controller's errors reach the System Log on change** (`e863a24`): `common/tecStatus.py` decodes
the register the firmware appends to every temperature sample, once for both processes, and reports
"WARNING: MTD415T Temperature control error: Thermal Latch-Up" when a bit appears and "... error
cleared: ..." when it goes, through the message queue. Not once per sweep as the old console print
did; the pill shows the continuous state. `Constants.ERROR_REG_EVENT` has one name per bit since
`2e313b7`: a missing comma had left 15 names and bits 13/14 mislabelled.

⚠️ **The MTD415T does have a flash** (data sheet 6.2.5): the "M" command saves T, W, L, d, G, O,
P, I, D, C and S, and the controller boots from it. The firmware never sends "M", which is why a
power cycle returns to the factory values and why config.txt is the memory. Saving Default #1 into
each instrument once would make the controller boot with it; the flash has a limited number of
erase cycles, so it would be a deliberate, rare action, not something done on every Set PID. Not
built; in the inventory.

⚠️ **Nothing but Set PID may write rows 1–4.** `_get_temperature()` (T SET) used to rewrite all seven
rows and take the PID from the hidden `tab_2` spin boxes; while init reset those widgets the fault
was invisible (every T SET put Default #1 back), once init stopped touching them it sent the
factory values (measured: P1000 I200 D100 after a T SET during a run, `7a7f1b3`). It writes the
set-point and its flag now; the hidden widgets were removed the same day (`51034e8`).

**On connect the controller is aligned to the file**, software → machine, the same direction
START has always taken. `_align_pid_with_controller()` runs after the firmware and board-number
queries: `C? P? I? D?`, and if the answer differs from the file, send the file and read back.
One log line, always with the numbers:

```
PID on connect: aligned, controller reports C50 P800 I200 D100.
PID on connect: controller had C50 P1000 I200 D100, set to C50 P800 I200 D100, read back: match.
PID on connect: controller had C50 P900 I200 D100, set to C50 P600 I200 D100, read back: match.
PID on connect: the TEC controller did not answer (C? P? I? D?); nothing sent. Is it powered?
```

The first three are the bench: a reconnect without power cycle, a power cycle (factory values),
and a `P900` typed from a terminal in the same power cycle. A controller that does not answer, or
a board still streaming sweep data, is left alone and said so. Cost: about two seconds per connect.

⚠️ A "PID of the instrument" does not exist anywhere in the hardware: whatever the controller
reports at connect, a program wrote it in the same power cycle. If instruments with different TECs
ever need different loops, the only place that memory can live is the PC, keyed by the board number
(known at connect). Not built; not asked for.

### ⚠️ File descriptors: one Worker costs ~100, and the shell's limit may be 256

Bench, 2026-09-09: START failed twice with "OSError: [Errno 24] Too many open files" inside
`multiprocessing.Queue()`. The terminal running the app had macOS's default soft limit, 256. `lsof`
on the live process: **65 PSXSEM + 35 PIPE for one Worker** — 14 queues, each a pipe plus its locks
and semaphore — over a base of ~40; and `start()` built the new Worker while `self.worker` still
held the old one, so for an instant there were two, ~240. Intermittent, not progressive: no leak,
just the peak. Three things since `3cefc79`:

- `common/fdLimit.py` — `raise_soft_limit()` runs in `app.py` before `QApplication` (65536 where the
  system allows it; macOS refuses anything above `kern.maxfilesperproc`), so the application no
  longer depends on the shell that launched it. Windows has no rlimit: the call is a no-op there.
- `Worker.close()` releases the queues and the process objects; `start()` calls it on the previous
  worker **before** building the new one. Not on STOP: the plots keep reading the worker's buffers
  after a run, and `is_running()` must keep answering. ⚠️ It **joins the two processes first**
  (`34f8388`): `stop()` signals the parser and terminates the acquisition without waiting, and until a
  process is seen to have exited `multiprocessing` keeps its object in its children list — which
  holds the parser, which holds every queue, which holds the semaphores. Closing the queues alone left
  75 of 93 descriptors (bench: 97 before the second START instead of ~15); join + close +
  `active_children()` + `gc.collect()` leaves the base.
- The System Log prints "open file descriptors: N of limit M" on every START and STOP. A leak is a
  slope there. **Bench, 2026-09-10, three cycles with every auxiliary window open during the run**:
  before START 16 / 24 / 24, after STOP 118 / 118 — a fixed 8 after the first cycle, no growth.

⚠️ Every new `Queue()` in the Worker costs ~7 descriptors. Adding one is fine; adding one without
knowing this is how a machine with a 256 limit finds out.

### Datalog file names — the Q-1 rule, and the copy that defeated it

`YYYY-MM-DD_hh-mm-ss_<label>.csv` in `logged_data/`, where the label is `F0 F3 F5 F7 F9` for a
single-overtone run and `multi` for a multiscan. Ported from Q-1 v3.0 (`b6fd052`) on 2026-08-28;
before that the format was `%Y-%b-%d` with the label spelled `fundamental` / `3th Overtone`, which
put `Jul` before `Jun` in a directory listing and put a **space inside the file name**.

- The labels come from `common/switcher.py` and, in NEXT, reach **nothing but the file names**:
  `Worker.get_overtone()` has no caller in the UI (in Q-1 it fed the `info2` readout). Renaming
  them is a storage change, not a display change.
- ⚠️ **The format string lives in `Constants.csv_default_prefix` and nowhere else.** `Worker.start()`
  used to declare its own copy of it, so editing the constant renamed nothing — the kind of defect
  that reads as "the change did not work" rather than as a second definition.
- ⚠️ **Nothing composes a datalog name at import time.** `Constants.csv_filename` and
  `csv_sweeps_export_path` were `strftime` calls in the class body: they carried the moment the
  module was imported, not the moment START was pressed. Both are gone; the timestamp is taken once
  per START in `Worker.start()` and the raw-sweep dump path derives from it in `store_data`.
- Old logs keep their old names and stay readable — **nothing parses a datalog file name.** Datalog
  View decides the column layout from the row width (see its format trap above), and the harmonic
  order from the frequencies.

### ⚠️ One datalog row per cycle — the temperature message is the clock (2026-09-17)

`Worker.store_data()` runs from the handler of the temperature queue, which the multiscan process feeds once
per overtone. Until 2026-09-17 the multiscan row was gated on `self._overtone_number == 0`, a value that
arrives on the **status** queue and was consumed **after** the temperature queue: inside one drain every
pending temperature message saw the same stale number, so a cycle produced 0, 1 or 5 identical rows depending
on how the GUI timer fell against the process (96 duplicate rows in 486 on 2026-09-11, 19 s gaps). Rules now:

- the temperature message of an overtone is `[time, T, overtone, is_last_of_cycle]` and is posted **after**
  that overtone's F and D messages (`Multiscan.elaborate_multi`; `_overtones_in_cycle` is set by `run()` from
  the frequencies file);
- the worker drains **F, D, then temperature, then status** (`consume` block): with separate multiprocessing
  queues the drain order is the only ordering there is, and the row must find the last overtone's values
  already in the stores;
- a row is written when, and only when, `is_last_of_cycle` is set; the time-controlled sampling branch checks
  its interval only at a cycle end, so every row is a whole cycle.

⚠️ Never gate a write on a value from another queue. ⚠️ Serial and Calibration post two-element temperature
messages and flag no cycle end: the single-frequency datalog is written on every call, as before.

### Plot Controls > N-SCALE, and the one thing that differs between the branches

Pressed, every plotted frequency is divided by its harmonic order (1, 3, 5, 7, 9), so the overtones
can be read against one another. It divides **whatever is drawn**: the shift when a reference is
set, the absolute frequency when it is not.

⚠️ **Display only.** `_nscaled()` is applied where the plotted series is built and nowhere else —
the buffers, the datalog and the status bar keep the measured values. The readout cards follow
because they are handed the same arrays as the curves; that coupling is deliberate and worth
keeping, since a card that disagrees with the line above it is the recurring defect here.

Five places apply it, and a sixth would be easy to miss: `_update_plot` builds the plotted frequency
at **four** points (single / multiscan × reference / no reference), and `_cursor_series` reads the
worker buffers **directly**, so the Δ readout has to divide too or it prints unscaled hertz under a
scaled curve.

While the control is off, `_nscaled` returns the object it was given unchanged — same identity, same
type — so nothing about the ordinary path moved.

⚠️ **`main` scales frequency only; `impedance-analysis` scales dissipation as well.** This is the
one place the two branches are meant to behave differently. It is specified, not drift, and must not
be reconciled by a cherry-pick in either direction — the dissipation panel does not hold the same
quantity on the two. The divisor's docstring repeats this at the point where someone would be
tempted to "fix" it, and the verification suite reads which contract it is checking from the
environment so the same gates run on both worktrees.

### The time axis of the real-time plots

`Constants.ElapsedTimeAxis`, ported from Q-1 v3.0 on 2026-08-28. The plotted x values stay **epoch
microseconds** — buffers, datalog and Δ cursors are untouched; only the tick labels are relative:

    0    45    2:00    5:00    1:02:05        (SS under a minute, M:SS under an hour, H:MM:SS above)

The reference is latched **once** per run with `set_start_time()` (which ignores `None` and NaN) and
cleared in `start()` with `reset_start_time()`. Four axes use it: frequency, dissipation,
temperature and the TEC-current window.

⚠️ **Before the reference is latched the axis draws empty labels, and that is the point.** The
previous axis (`DateAxis(time_format='seconds')`, now removed) printed `int(value/1e6)` in that
state — the raw epoch, `1787904318` — for the whole warm-up, because in single mode the reference is
only taken when `_ser_control` reaches `Constants.environment`. An axis that says nothing is better
than an axis that says 1787904318.

⚠️ **The reset belongs to `start()`, not to `stop()`.** The finished run stays on screen after STOP
and its ticks have to keep meaning something; clearing there would blank the labels of the plot the
user is still reading. There was a commented-out block in `stop()` proposing exactly that.

⚠️ **`self.start_time` is in microseconds in both modes now.** It used to be seconds in single mode
and microseconds in multiscan, and the four calls to `SecondWindow.update_plot` compensated by
dividing by 1e6 in two of them. One unit, four identical call sites.

⚠️ **`RingBuffer.get_all()` returns the *newest* sample at index 0** and pads the tail with NaN —
measured: three appends into a buffer of five give `[30 20 10 nan nan]`, and its own comment saying
"from the oldest to the newest" is wrong. Array order runs backwards in time, which is the trap
under everything below.

⚠️ **The reference is the first datum *shown*, not the first sweep *acquired*** — changed on
2026-09-01, and this reverses what this section said before, so the reasoning is kept.

`Serial.elaborate` pushes a timestamp on **every** sweep but a NaN value until `_k >= environment`,
because no trimmed mean exists before the circular buffer has filled. The reference used to be
`np.nanmin(t1_buffer)` — the oldest timestamp present, which belongs to sweep 0, a sample that is
never drawn. So the first point that *is* drawn landed at `environment × sweep_period`: **measured
5.4 s** with `environment = 3` and a 1.8 s sweep, and 15–20 s at the production value of 10. The
operator sees a run that starts several seconds late.

`_first_valid_timestamp()` takes the last element of the leading run of non-NaN **values** — the
oldest sample that actually carries a datum — and that instant becomes zero. It returns `None` while
nothing valid has arrived, and the caller retries on the next tick rather than latching onto a
sample nobody will see; the old code fired once on `_ser_control == environment`, which assumes the
counter and the data reach the GUI on the same tick, and they travel on different queues.

⚠️ **And the claim that multiscan already used `nanmin` over the buffer was wrong.** Multiscan takes
`buffer[0]` — the *newest* sample — **per overtone**, and only then `nanmin` **across the five
overtones**. That is a minimum over overtones, not over time, and it is why multiscan never showed
the offset: it has always latched onto the first valid datum, and it calls `clear()` immediately
after. The two modes agreed on the wording and disagreed on the instant. Single mode now matches.

An all-NaN buffer yields no reference, and `set_start_time` ignores NaN in any case.

Datalog View keeps its own `RelativeTimeAxis` — a log records relative time in seconds already, so
it would have to be scaled by 1e6 to feed this axis — but **not its own format**: both call
`Constants.format_elapsed_seconds`, the one definition, and so does the "zero at …" readout under
the reference cursor. The two windows show the same run, and a reader who has just seen `5:00` on
the instrument should not have to translate `0:05:00`. Q-1 makes the same split, with a second axis
class for its log viewer and the same format in it.

### `ui/plotMenu.py` — the plot right-click menu, once

Grid off, then Auto-scale / Reset zoom / mouse mode / grid / Export. **Every panel in the
application uses this module** — the main window included, since 2026-08-27; it had its own copy
until then, and the hooks `extra_actions` (the Δ cursors) and `apply_grid` (the phase twin's grid)
exist so that it needs no second implementation.

Three pyqtgraph facts live in that module because they cost time to find:

- `setMenuEnabled(False)` is needed on the `PlotItem` **and** its `ViewBox`; either one left enabled
  still pops pyqtgraph's own menu.
- the plots of one `GraphicsLayoutWidget` share a `QGraphicsScene`, so `sigMouseClicked` is
  connected **once per scene**, with the plot found by hit test.
- ⚠️ **and the hit test has to be scoped to the scene that fired it.** `sceneBoundingRect()` is in
  the coordinates of the item's own scene, and every `GraphicsLayoutWidget` owns a separate one
  whose origin is its own top-left corner, so rectangles from two canvases are **not comparable** —
  they all start near (0, 0) and overlap almost completely. Testing a click against every target
  regardless of scene is what made this menu act on the wrong plot for months: right-clicking the
  main window's dissipation panel drove the **temperature** plot, because that one sits in the first
  canvas and its rectangle covered the same coordinates. Measured before the fix: two of the main
  window's four panels answered with the wrong plot, and Datalog View's temperature panel answered
  with the frequency one.

The rectangle tested is the **`PlotItem`'s**, not the `ViewBox`'s — axes, title and legend margin
are part of the plot to the eye and outside the `ViewBox`, and a right-click on the axis strip used
to open nothing at all. Where two candidates in one scene both contain the point, the smaller wins.

### `ui/widgets.py` — why the chevrons are painted

`ChevronComboBox` / `ChevronSpinBox` / `ChevronDoubleSpinBox` draw their own chevron; the style sheet
switches the platform arrow off. **Do not "simplify" this into pure QSS**: the CSS-triangle trick on
`::down-arrow` is not honoured by Qt 5.9.7 — it paints the box, so the arrow comes out a rectangle,
measured on this build. An image would mean one asset per theme times one per pixel density.

⚠️ The spin buttons are **invisible, not gone**: the sheet removes their border and arrow, not the
sub-control, so clicking where the glyphs are still steps the value.

⚠️ **A combo popup is two widgets**, the list and a `QFrame` container, and the container is a separate
top-level window: a `QComboBox QAbstractItemView` rule in the window's sheet **does not reach it**. Its
colours ignored theme switches until `_style_popup()` started setting the sheet and the QPalette on
both objects directly. The popup list is deliberately square-cornered — it is an opaque window, so a
rounded background leaves the window's own colour showing at the corners. On macOS a light native
frame may still show around it; on Windows it does not.

### The overtone chips, and why they still stretch

`F1 F3 F5 F7 F9` in the Measurement Setup card share whatever width the sidebar has: each is
50 px at a 260 px row, 64 at 330, 78 at 400, with the gaps fixed at 3. Pinning them so a wider
sidebar buys **spacing** instead has now been tried twice and reverted twice — `1e587d7`, and again
on 2026-08-28. The second attempt worked mechanically and was rejected on looks: at a wide sidebar
five fixed chips with 80 px gaps read as five islands, which is worse than five wide buttons.

What the two attempts established, so a third does not rediscover it:

- ⚠️ **`setFixedWidth` alone does not pin these buttons.** `theme.qss` carries `min-width: 0px` on
  the chip rule, and a style-sheet min-width beats the widget's own minimum — measured, the layout
  item reports a minimum of 8 px however wide the button says it is, which is how the first attempt
  came to report 75 and render 42. What stops the row **stretching** them is a `Fixed` size policy.
- ⚠️ **A pinned width is honoured only while `5*W + 12 <= row`**, so raising it on its own does
  nothing once the row cannot hold it: 72 px per chip needs a 372 px row, and the pane maximum is
  400. Widening the pane to reach it is a second change, not a detail.
- **The sidebar takes 48 px off the pane before the row sees it** (measured: the container's minimum
  is the row's minimum plus 48), and **every pixel of chip costs five of container minimum** — which
  is the budget for tuning it, against the clipping in §5.
- ⚠️ **Five equal chips spanning the row are already the widest those chips can be.** Nothing else
  is in that row, so pinning a width can only make them *narrower* than the row would give and move
  the difference into gaps. Wider chips means a wider sidebar, or nothing.
- The 3 px between them is worth 2.4 px of chip (12 px over five). Closing it to 0 was tried on
  2026-08-28 and put back the same day: 52 / 66 / 80 px chips at rows of 260 / 330 / 400 against
  50 / 64 / 78, and touching pills read worse than the two pixels were worth.
- Packing the chips left with **one trailing spacer**, the treatment the temperature buttons get, is
  the variant neither attempt tried. It keeps them grouped instead of scattered.

### The menu bar, homologous with Q-1 v3.0

Same four menus in the same order, and within each the same grammar as Q-1 — verified by dumping
both menu trees at runtime, one process per tree (two openQCM packages in one Qt process segfault).

| menu | NEXT |
|---|---|
| File | Open Log… ― Quit |
| View | Sidebar · Status Bar · Δ Cursors (F / D) · Grid ― Theme › (Light, Dark) |
| Tools | Raw Data View · Peak Data View · PID Control · Raw Data (from sweep files) · Tec Current ― Check Firmware Version |
| Help | Website · Email Support ― Check for Updates… ― About openQCM NEXT |

The correspondence is by **handler, not by label**: `actionFirmware` runs `get_firmware_version()`,
which is Q-1's *Check Firmware Version* and lives under **Tools** there, not under Help;
`actionSoftware` runs `get_web_info()`, which is Q-1's *Check for Updates…*; `actionHelp` opens the
software page, Q-1's *Website*. The labels moved to say what the code does.

⚠️ **No objectName changed.** Qt reaches these actions through `connect()` and by string, so a
rename is a label change only — the rule from `CLEANUP_PLAN.md` §0.

Four differences that are deliberate, not drift:

- **Grid** is NEXT-only: pyqtgraph's own right-click menu has no grid entry. It sits beside the
  cursors, the other plot-display toggle.
- **Sidebar**, not Q-1's *Left Panel*: the codebase says sidebar everywhere (`sidebarPane`,
  `sidebarScroll`, `sidebarContainer`), and a menu label disagreeing with all of it is worse than
  disagreeing with Q-1. Same reasoning for **Δ Cursors (F / D)**, which names the two panels it
  toggles, and for the **Light / Dark** submenu entries, where Q-1's "Light Theme" repeats the name
  of the submenu they sit in.
- **Measurement Parameters** and **User Guide** are Q-1-only: NEXT has no such dialog and no second
  URL. Nothing was added as a dead entry.
- Two entries are planned, with their position already fixed by Q-1: **Check Board Serial Number**
  immediately after *Check Firmware Version* in Tools, and **Download Update** immediately after
  *Check for Updates…* in Help. Both are marked in `_build_menubar`.

### The status bar: one dot, plain text

The machine state is the **colour of one dot** (`statusIndicator`), as in Q-1 v3.0: grey disconnected,
yellow connected and idle, orange processing or recoverable warning, green monitoring, red error.
`infostatus` and `infobar` are plain text beside it. Write through `_set_status(key, text)` and
`_set_message(text)` rather than pairing a `setText` with a stylesheet.

It used to say the state three times — a coloured pill, a `<font color>` inside the message, and the
literal word "Infobar" printed in front of it. The dot colours are absolute, not palette entries: they
are state semantics and must mean the same on both themes.

### ⚠️ Sweep dump: development only, off by default

`common/sweepDump.py` is the only writer of `sweep_data/<n>.txt`, gated by
`Constants.dev_sweep_dump` (default `False`). Enable it for a session without touching source:

```bash
OPENQCM_SWEEP_DUMP=1 python3 run.py
```

**Tools → Raw Data (from sweep files)** — the older matplotlib viewer — is hidden while the dump is
off, since it would only open an empty or stale window. It is kept working (it now calls
`resonance.py`), but the live view is the one to build on.

Its module, `sweep_data/plot_sweep_spline.py`, is imported **inside `_raw_data_plot()`**, not at
the top of `mainWindow.py`: a release tree may drop `sweep_data/` altogether and still start, and
matplotlib is no longer loaded at launch on `main` (measured: not in `sys.modules` after importing
`mainWindow`, import time 2.05 s → 1.61 s headless). Keep it that way — nothing under `sweep_data/`
may be imported at module level from code that ships.

⚠️ **`sweep_data/` is overwritten on every acquisition.** Copy the files somewhere else before
analysing them.

### `core/averaging.py` — why the buffer length no longer decides robustness

`robust_mean()` replaces `scipy.stats.trim_mean` at the six places that average the raw frequency,
dissipation and temperature buffers. The estimator is the same (sort, drop k per tail, average the
rest); what changed is how k is chosen.

`trim_mean` drops `int(proportiontocut * N)` samples per tail, which with `proportiontocut = 0.10`
is **zero for every N below ten**. The outlier rejection VER 0.1.6 was introduced for therefore
existed only because `Constants.environment` happened to equal exactly 10 — a coincidence, not a
property, and one that any resizing of the buffer would have destroyed **in silence**, with nothing
in the logged output to show that the average had become a plain arithmetic mean.
`trim_count()` adds a floor of one sample per tail and a ceiling of `(n-1)//2`.

⚠️ **If you touch this, the gate is exact equality against `scipy.stats.trim_mean` at N=10 and
N=50 on real buffers.** Production values must not move. Two things learned by tripping over them:
- k equals `int(proportiontocut * n)` for every n ≥ 10, so wherever the old code trimmed at all the
  result must be **bit-identical**, not merely close.
- ⚠️ `np.mean` adds in array order, so `np.sort` and `np.partition` give results differing in the
  last bit even on the same retained samples (measured: 25.045000000000002 against
  25.044999999999998). `robust_mean` partitions with the same kth arguments as `trim_mean` for
  exactly this reason. Do not "simplify" it to a full sort.

**NaN is trimmed, not propagated**: it orders above every real number, so one NaN goes out with the
high tail. With more NaNs than k the result is still NaN. This differs from the old behaviour only
on a short buffer (at N ≥ 10 `trim_mean` already dropped it).

### The two curve palettes, and why the light panel is grey

`Constants.plot_color_multi` (frequency, blue) and `Constants.plot_color_multi_diss`
(dissipation, brown) are **two ramps specified in luminance**, not two lists picked by eye. Read
them from `Constants`; nothing may hard-code a curve colour.

Rec. 709 luminance, the number every decision below is made on:

| # | frequency | Y | dissipation | Y |
|---|---|---|---|---|
| 1 | `#0000FF` | 18 | `#873814` | 70 |
| 2 | `#007FFF` | 109 | `#AE5A34` | 105 |
| 3 | `#00BFFF` | 155 | `#CE7E5B` | 140 |
| 4 | `#60CCEF` | 184 | `#E5A487` | 176 |
| 5 | `#92E4EB` | 211 | `#F7CBB7` | 211 |

⚠️ **A ramp that mirrors another ramp's *shape* is not a ramp that can be read.** The
first brown series reused the blues' fractions of the way to white. Because brown starts light
(156 against pure blue's 18), the five landed inside a 58-point band with steps of 10-13, and on
the instrument the middle overtones were not separable. The brown is now hue-locked at 18.4 deg
with saturation falling 0.85 -> 0.26 and V solved per entry for the target luminance: steps of 35.

⚠️ **Both ramps are bounded by the panels they are drawn on**, so the panels are not
free either. `theme.PLOT[*]["bg"]` reads the interface's **own window colour** — `DARK["window"]`
(43,43,43) and `LIGHT["window"]` `#f2f4f7` at 244. One dict, four canvases: the main
window and all three auxiliary views set their background from it. The light panel was `"w"`, and against pure
white the palest entry of each series all but vanished. Two consequences worth knowing:
- The ceiling of both ramps is **211**, which clears the light panel by 33. The palest blue used to
  be `#BFFFFF` at 241 — three points from the panel — and read by its cyan tint alone.
- Entry 4 of the blue moved too. Capping entry 5 at 211 while leaving 4 at 205 would have left six
  points between F7 and F9: one defect for another. The **three identity blues (1-3) do not move**.

Still on the blues in both panels: `plot_color_multi_g`, the branch-only hex mirror used by the
conductance plots — a copy of an *older* blue palette that has never tracked this one. (The legacy
`data_view` viewer was the other one; it was retired on 2026-08-27.)

Raw Data View and `plot_sweep_spline` draw amplitude sweeps; blue is correct there.

### ⚠️ `Constants.environment` is currently a development value

It is **3**, not the production **10**, so test runs leave warm-up almost immediately.
**Restore 10 before any production build.** The reason is now **purely metrological** — how many
sweeps go into each logged point, and how long the instrument takes to settle. It used to be more
than that (shortening the buffer switched off the outlier rejection); `core/averaging.py` removed
that dependency, so do not repeat the old warning. The constant carries a banner explaining both.

### Also done on main
`run.py` entry point; full README; `requirements.txt` / `environment.yml`; Raw Data fix
(restored the functional `sweep_data/*.txt`); **robust trimmed-mean averaging** of the raw
acquisition buffer; **observable plots default to Y autorange** in development
(`Constants.plot_force_yrange`); **responsive peak-detection (calibration) cancellation**
(ported from Q-1 v3.0 — Stop now interruptible mid-sweep, clean shutdown); **GUI theme system
dark/light** (`ui/theme.py` + View → Theme menu, Phase 0 of the GUI redesign); **phase sweep
plumbed into the GUI process** (`consume_queue_P_multi`, which also closed an unbounded
`mp.Queue`); **single-overtone warm-up bug fixed** (the first nine sweeps used to be dropped by a
swallowed `UnboundLocalError`); **outlier rejection made a property of the average instead of a
coincidence of the buffer length** (`core/averaging.py`).

Since 2026-08-28, each with a section of its own above: **datalog file names on the Q-1 rule**
(`2026-08-31_12-27-50_multi.csv`); **the Q-1 elapsed-time axis** on the four real-time plots;
**the menu bar homologous with Q-1 v3.0**; **the machine identification number** end to end —
programmer sketch, firmware `'S'`, host query, sidebar and window title; **firmware `0.1.5c` with
`'Q'`** and the host waiting for the board to fall silent before it asks anything. All see
CHANGELOG.

### Asking the board a question while it may still be talking

⚠️ **The board sweeps once per command and reads serial only at the top of `loop()`**, so a sweep
runs to completion whatever the host does. Stopping an acquisition kills the host's child process;
the **board keeps sending** for the rest of the sweep — about 1.8 s per overtone on this instrument.
A question asked in that window comes back answered with `amplitude;phase` data.

`reset_input_buffer()` does not help: it empties what has arrived, not what is still coming. Three
things fix it, and all three are needed.

- **`_drain_serial()`** waits for the line to fall silent (`serial_quiet_ms` = 250) before every
  query, giving up after `serial_quiet_timeout_s` = 6 s. It runs inside `_serial_query`, so every
  command benefits. Simulated against a board streaming for 1.8 s: 1360 bytes drained, then the real
  answer parsed.
- **`'Q'` ends the sweep in progress** (firmware 0.1.5c). `_reacquire_serial_lock` sends it.
  ⚠️ **Measured at the bench 2026-09-01, it saves nothing here, and the numbers are below.** Keep it
  anyway — it is the right primitive and costs one write — but do not count on it. ⚠️ Only when the
  reported version is one that knows the letter:
  on older firmware `'Q'` has no branch and falls into the sweep parser, where `atol("Q")` is 0 and
  `freq_start` is silently overwritten. ⚠️ **It does not start a scan** — `message` is latched only
  after the **third** field, so a single letter never begins a sweep, and every real sweep command
  re-sends all three. That is the difference from Q-1, whose parser did latch and whose `'F'` really
  could set the board off from 0 Hz; the note here claimed ours behaved the same way, and it was
  wrong. Verified on hardware 2026-09-01: a `0.1.5a` board, which has no branch for `'S'`, answers
  nothing and keeps working. The firmware still gives `'Q'` an explicit no-op branch, because not
  clobbering `freq_start` costs nothing.
  **The fallback is verified on hardware** (2026-09-01, a board deliberately downgraded to
  `0.1.5b-TEST`): no `'Q'` is sent, the drain alone does the work — `Drained 7172 bytes` — and the
  firmware version and the board number both come back correct afterwards, in single mode, in
  multiscan and after a peak detection.

  ⚠️ **And then the same 7172 bytes appeared with `'Q'` working, which is how the following was
  found.** Two defects, one after the other, and the second is the one that matters:

  1. The `'Q'` write sat inside the **`except`** of `_reacquire_serial_lock`, so it could only run
     when re-opening the port *failed* — and a failed `_open_serial_lock` raises with the handle
     still closed, so even there the write would have failed. **`'Q'` had never been transmitted.**
     Four bench sessions passed over it because the drain produced the right answer regardless: the
     feature was dead and its own fallback hid the symptom. Moved to the success path, where it now
     logs `Stop-sweep sent to firmware <version>`.
  2. With it genuinely transmitting, the drain reported **7172 bytes again, the same to the byte**.
     The drain now logs its duration, and that is what explains it: **414 ms total, 268 ms of which
     is the unconditional quiet window**. The bytes read out in ~146 ms — seven turns of a loop
     polling every 20 ms — so on USB CDC they were already buffered; a board still sweeping would
     have run past 1500 ms.

  The firmware is not at fault: its poll is correct and correctly placed, at the end of an iteration
  so a break never lands mid-line. **The sequence is what makes the letter late.** The parent regains
  the port only after the child releases it, and the child releases it once the board has finished,
  so `'Q'` always arrives to an idle board. A timely one would have to be sent by the **child**, and
  its entire prize is those ~146 ms, since the 250 ms quiet window stays either way. Not worth
  restructuring the stop path for — but if anyone ever wonders why `'Q'` seems to do nothing, this
  is why, and the answer is not "the firmware ignores it".

  ⚠️ **The drain is the mechanism that recovers the port, and always was.** Read the two numbers on
  its line together: a total close to the quiet window alone means backlog, a total far above it
  means the board is still talking. The count on its own cannot tell those apart, which is exactly
  how this went unnoticed.
- **`_board_busy()`** keeps a busy board from being reported as an old one. An unrecognised reply used
  to reach the "no firmware information" branch, which answers *Please update firmware version* — the
  wrong problem to send someone looking for. Two signs, either is enough: the port never fell silent,
  or the answer carries a semicolon, which no version and no identification number does and every
  sweep line does.

⚠️ **A peak detection ends without going through `stop()`** — the completion path calls only
`_enable_ui(True)` — so it is the one place that has to call `_reacquire_serial_lock()` itself.
Without it the GUI never takes the port back and the two device queries stay greyed out until the
user disconnects and reconnects.

### A firmware update kills the handle, and the window has to know

Reprogramming the Teensy **re-enumerates the USB device**. macOS tears the device node down and
recreates it, so the persistent handle the GUI holds is dead from that moment: every read raises
`OSError(6, 'Device not configured')`.

⚠️ **The port name does not change.** Measured on 2026-09-01: `/dev/tty.usbmodem131313201` before
the update and the same string after. So the combo box still lists the right entry, the label still
says *Connected*, and nothing on screen suggests anything happened — the handle onto that name is
simply gone. That is what made the fault read as a firmware problem instead of a connection one.

⚠️ **`_can_query_device()` cannot detect this**, and no amount of tightening will make it. pyserial's
`isOpen()` returns the `is_open` flag, set by `open()` and cleared by `close()`; it never probes the
device. After a re-enumeration the flag is still `True`, so the menu entry stays enabled and the
query goes ahead. Only an actual read finds out.

`_drain_serial` therefore returns **three** outcomes, not a boolean:

| outcome | what happened | how long it takes | what the operator is told |
|---|---|---|---|
| `DRAIN_QUIET` | the port fell silent | the backlog, then 250 ms | nothing, the query proceeds |
| `DRAIN_BUSY` | it never fell silent | the full 6 s timeout | *the board is still sending data*, wait |
| `DRAIN_LINK_LOST` | the handle raised | ~0 ms | *the connection was lost*, reconnect |

⚠️ **The elapsed time is the observable, and it is printed for that reason alone.** The two failures
used to collapse into one `False`, and the count of drained bytes cannot separate them — the clock
can, by four orders of magnitude. This is the same lesson as `'Q'`, one layer out: a wrong outcome
that looked right because its fallback produced a plausible message.

`_board_busy()` now claims busy only for `DRAIN_BUSY`; `_link_lost()` covers the third case and
`_report_link_lost()` takes the window to Disconnected, because a GUI claiming *Connected* over a
port that is gone is the state that produced the wrong diagnosis in the first place.

And the updater does not wait to be told: `_run_firmware_updater()` gives the handle up as it
launches the loader. The launcher returns when the loader is **on screen**, not when the board has
been flashed, so there is nothing to wait for and nothing to detect — the connection is forfeit the
moment the operator starts. Declaring it there is cheaper and more honest than discovering it later.

### The machine identification number, and where it lives

`firmware/openQCM_Next_SerialNumber/` writes it into the Teensy EEPROM. Flashed once per board,
then the operational firmware goes on top — the EEPROM survives the reflash.

Four bytes, **the layout the Q-1 uses, byte for byte**, so a board is read correctly by either
tool: `[0]` magic `0xA5`, `[1]` series, `[2]` unit high, `[3]` unit low, big-endian.

⚠️ **The format is `SSNN`, one compact integer with no separator** — series without leading zeros,
unit always two digits: series 20 unit 52 is `2052`, and the board after `2099` is `2100`, series 21
unit 00. `sprintf(buf, "%u%02u", series, unit)`. Valid range 100–25599. The older `SERIES-NNNN`
form (`20-0055`) is obsolete and must not appear in firmware, serial output, logs or GUI.

The operator sets **one macro**, `OPENQCM_SERIALNUMBER`; series and unit are derived from it at
compile time (`/100`, `%100`), so the two cannot disagree. A `#error` rejects anything outside the
range — verified, it fires at 99 and at 25600. An existing number is never overwritten without a
`Y` on the serial monitor.

The verification line the programmer prints is `SERIALNUMBER = 2052`: a plain integer, no dash, no
leading zeros on the series.

**The operational firmware only reads it.** Command `'S'` replies with the number (`1900` on both
worktrees' sketch) or with `NO_SERIAL` when the magic byte is absent — it never invents or writes
one.

The command arrived with `0.1.5b`; the current pair is **`0.1.5c`**, which added `'Q'`. Each
version is its own pair of folders, production and no-TEC `-TEST`:

| folder | state |
|---|---|
| `openQCM_Next_py_0.1.5c_teensy` + `_TEST_` | ⭐ **current** — `'S'` and `'Q'`, what `Constants.FW_VERSION` expects |
| `openQCM_Next_py_0.1.5b_teensy` + `_TEST_` | superseded — `'S'` only. Delete once no board runs it |
| `openQCM_Next_py_0.1.5a_teensy` + `_TEST_` | superseded — neither. Delete once no board runs it |

⚠️ **A version bump means a new folder, not an edit in place.** A folder named for a version whose
firmware reports a different one is the kind of thing that costs an afternoon on a bench — it
happened once here already, on 2026-08-31, and was undone the same day.

⚠️ **A disabled menu entry needs its colour said explicitly.** Once the style sheet sets a colour on
`QMenu`, Qt stops applying its own disabled palette to the items, so an entry that cannot be clicked
still *looks* like one that can — which reads as a bug rather than as a state. `QMenu::item:disabled`
and `QMenu::item:selected:disabled` are in `theme.qss` for that; the second stops the highlight
following the cursor over an entry that would do nothing, because an item that lights up and then
ignores the click is worse than one that never lights up.

⚠️ **Both menu queries are greyed out unless the board can answer** — `_can_query_device()` is the
single predicate, and it drives **both** the menu state and the two methods' own guards, so a greyed
entry and a refused query cannot disagree about what the instrument is doing.

It is not `_serial_connected`. `start()` hands the port to the acquisition process by **closing the
handle without dropping the reference**, so `_serial_lock is not None` stays true while the child
owns the port; whether it is **open** is what decides, together with the run state.

⚠️ **The refresh belongs to `_reacquire_serial_lock()`, not to `stop()`.** `stop()` calls
`_enable_ui` *before* `worker.stop()` and a second before the port comes back, so the menu state it
computes is a second out of date — after a Stop or a finished peak detection the entries stayed grey
even though the instrument was in standby. Every path that regains the port ends in
`_reacquire_serial_lock`, which is the one place that sees the true state; handing the port over in
`start()` greys them immediately for the same reason. They talk to the
board over the persistent handle, so they need an open port and an idle acquisition: while a
measurement runs the child process owns the port. Disconnected, the firmware query used to run
anyway and come back empty, which that code reads as "no firmware information" and answers with
*Please update firmware version* — a closed port reported as an out-of-date board, which is the
wrong problem to go looking for. The runtime guards inside both methods stay: a menu item can be
reached by a shortcut, and the automatic query on connect does not go through the menu at all.

**The host side**: `Tools > Check Board Serial Number`, and the same query run silently on connect.
Three outcomes, and they are not the same thing — no valid answer at all is a firmware older than
0.1.5b, `NO_SERIAL` is a board whose EEPROM was never written, anything matching `^\d{3,5}$` inside
100–25599 is the number. It goes under the brand in the sidebar (`lblSerialNumber`) and into the
window title.

⚠️ **NEXT's `PopUp` has no `info()`** — that is a Q-1 method, and the port used it: the success path
raised `AttributeError` the first time the menu entry was clicked. The NEXT equivalent is
`info_not_blocking()`. It survived verification because every outcome had been exercised with
`auto_mode=True`, the mode that skips all four popups. Driving a dialog-bearing path headlessly
needs `PopUp` swapped for a recorder anyway — `PopUp.warning` is modal and hangs the run.

⚠️ **The window title has two independent suffixes** — the board number, which arrives on connect,
and the datalog filename, which arrives on START — so it is composed in one place,
`_window_title()`. Writing either of them straight into `setWindowTitle` is how one erases the
other.

⚠️ **`Constants.FW_VERSION` moves with the firmware.** The host compares the reply to `'F'` against
that string and pops a firmware-update warning when it does not match, so a version bump that stops
at the sketch turns into a warning on every connect. It is `'0.1.5c'` now.

#### Bench verification — complete, 2026-09-01

Every scenario has been run on hardware. Recorded because re-running them costs a board downgrade
and an EEPROM wipe each.

| scenario | board | result |
|---|---|---|
| number valid, connected and idle | 1900, `0.1.5c` | popup, `S/N 1900` in the sidebar, `[1900]` in the title |
| the two entries greyed | — | greyed while disconnected and while acquiring, active when idle; the number stays in the title throughout |
| standby after a Stop | 1900, `0.1.5c` | both entries answer at once, single and multiscan |
| standby after a peak detection | 1900, `0.1.5c` | answers without a reconnect — the path that does not go through `stop()` |
| firmware that does not know `'S'` | `0.1.5a-TEST` | empty reply → *needs firmware 0.1.5c or later*, and nothing else |
| EEPROM cleared | `0.1.5c-TEST`, magic byte zeroed | `NO_SERIAL` → `S/N not programmed`, no number in the title |
| `'Q'` on the no-TEC variant | `0.1.5c-TEST` | the letter is sent and logged; it saves nothing — see the measurement above |

⚠️ Two of these look like failures in the log and are not. A `0.1.5a` board prints
`Board number response: '' (raw '')` **twice** for one connection — that is the connect handshake
and then the operator's own menu check, 2.24 s apart, which is why the line carries `[auto]` or
`[menu]`. And a drain line that does **not** appear at all is the best outcome, not a missing one:
it prints only when it discarded something.

The sketch that clears the magic byte is deliberately **not** in the repository — a tool that erases
a board's identity should not be lying around — so it gets rewritten each time. Twenty lines:
`EEPROM.write(0, 0x00)` guarded by a read of the same byte, then a `MAGIC = 0x..` line every three
seconds so the serial monitor confirms it.

⚠️ **Every reply is parsed by `_first_reply_line()`, not by `rstrip('\r\n')`.** That was the rule
for the firmware version and it only strips the **trailing** terminator: a leading blank line, or a
second line after the one that matters, survives it and then fails an exact comparison for a reason
nothing on screen explains. The branches that raise the update warning printed nothing either, so a
wrong answer and no answer at all looked identical from outside — they log the raw reply now.

The comparison is `_firmware_is_current()`, **one function** — the check appears four times in
`get_firmware_version` and a rule spelled out four times is a rule that drifts. It accepts
`FW_VERSION` and, while `Constants.accept_test_firmware` is on, `FW_VERSION + '-TEST'`: the
prototype board answers `0.1.5c-TEST` and used to raise the update warning on every connect, though
it speaks the whole protocol. The suffix says which board is on the bench, not that the firmware is
older.

⚠️ **`accept_test_firmware` is a development switch — set it to `False` before a production build.**
A shipped instrument must not accept a prototype firmware without saying so. It sits next to
`FW_VERSION` in `constants.py`, under a banner, and turning it off is one line: the check then
rejects `-TEST` and everything else that is not an exact match.

⚠️ The copy of the programmer in the Q-1 repository is still **v2.0**, which writes the same bytes
but prints the obsolete dashed form. The specification calls for v2.1 there. Until that is updated
the two sketches agree on the EEPROM and disagree on what they print.

### ⚠️ TEST-ONLY firmware variant (no-TEC board) — temporary, will be removed
`firmware/openQCM_Next_py_0.1.5c_TEST_teensy/` (`0.1.5c-TEST`) is a **throwaway internal
variant** for a special bench board that **does not mount the TEC section**. It is a copy of the
production firmware of the same version with all MTD415T/Serial1, MCP9808, fan and TEC-pin code removed (on a
no-TEC board those blocking Serial1 reads stall the sweep), and the temperature field **simulated**
(`25.00 °C` baseline + slow ±`0.05 °C` wobble; `#define USE_INTERNAL_TEMP` switches to the real
Teensy 4.0 die temperature). The DDS/ADC sweep engine and the host wire format are unchanged
(`temperature;status(0);error(0);s`), so **no software change is needed** and TEC commands are
accepted as no-ops. **Do not build features on this variant.** It exists for a prototype board and
will be deleted once that board is retired — but it is **kept in step with production while that
board is in use**: a change to the host/firmware protocol goes into both sketches, as the `'S'`
`'S'` and `'Q'` commands did on 2026-08-31. Production firmware is
`firmware/openQCM_Next_py_0.1.5c_teensy/`.

## 4. `impedance-analysis` branch (0.1.6G) — detail

**What it is**: impedance measurement via the **conductance spectrum G(f)** derived from the AD8302
MAG/PHASE signals (software post-processing; same firmware/protocol as the classic method).

**Where in the code (on the branch)**:
- `software/openQCM/processors/Multiscan.py`: `parameters_finder_impedance()` (~:328), `_Zabs_Vmag`,
  `_phase_raw_V_phase`, `_G_calc`, `_B_calc`, `_Freq_G`, `_half_bandwidth_G`. Wired into
  `elaborate_multi()` (~:626): it runs **both** the classic and the conductance method but
  **publishes the conductance** results (the classic lines are commented out).
- `software/openQCM/sweep_data/plot_conductance.py`: offline validation script (uses `g*.txt`).
- `docs/impedance-analysis/`: documentation (`conductance-calculation.md`,
  `openQCM_Next_G_Impedance_Analysis.md`, 3 PDFs).

**State / limitations**:
- Implements the **approximate** formula (`G = cosφ/|Z|`); the **exact** complex-impedance version is
  documented only, not implemented.
- **DEBUG** state (`constants.py`: `environment = 4`, `plot_autoscale_yaxis = True`).
- The method is **always on, not selectable** from the UI (hard-wired in `elaborate_multi`). The only
  added control is the **"G DATA VIEW (BETA)"** button (launches the offline plot).
- `elaborate_conductance_multi()` is **dead code** (UNUSED).

**To stabilize / merge**:
1. Make the measurement **selectable** (classic vs conductance) instead of hard-wired.
2. Implement the **exact** formula (complex impedance in the divider).
3. Remove the DEBUG state.
4. **Align with `main`** via `git merge main` (the branch lacks the recent development).

## 5. Planned technical tasks (on `main`)


> 📌 **Source-code cleanup**: a full plan already exists in
> [`CLEANUP_PLAN.md`](CLEANUP_PLAN.md) — produced by a read-only audit on
> 2026-07-20 (baseline `main` @ `630e898`), not yet executed. Dead code, unused
> structures, redundancies, with a per-item confidence tag and a verification
> protocol. Read its §0 before touching anything: PyQt5 5.9.2 with the classic
> `QtGui` namespace must not be "modernised", and Qt reaches methods through
> `connect()`, objectName and overrides, so nothing gets deleted without grepping
> its name as a string across all of `software/`.

### Runtime files: the application must survive their absence

Deciding what is versioned turned out to be the easy half. On 2026-07-28 the runtime
data was untracked (`Calibration_*MHz.txt`, `PeakFrequencies*.txt`,
`sweep_data/*.txt`) and the PeakFrequencies part had to be reverted the same evening,
because the application **does not start** without them and the tool that writes them
lives inside the window that will not open. Two work items, in order:

1. **Make the reading side tolerant, and its errors actionable.** ~30 call sites read
   runtime files with a bare `loadtxt`, which today produces a traceback in whichever
   process happens to hit it first:

   | file | `loadtxt` call sites | read from |
   |---|---|---|
   | `PeakFrequencies.txt` | 11 | `mainWindow`, `worker`, `Multiscan`, `Serial` |
   | `PeakFrequenciesRT.txt` | 2 | `Multiscan`, `Serial` |
   | `Calibration_*MHz.txt` | ~4, through a `filename` variable | `Multiscan`, `Serial` |
   | `config.txt` | 14 | `mainWindow`, `Multiscan`, `Serial` |

   One helper rather than thirty try/except: `FileStorage.load_runtime(path, what,
   remedy)` raising a `MissingRuntimeFile` that carries the remedy. Then two
   behaviours, and the distinction is the point — **start-up paths degrade**
   (`load_frequencies_file()` returns `None`, the legend draws defaults, the status
   bar says what is missing, Peak Detection stays reachable), while **paths inside a
   running measurement raise and stop cleanly**, because there the file must exist and
   carrying on would publish meaningless numbers.
   Verification: rename the files, start the GUI, check it comes up and shows the
   message instead of dying.
2. **Then `config.txt` can follow.** It is the last tracked runtime file, read at
   start-up by both `MultiscanProcess` and `SerialProcess`, and it is the reason every
   pull needs a stash. Once item 1 is in, untrack it — and only then.

⚠️ Whoever does item 1: do not untrack `PeakFrequencies*.txt` before it is finished
and tested. The `.gitignore` says so too, next to those two lines.

Done (raw-data robustness — see CHANGELOG):
- **`trim_mean` anti-outlier averaging**: replaced Savitzky-Golay + `np.average` with
  `scipy.stats.trim_mean(0.10)` on the 10-sample circular buffer for frequency and dissipation
  (per overtone) **and temperature**, in **both** processors (`Multiscan.py` multi-overtone,
  `Serial.py` single-overtone). Added `Constants.trim_mean_proportiontocut`. The replaced
  SG (window=3, order=1) was a linear 3-point moving average with no outlier rejection.
  - **Still pending — Stage C**: the datalog-decimation average in `core/worker.py:767-769`.
    There, average over `get_partial()` (NaN-safe) and note that `trim_mean(0.10)` degenerates
    to the plain mean for buffers < 10 samples (choose proportion or estimator accordingly).

Done (dev plotting — see CHANGELOG):
- **Observable plots Y autorange** (`ui/mainWindow.py`, `Constants.plot_force_yrange`): the forced
  padded Y-range on frequency/dissipation/temperature is gated behind the flag (default `False`,
  routed through the `_set_yrange_forced` helper) so development runs autoscale tight to the data.
  - **Distribution follow-up**: set `plot_force_yrange = True` and tune the paddings
    `y_f_range` / `y_d_range` / `y_t_range` for a stable user-facing view.

Done (responsive peak-detection cancellation — ported from Q-1 v3.0, see CHANGELOG):
- Peak detection (calibration) is now **interruptible cleanly** instead of blocking the Stop button
  for the whole ~1 min sweep. `processors/Calibration.py`: inner sweep-read loop polls `self._exit`
  with a `0.1 s` serial read timeout (Stop acts in ~0.1 s), emits a `-1` cancellation sentinel on
  `parser5` + `return` on mid-sweep cancel, drains stale serial bytes on start. `core/worker.py`:
  `_calibration_cancelled` flag (`is_calibration_cancelled()`), `stop()` joins-then-terminates the
  peak-detection process (graceful) while measurement modes keep the direct terminate.
  `ui/mainWindow.py`: Stop stays enabled during peak detection; `_update_plot` checks the flag first;
  `stop()` shows "Peak Detection Cancelled" and clears the real-time amplitude trace; init
  `_overtones_number_all = 0` (fix for the latent `AttributeError` that Stop-during-calibration exposed).
  - **Note (dormant scaffolding)**: the `-1` sentinel + flag path mirrors Q-1 but rarely fires in
    NEXT — the GUI `stop()` stops the plot timer before the sentinel is consumed, so the user-facing
    "Cancelled" comes from `stop()` and the real cancellation from the responsive loop + graceful join.
  - **Reference sibling repo**: `/Users/marco/claude_code/openQCM_Q-1/OPENQCM` (git; remote
    `github.com/openQCM/openQCM_Q-1`; **v3.0**). This is the authoritative Q-1 roadmap codebase.

GUI redesign (phased, inspired by openQCM Q-1 v3.0 — reference repo `/Users/marco/claude_code/openQCM_Q-1/OPENQCM`):
- **Fase 0 — Theme dark/light — DONE** (see CHANGELOG): `ui/theme.py` (LIGHT/DARK palettes + QSS +
  per-theme plot colors) + `_setup_theme_menu`/`_apply_theme`/`_apply_plot_theme` + `QSettings`
  persistence (default light). Readout fields migrated from inline white to QSS objectName rules.
  - Known Phase-0 limitation: `infostatus` standby stays a light pill on the dark theme (uses HTML
    `<font color=#000000>` text on a white inline background) — harmonise the neutral state in Phase 4.
- **Fase 1 — Single-window QSplitter shell — IMPLEMENTED, ⚠️ VISUAL TUNING PENDING** (committed on
  `main`; the user reported the visual layout is *not correct yet* and will iterate off-session):
  `ui/mainWindow.py::_build_shell()` (called at the very end of `__init__`, after the runtime
  Connect/Refresh buttons exist) re-parents the old two-column `gridLayout_2` into a horizontal
  `QSplitter` **[ scrollable collapsible sidebar | plots ]**. Sidebar order (top→bottom): brand
  (`groupBox_2`), connection (`gridLayout`), F/D readouts (`groupBox_data`), overtone radios
  (`gridLayout_D`), sampling/time (`gridLayout_5`), `line_3`, Temperature/PID tab (`tabWidget`),
  `addStretch`, then **bottom**: action row (`horizontalLayout`) + status (`verticalLayout`, `infobar`).
  Plots (`verticalLayout_plt`) go in the center pane. No widget recreated → objectNames + signal
  wiring preserved (theme Phase 0 and all logic still work).
  - **Re-parenting recipe (KEEP THIS — a subtle Qt gotcha)**: widget → `dest.addWidget(w)` (re-parents);
    bare sub-layout → wrap in a fresh `QWidget` via `container.setLayout(subLayout)` then
    `dest.addWidget(container)`. Do **NOT** use `layout.addItem(takenItem)` for widgets — it does not
    re-parent, leaving controls owned by the old `centralwidget` → mis-rendered. The central layout is
    swapped with the `QtGui.QWidget().setLayout(oldGrid)` throwaway trick.
  - **Revert instantly**: comment out the `self._build_shell()` call in `__init__` → old grid returns.
  - **What to fix on-device** (not verifiable headless): the action row packs 6 buttons + progress bar
    horizontally into a ~360px sidebar → likely overflows/wraps and looks cramped. Candidate fixes: lay
    the acquisition controls vertically (or a 2-col grid), give the sidebar groups real "card"
    styling/spacing, revisit sidebar min/max width (currently 220–360) and splitter initial sizes
    (`[240, 900]`). Note much of the action row is superseded by **Phase 3** (single StartStop toggle +
    status dock) — decide whether to polish now or fold into Phase 3. `QtGui.*` widget classes are
    available in `mainWindow.py` via the matplotlib `qt_compat` shim (so keep using `QtGui.QWidget` etc.).
- **Fase 2 — Tab centrale [ Plots | System Log ] — IMPLEMENTED (pending on-device smoke test)**
  (see CHANGELOG): center pane is a `QTabWidget` (`centerTabs`); the plots are re-parented into the
  Plots tab; module-level `LogStream` mirrors the main process's stdout/stderr into a read-only
  `QTextEdit` (`systemLog`) with `[HH:MM:SS]` timestamps, forwarding to the originals; installed
  after `_build_shell()` (`_install_system_log`), restored in `closeEvent` (`_restore_system_log`);
  theme-aware monospace via `QTextEdit#systemLog` in `ui/theme.py`. **Scope**: captures `print()`
  of the main process only — child-process prints and `logging`-module messages stay on the
  terminal / log file (a `logging.StreamHandler(LogStream)` would add them; optional Phase 2-bis).
- **Fase 3 — Consolidated controls — DONE** (sub-steps below; see CHANGELOG):
  3. Consolidated controls **+ sidebar layout tuning (folded in here)** — sub-steps:
     - **3a single Start/Stop toggle — DONE** (see CHANGELOG): `pButton_Start` toggles Start/Stop
       (`_toggle_start_stop`, uses `worker.is_running()`), green/red via a `running` dynamic
       property + theme QSS (`#pButton_Start`), stays enabled while running, visual state flipped
       inside `_enable_ui`; `pButton_Stop` hidden, inline style dropped.
     - **3d log-filename display — DONE** (see CHANGELOG): runtime `lblLogFile` in the sidebar
       status area (elided + tooltip) + window title suffix; `Worker.get_csv_filename()` mirrors
       the datalog names (serial `<ts>_F<n>.csv`, multiscan `<ts>_multi.csv`, calibration "").
     - **3c status pill theme-aware + state dot — DONE** (see CHANGELOG): `_status_pill(key)`
       helper (standby follows the theme; warn/err/ok keep yellow/red/green with dark text),
       `● Program Status: …` texts, re-applied on theme switch via `_status_key`.
     - **3b overtone quick-select F0–F9 — DONE** (see CHANGELOG): checkable proxy buttons over the
       hidden legacy radios (`scan_selector` untouched); multiscan = multi-select visual filter,
       live during acquisition; serial = exclusive, drives `cBox_Speed` (reverse-order mapping
       `combo_index = count-1-idx`), idle-only; calibration = disabled.
     - **3e sidebar action-area layout — DONE** (see CHANGELOG): Refresh+Connect moved into the
       connection card (bottom row, theme QSS instead of inline styles); action row decomposed —
       plot controls keep the old row, Start/Stop toggle gets a prominent full-width row with the
       progress bar underneath. This resolves the Phase-1 "cramped action row" note. Remaining
       fine-tuning (spacing/polish) deferred to the user's visual pass after the block phases.
- **Riscrittura programmatica GUI (approved follow-up to Phases 0–3)**:
  - **R1 — programmatic builder, structural parity — DONE** (see CHANGELOG): `ui/mainWindow_ui.py`
    (hand-written `Ui_MainWindow`) replaces the generated Designer UI; `_build_shell()` deleted;
    runtime widgets absorbed; File/View/Tools/Help menu skeleton. Contract-checked (all
    `self.ui.<name>` refs exist) + offscreen instantiation verified. Old generated file kept as
    reference. **Pending: user visual check.**
  - **R2 — mockup style pass — DONE + fidelity fixes** (see CHANGELOG): full-width bottom status
    bar (36 px fixed — the unbounded height bug from the first check is fixed; pill + message
    left; F/D/T/S live readings + progress right, reset on Stop); titled cards with the title
    inside (Serial Connection, Measurement Setup, Current Readings, Temperature & PID); Start
    idle = accent blue (running red); F0–F9 chips; menu-bar corner theme toggle; plot canvases
    reordered [sweep+temp, frequency, dissipation].
  - **R2-bis — QSS refinement pass — DONE** (see CHANGELOG): refined palettes (softer borders /
    fields), rounded cards (10px) with 13px bold inside titles, restyled inputs, primary Connect /
    outline Refresh, larger Start (40px, 14px bold), pill chips, borderless bold readout values,
    themed tabs (accent on selected), slim rounded progress, in-window menu polish; TEC state
    banner converted to a theme-aware `_tec_state_pill` helper (off/warn/active/err, re-applied
    on theme switch). **Pending: user visual check.**
  - ⚠️ **Frequency and dissipation stay in TWO separate panels** — the user explicitly rejected
    the mockup's single dual-axis panel. Do not merge them.
    Other accepted deltas vs the mockup: per-overtone readings grid kept (NEXT is multi-overtone);
    Add-On menu superseded by Tools.
- **Fase 4 — plot interactions — DONE (pending user visual check; see CHANGELOG)**: grid off by
  default + per-plot toggle; custom right-click menu on all four plots (auto-scale, reset zoom,
  pan/select mouse mode, grid); **Δ cursors on the separate F and D panels** (Δt in s — axis is
  epoch µs —, ΔF Hz / ΔD ppm via nearest-sample on the fundamental (multiscan) or measured
  overtone (single); right-click per panel or View → Δ Cursors global toggle; items parented to
  the ViewBox with ignoreBounds so they survive clear() and don't drive autorange).
  **Deferred by decision**: min-Y-scale enforcement (to be integrated with `plot_force_yrange`).
  Next: Fase 5 (menu wiring: Tools/Help actions already exist) and the user's GUI fine-tuning pass.
- **GUI fine-tuning — DONE this session (2026-07-17; all committed & pushed, see CHANGELOG)**:
  - **Sidebar compaction**: minimal F0–F9 chips; TEC ON/OFF/RESET on one compact row; **Set/Clear
    Reference merged into a single toggle** (`_toggle_reference`); Temperature state banner
    word-wraps; sidebar scroll `minimumWidth` 220 → 170; a long "Connected: <port>" no longer widens
    the sidebar (`label_COM_status` size policy `Ignored` + full name in tooltip).
  - **Temperature card**: datalog sampling-time selector + whole PID section **hidden** (widgets
    kept alive on a hidden standalone `tab_2`); the redundant inner `QTabWidget` container removed —
    controls sit directly in the card.
  - **Plot Controls card** (Autoscale · Set/Clear Reference · Clear) + new **Autoscale** button
    (`autoscale()` → X+Y autorange on all plots).
  - **Center layout**: vertical `QSplitter` (`plotSplitter`) — amplitude/phase-sweep + temperature
    on top, **collapsible/hideable** via the handle; per-overtone **readout cards moved above the
    plots** ("Frequency (Hz)" / "Dissipation (ppm)"); sidebar "Current Readings" card removed.
  - **Palette reduction** toward blue `#008EC0` + brown `#DD8E6B`: Start/Stop toggle **blue (idle) /
    brown (running)** (added `brown` / `brown_hover` palette keys).
  - **App icon** now loads from an absolute module-relative path (`res/icon/favicon.png`).
  - **Fix**: peak-detection / amplitude-sweep / temperature curves were white → invisible on the
    light theme's white plot background; now theme-aware (`theme.PLOT[theme]["curve"]` +
    `_curve_color()`, re-applied on theme switch).
- **Fase 5 — scientific menu wiring — DONE** (see CHANGELOG): `Help → Help` opens the software
  webpage + new `Help → About`; `View → Sidebar` / `View → Status bar` show/hide toggles
  (`_open_help_website`, `_show_about`, `_toggle_sidebar`, `_toggle_statusbar` in the controller).
  **The phased GUI redesign (Phases 0–5) is complete.**
- **GUI refinement pass — DONE (2026-07-17, see CHANGELOG)**: single **temperature ON/OFF toggle**
  (blue/brown, gated on the serial connection, synced to firmware TEC status;
  `_toggle_temperature_control`/`_update_tec_toggle`/`_tec_on`); unified **secondary outline button
  style** in `theme.py` (Connect/Disconnect, Refresh, AUTO/SET REF/CLEAR, T SET, TEC Reset — blue
  outline, brown for the deactivate state, grey outline disabled) with widths sized to the label
  (HBox + trailing stretch); renames **AUTO / SET REF↔UNSET REF / CLEAR / T SET**; **bold card titles**
  via the QGroupBox widget font (Qt ignores font-weight on `::title`; card content reset to normal);
  **Start/Stop** larger, not bold, with ▷/□ glyphs; **Plot Controls** anchored under Temperature
  (sidebar stretch moved below it); removed redundant captions; **frequency selector shown only in
  Single Measurement** (`_source_changed` `setVisible`); **sidebar** default 300 px, resizable 260–400
  (brand `label_2` set to word-wrap to stop it pinning a ~459 px minimum); temperature setpoint +
  indicator right-aligned. ⚠️ A few small visual refinements remain (per the user, to do later).
- **GUI — remaining / TODO** (polish / optional, after the block phases):
  - **Harmonise the remaining state colors** (status pill yellow/red/green) toward the blue+brown
    palette (deferred by the user during the palette-reduction step).
  - **min-Y-scale** enforcement (integrate with `Constants.plot_force_yrange`).
  - ~~Dedicated "Advanced Temperature Control" window~~ — **done** as Tools → PID Control (§3);
    the hidden `tab_2` widgets and their three functions removed (`51034e8`).
  - **"Serial write skipped: acquisition running" reads like a failure** — it is the GUI declining
    the direct write because the process owns the port, after which the process does the job (T SET,
    TEC ON/OFF, RESET all go through the flag or a request). Cosmetic: say what happens instead.
    Parked 2026-09-10.
  - **Peak Data View: Y follows only when the gesture stops** — parked 2026-09-09, Marco's call
    ("va bene così"). After the three downsampling fixes (§3) a full-span pan still costs 90–160 ms on
    the bench (paint 30–40 ms of it) because the Y autorange re-runs on every X change and restarts
    the update of every item on both linked panels. Measured offscreen: pan 40 ms → 15 ms with the Y
    autorange off during the gesture, 9 ms with the raw dots also hidden. The design ready to build:
    keep Y still while dragging, refit it once to the visible data ~200 ms after the last X change
    (`setAutoVisible(y=True)`, single-shot timer on `sigXRangeChanged`); "Auto-scale" and "Reset
    zoom" in the right-click menu stay. `OPENQCM_PLOT_DEBUG=1` is the yardstick before and after.
  - **Confirmed UX decisions**: single StartStop toggle; **TEC/PID kept in the sidebar** (advanced
    window later); System Log as a tab; default theme light; **frequency & dissipation stay TWO
    separate panels** (single dual-axis panel rejected).
  - ⚠️ **Preserve (do NOT copy Q-1 blindly)**: Q-1 v3.0 has *no* temperature control — NEXT's
    **TEC/Peltier + PID** must stay; and NEXT's **multiscan** multi-overtone selection differs from
    Q-1's single-overtone measurement.

Quick wins:
- **Disconnected-sensor detection** (ported from openQCM Q-1; detailed plan ready, awaiting go):
  add `Constants.min_valid_q_factor = 100` and, in `parameters_finder` — **both** `Multiscan.py`
  (before the `return` ~:317) and `Serial.py` (~:319) — set `self._err1 = self._err2 = 1` when the
  true Q is below the threshold, so amplifier noise from a detached sensor is not logged as a peak.
  **Adaptation — do NOT blind-copy Q-1**: our `parameters_finder` returns `Qfac` = *bandwidth*
  (consumed by the dissipation calc), not a Q-factor. Compute a separate local
  `q_factor = freq_resonance / bandwidth` (inside `np.errstate(divide='ignore', invalid='ignore')`,
  so `bandwidth == 0` → `inf` → passes) **only** for the guard; leave the returned `Qfac` and the
  dissipation untouched. Reuses the existing `_err1/_err2` → `parser6.add6(...)` "-3dB not found"
  pipeline (no new plumbing). Threshold `100` is Q-1's (its bandwidth is FWHM `0.707·f_max`); ours
  uses `f_max - THRESHOLD_DB` (0.3 dB), so the value **must be validated/tuned on hardware** with a
  physically disconnected sensor. Optional first step: synthetic Lorentzian-vs-noise check offline.
- ~~**Robust firmware query**~~ — done on 2026-08-31, though not the way this line proposed. Q-1's
  range-priming answers a different failure (a firmware that misparses `'F'` as a sweep command);
  ours was a board still streaming the rest of its sweep. The cure is `_drain_serial()`, the `'Q'`
  command and `_board_busy()`; see §3, "Asking the board a question while it may still be talking".
- ~~**Firmware updater .hex is two versions behind**~~ — done on 2026-09-01. `firmware_update/`
  now carries both `0.1.5c` images and `_firmware_image()` chooses between them from the version the
  board just reported, so the loader opens with the image already in it. What follows is kept
  because the reasoning is the reusable part. The folder used to ship the `0.1.5` image (POT 180)
  while the software expected **`0.1.5c`** (`'S'` and `'Q'`), so anyone who ran the
  bundled updater landed on a firmware the software would immediately ask them to update.
  ⚠️ **Still to verify: the whole procedure under Windows**, before a production build. Only the
  macOS branch has been run on hardware (2026-09-01, prototype board `0.1.5a-TEST` → `0.1.5c-TEST`).
  The Windows branch hands the image to `TyUploader.exe` through `subprocess.Popen`, because
  `os.startfile` takes no arguments — a different call, on a different loader, never executed.
  ⚠️ **Corrected 2026-09-01**: this line used to say the `0.1.5c` image was *already built*. It was
  not — and **no `-TEST` variant had ever been built either**; only `0.1.5a` and `0.1.5b` non-TEST
  carried a `.hex`. Both `0.1.5c` images have now been built (`teensy:avr 1.58.1`, FLASH 55 120 B
  and 45 500 B) and live beside their sketches. What is still open is the swap inside
  `firmware_update/`, and the question underneath it: the loader is opened with **no file**, so the
  operator picks the image by hand out of a folder whose only `.hex` is the wrong version and, on a
  prototype, the wrong variant. The software already knows which it wants — it has just read the
  reported version, `-TEST` suffix included — and `open -a Teensy.app <hex>` would hand it over.

Backend backlog ported from the more mature **openQCM Q-1** sibling codebase (its CHANGELOG is the
roadmap). ⚠️ Each Q-1-inspired change needs a **detailed plan + explicit approval before coding**
(code must be adapted to this repo, not copied verbatim — see the Q-factor example above):
- **Tracking safety (auto-disable / auto-resume)**: disable auto-tracking after N consecutive
  sweeps with the peak lost, auto-resume when it returns. Backend = a `_consecutive_edge_errors`
  counter in the acquisition process + tracking events on a parser queue + Worker→GUI notifications
  (Q-1: disable after 10, resume after 5). Builds on the disconnected-sensor guard (same `_err`
  pipeline). GUI status-bar notification part deferred.
- **Peak-detection validations**: validate the fundamental is a plausible QCM frequency
  (4-6 / 9-11 MHz), flag when all expected overtones are zero, auto-detect QCM type (5/10 MHz),
  tune the magnitude/phase cross-validation threshold. Two-phase detection already exists in
  `processors/Calibration.py` (`peak_detection_qcm_fundamental` / `..._overtones`).
- **Windows serial anti-jitter**: add `sleep(0.001)` inside the `inWaiting()` read loop
  (`Serial.py:826`, currently a tight busy-wait) to reduce Windows scheduler jitter.
- **Minor / defensive**: `FileManager.create_dir(None)` raises `TypeError`; `file_exists(None)`
  returns `None`. `Constants.environment = 50` for production (currently `10`, development).

Later (GUI / firmware / packaging — deferred): UI (System Log tab, measurement cursors, light
theme, overtone quick-select); packaging (`common/resources.py` + hardcoded-icon fix, PyInstaller);
cross-platform validation; merge the impedance feature once stable (make the conductance method
selectable).

## 6. Conventions and gotchas

- **PyQt5 = 5.9.2 is mandatory**: the GUI uses the classic `QtGui` widget namespace
  (`QtGui.QMainWindow`, `QtGui.QPushButton`…); PyQt5 ≥5.11 moves widgets to `QtWidgets` and breaks the
  app.
  ⚠️ **And `QtGui` does not actually contain those widgets** — not even in 5.9.2. It works because
  pyqtgraph's `Qt.py` copies every `QtWidgets` member into `QtGui` for Qt4 compatibility (line 299 of
  0.11.0), and `mainWindow.py` imports pyqtgraph *before* `QtGui`. Measured: `QtGui.QFileDialog` is
  `False` before importing pyqtgraph and `True` after. So every widget reached through `QtGui` in that
  file works **by side effect of a third-party import**. It already cost one traceback in production
  (`File > Open Log`, fixed in `badd438`). In new code import from `QtWidgets` explicitly. **Python 3.9.12**. Tested on macOS Intel and Apple Silicon. Conda is the reproducible route
  (see `software/environment.yml`).
- ⚠️ **A QSS property selector is evaluated at polish time, not continuously.**
  `QGroupBox[cardCompact="true"]` in `theme.qss` lets a card opt into the compact look without this
  file knowing its object name — useful for widgets built on a branch. But `setProperty` after the
  style sheet has been applied changes nothing on screen: set it in the builder (which runs at
  `setupUi()`, before `_apply_theme()`), or call `style().unpolish(w)` then `polish(w)`. Qt maps a
  Python `True` to the string `"true"` the selector matches.

- **Runtime-rewritten data files.** Only three are still tracked: `PeakFrequencies.txt`,
  `PeakFrequenciesRT.txt` and `config.txt`. `Calibration_5MHz/10MHz.txt` and `sweep_data/*.txt` were
  untracked on 2026-07-28/29 and are regenerated by Peak Detection and by an acquisition; the
  PeakFrequencies pair had to **stay** versioned, because `load_frequencies_file()` reads them while
  the window is being built and the only thing that writes them is a button inside that window, so a
  clone without them does not start. Same reason for `config.txt` (`loadtxt` at start-up in both
  `MultiscanProcess` and `SerialProcess`). Mark the tracked ones **`skip-worktree`** on each machine
  so runtime rewrites do not pollute git — a **local, per-clone** setting:

  ```bash
  git update-index --skip-worktree software/openQCM/PeakFrequencies.txt software/openQCM/PeakFrequenciesRT.txt
  ```

  ⚠️ Untracking a file **deletes it** on every other clone that pulls; `.gitignore` does not protect
  an already-tracked file. Before untracking anything, ask what reads it. And if you ever see the
  three symptoms together — clean `git status`, `git checkout --` saying "did not match any file(s)
  known to git", and a merge complaining about local modifications to those same files — that is the
  `skip-worktree` bit: diagnose with `git ls-files -v | grep ^S`.

- â ï¸ **Mixed line endings, and no `.gitattributes`.** 42 `.py` files are LF and five are CRLF
  (`fileStorage`, `switcher`, `Sigma_Clip`, `ReadLine`, `Calibration`). Two consequences. **On
  Windows**, set `git config --global core.autocrlf false` *before cloning*, or git rewrites every
  file at checkout and the clone looks entirely modified. **When editing with a script**, read and
  write in binary: `open(p).read()` uses universal newlines and `write()` emits `'\n'`, which
  silently converts a CRLF file whole â it happened in `8c40c58` and had to be undone in `da81e2b`,
  where a two-line change arrived as a 1598-line diff. Normalising all five is a reasonable decision
  to take deliberately; it has not been taken.
- **The GUI *can* be exercised headless** — the old "leave it all to a human" is only half true, and
  the difference matters because logic bugs are cheap to catch this way. Static checks first
  (`python -m py_compile ...`, `python -c "from openQCM.app import OPENQCM"` from `software/`), then
  drive real widgets under `QT_QPA_PLATFORM=offscreen`: build `Ui_MainWindow` on a bare
  `QMainWindow`, or instantiate a dialog against a stub host and call its refresh directly (this is
  how Raw Data View's bands, worker re-resolution, one-shot framing and closed-dialog behaviour were
  verified before any on-device run). Three traps, all found the hard way:
  - **hold the `QApplication` in a name.** `QApplication.instance() or QApplication([])` as a bare
    expression leaves it unreferenced, it is collected at once, and the process segfaults with no
    output at all — buffered stdout dies with it, so it looks like the script did nothing.
  - **do not call `show()`** on the dialog; it segfaults offscreen. Capture with pyqtgraph's
    `ImageExporter` on `canvas.scene()` instead, which needs no visible window.
  - **do not re-import two copies of `openQCM`** from different trees into one Qt process; it
    segfaults. Use a subprocess per tree.
  Fonts are missing offscreen (`QFontDatabase: Cannot find font directory`), so rendered captures
  have no text — expected, not a bug. The on-device smoke test still belongs to a human.
- ⚠️ **A `QMessageBox` window title is discarded on macOS.** Measured: `setWindowTitle("FIRMWARE
  UPDATE")` followed by `windowTitle()` returns `''` — **before** `show()`, so it is not the
  platform plugin, it is Qt applying the macOS convention that an alert has no title. Every
  `PopUp.*` call in this application passes a title, and on macOS **none of them is displayed**.
  The consequence is a rule, not a curiosity: the *message* has to carry everything the operator
  needs, because the word that would have named the dialog is not on screen. Do not fix this by
  putting the title back — it cannot be put back; put it in the text.

- **Every change goes into `CHANGELOG.md`** (unless explicitly told not to, e.g. a fix that just
  restores pre-existing behavior); keep the **README** aligned with substantial changes. Commits use
  Conventional Commits + a `Co-Authored-By` trailer.
- Propose a plan and wait for approval before invasive changes.
