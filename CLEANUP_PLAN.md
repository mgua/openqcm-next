# CLEANUP_PLAN — openQCM NEXT source-code cleanup

> Work plan for a **future execution session**. Produced by a read-only audit
> (4 parallel analysis agents + `pyflakes` + `grep`, nothing modified).
> Goal: remove dead code, unused structures, dead comments and redundancies with
> **zero behavior change**. Working language: Italian in chat, English in the repo.
> Generated: 2026-07-20. Baseline: `main` @ 630e898, working tree clean.
> ⚠️ Executed only in part since (dead Qt-Designer UI files `d23333e`, `data_view/`, the hidden
> `tab_2` `51034e8`): re-check every item against HEAD before acting on it (note of 2026-10-01).

---

## 0. Scope, constraints, verification protocol

**In scope:** the Python application under `software/` only.
**Out of scope:** Arduino firmware (`firmware/`), `research/`, and any structural
*refactor* (see §7 — the Serial/Multiscan duplication is documented, not to be
consolidated in a cleanup pass).

**Hard rule:** cleanup must not change runtime behavior. Prefer deletion of proven-dead
code; when confidence is medium, verify before removing (see the per-item confidence tags).

**Cautions specific to this codebase:**
- **PyQt5 5.9.2, classic `QtGui` namespace** — do not "modernize" imports.
- **Qt indirection**: methods may be reached via `.connect(...)`, objectName, or as Qt
  overrides (`closeEvent`, `eventFilter`, …). Never delete a method without grepping its
  name (as a string too) across all of `software/`.
- **Multiprocessing**: `Constants` are read across processes; a constant unused in one
  file may be consumed by another. Every "unused constant" below was grep-checked
  tree-wide, but re-confirm before deleting.
- **UI builder contract**: `ui/mainWindow_ui.py` intentionally keeps some widgets alive
  and hidden (`pButton_Stop`, `pButton_Reference_Not`, `l1`, `info11`, `line*`). These are **not**
  dead — the controller uses them. Leave them. (The hidden `tab_2` PID block was in this list;
  it was removed in `51034e8`, 2026-09-08.)
- **GUI testing headless is limited.** Windows can be built and fed offscreen (HANDOFF §6), but
  the tabbed windows must not be shown; after each phase run the static checks below and leave
  the on-device smoke test to a human at the end.

**Suggested workflow:**
- Dedicated branch `chore/source-cleanup`; atomic commits per phase/file
  (Conventional Commits + `Co-Authored-By` trailer).
- After **every** phase, from `software/`:
  ```bash
  python -m py_compile $(git ls-files '*.py')
  python -c "from openQCM.app import OPENQCM"
  python -m pyflakes openQCM run.py   # regression: count should only go down
  ```
- Recommended order: **Phase 1 → 2 → 3 → 4 → 5** (zero-risk first).
- Update `CHANGELOG.md`; keep `README.md`/`HANDOFF.md` aligned if structure changes
  (e.g. the repo-structure tree lists `mainWindow_new_ui.py`).
- On-device smoke test at the end (include the grid toggle — see §6 bug #1).

**Headline:** ~4,500–5,000 lines removable out of 17,080 (~28%).

---

## Phase 1 — Whole dead files (zero risk; verified: zero importers)

Confirmed by grep across all of `software/`: no `import`/`from` pulls these in
(`res/` isn't even a package — no `__init__.py`).

| File | LOC | Action / coupling to remove with it |
|---|---|---|
| `software/openQCM/ui/mainWindow_new_ui.py` | 857 | Old pyuic5 `Ui_MainWindow` (from an absent `.ui`). Active builder is `ui/mainWindow_ui.py`. |
| `software/openQCM/res/mainWindow_new_ui.py` | 796 | Second generated copy. |
| `software/openQCM/res/mainWindow_new.ui` | (XML) | Designer source for the dead module; no `loadUi` consumes it. |
| `software/openQCM/res/README.txt` | — | Only documents regenerating the dead file. |
| `software/openQCM/processors/Sigma_Clip.py` | 556 | Vendored astropy `SigmaClip`, never imported (has a latent broken `from utils import isiterable`). |
| `software/openQCM/processors/SocketClient.py` | 99 | `SocketProcess` imported once at `core/worker.py:6`, never used. **Also remove** that import **and** the nested `class SocketClient` in `constants.py:707-712` (`#unused`). |
| `software/openQCM/processors/Simulator.py` | 84 | `SimulatorProcess` never imported. **Also remove** `constants.py:527 simulator_default_speed`. |
| `software/openQCM/util/embedding_in_qt_sgskip.py` | 71 | `ApplicationWindow` imported at `ui/mainWindow.py:46`, used only in commented `:346`. **Also remove** that import + commented use. |

After Phase 1: update the Repository-Structure tree in `README.md` (it lists
`mainWindow_new_ui.py`).

---

## Phase 2 — Unused imports (zero risk)

`pyflakes` baseline: **44 "imported but unused" + 9 star imports.** Full list from the
audit (all HIGH confidence unless noted):

**Processors**
- `Serial.py:14` `ReadLine as rl`; `:15` `time as tm`; `:16` `progressbar` (Bar, Percentage, ProgressBar, RotatingMarker, Timer).
- `Multiscan.py:6` `Overtone_Switcher_5MHz/10MHz`; `:15` `progressbar` (×5); `:17` `ReadLine as rl`; `:21` `from numpy import loadtxt` (**duplicate** of `:11`).
- `Calibration.py:5` `Logger as Log`; `:8` `progressbar` (×5); `:14` `numpy.loadtxt`; plus commented imports `:7`, `:16-17`.
- `Parser.py:2` `Logger as Log` (fully unused once the two commented `run()` blocks go — see Phase 3).

**Core / common / app**
- `worker.py:6` `SocketProcess` (goes with Phase 1); `:23` `#import pywt` (commented).
- `constants.py:5` `import time` (used only in the commented DateAxis block).
- `common/fileStorage.py:6` `import datetime` (only in commented `:50`).
- `app.py:15` `Constants` (used only in commented `:67`; keep `MinimalPython`).
- `common/switcher.py:3` `TAG` module var — never referenced.

**UI**
- `mainWindow.py:11` `pyqtgraph.AxisItem`; `:24` `SerialProcess`; `:29` `Architecture, OSType`; `:46` `ApplicationWindow` (goes with Phase 1).

**data_view / sweep_data**
- `data_view/main.py:2` `loadUi`; `:7` `random`; `:10` `time`; `:13` `QWidget, QInputDialog, QLineEdit`; `:14` `QIcon`; `:16` `QTextEdit`. Note line 1 is `from PyQt5.QtWidgets import *`, so the explicit QtWidgets imports are redundant regardless.
- `plot_sweep_spline.py:29` `tkinter as Tk`; `:30` `math`; `:33` `InterpolatedUnivariateSpline`.
- `data_view/qt_designer_ui.py:9` `PyQt5.QtGui`.

**Star imports (optional sub-step, slightly more than removal):** `data_view/main.py:1`
and `data_view/mplwidget.py` use `from PyQt5.QtWidgets import *`. Converting to explicit
imports is a nice-to-have; if done, it must list every used name — otherwise leave as-is.

---

## Phase 3 — Commented-out dead code (zero risk; ~2,000 lines)

The largest surface. Remove Spyder fold blocks (`# ===...===`), triple-quoted dead code,
and commented `print`/`plot`/old-algorithm lines. Behavior unchanged (it's all inert).

### `ui/mainWindow.py` (~1,300–1,500 commented lines; ~110 fold blocks + ~24 triple-quoted)
Representative ranges (all HIGH):
- `344-350` `#DEV RAWDATA` ApplicationWindow init; `366-370` old firmware call; `374-376` `dummy` connect; `456-459` console-clear; `468-471`, `1493-1496` OFF-button enable.
- `543-560, 623-638, 654-674, 692-714` old legend/plot in `start()`; `825-871` old `stop()` clear.
- `878-904` `temperatureSet` docstring holding the old `_my_serial` impl; `1312-1352` old `get_firmware_version`; `1365-1376` OS-separator branch.
- `1790-1841, 1856-1973` phase-plot (`_plt1`) / multi-window setup; `2265-2286` `_configure_signals` dead connects; `2319-2325` `_log_data_plot` bootstrap.
- **`2793-3822`** the big one — commented `plot()/setYRange/updateViews/clear` across all `_update_plot` branches (~700 lines).
- `4083-4094` `_getLabel`; `4329-4361, 4383-4389` `ControlsWin.ui1` blocks; `4454-4483` clear tails; `4489-4518` old `reference()`; `4553-4633` reference/autorange snippets; `4673-4768` legacy `get_web_info` scrape.

### `processors/Multiscan.py` (~60 regions)
- `134-155, 167-240, 285-312` `parameters_finder` algorithm-history banners; `372-471` `elaborate_multi` call variants; `480-487` `elaborate_ampli_phase_multi` head.
- **`745-1276`** largest concentration — commented DEBUG / exception-handler / raw-save blocks in `run()`.
- `1418-1431, 1522-1525, 1770-1776` switch/peaks/`len==5/3` blocks.

### `processors/Serial.py`
- `141-161` VER-history banners; `172-314` old algorithm variants in `parameters_finder`; `373-462` dead debug/append in `elaborate`; `485-518` CSV-dump triple-quotes + `np.savetxt`.
- `715-1079` scattered DEBUG/print blocks in `run()`; `1220-1234` port-inspection prints; `1298-1325, 1517-1523` `len==5/3` blocks; `1100-1103` reset print; `1539-1541` trailing `#a=SerialProcess()`.

### `processors/Calibration.py`
- `324-337` `_QCStype` map; `364-367` freq init; `435-460` ProgressBar; `526-531` `add6` variants; `557-579` early baseline / path-selection; `586-685` print/history; `797-799` trailing `#a=CalibrationProcess()`.

### `processors/Parser.py`
- `136-155` and `157-207` — two entire commented-out `run()` implementations (reference attrs that don't exist on the class); `55-56, 133-134` debug lines.

### `core/worker.py`
- `75-80` buffer init; `183-185` print; `207-210` old `ParserProcess` sig; **`243-277`** big "DATA/CALIBRATION MAIN INFORMATION" print blocks; `333-336` stop calls; `470-478` TIME prints; `553-555` `'''self.store_data_calibration()'''` (method doesn't exist); `749-821` store_data prints + `CSVsave_Multi` variants; `997-1001, 1044-1046`.

### `core/constants.py` (~110 lines in two big blocks)
- `54-62, 86-88, 143-145, 219-243, 485-507, 545-550, 638-661` old value variants.
- **`282-348`** old per-overtone 5 MHz params (~67 lines); **`716-761`** old `DateAxis` class (~46 lines; live one is `767-800`); `607-631` dead path/debug_file block.

### `app.py`
- `36-47` win32gui console block; `67-70` setWindowTitle/move/show.

### `sweep_data/plot_sweep_spline.py`
- `4-13` fake-docstring code snippet; `18-20` matplotlib import; `121-133` old `get_left_index`; `165-180`; `251-315` plt debug; scattered commented `print`/`axs.plot`/`plt.style` at `405-732` (see audit for the full list); `473, 593, 751` dark-bg.

### `data_view/main.py` + `mplwidget.py`
- `main.py:394, 523-525, 584-600`; `mplwidget.py:17`.

### `ui/popUp.py`
- `26-32, 67-70, 159-162, 197-200, 263`.

---

## Phase 4 — Structural dead code (low risk)

### Dead methods (never called; grep-confirmed)
| Symbol | Location | Conf |
|---|---|---|
| `waveletSmooth` (nested in `elaborate`) | `Serial.py:329-341` | high |
| `_TempCtrl` | `Serial.py:1091-1095` | high |
| `_TempCtrl` | `Multiscan.py:1286-1290` | high |
| `get_sweep_parameters` (no `self`) | `Multiscan.py:1791-1794` | high |
| `FindPeak` (+ its 6 attrs `max_indexes_*`, `max_freq_*`, `max_value_*`) | `Calibration.py:85-100` | high |
| `setColumnCount` + nested `_addItemToLayout` | `mainWindow.py:411-440` | high |
| `clear_all_plot` | `mainWindow.py:4401-4408` | high |
| `start_download` (uses never-assigned `self._webinfo`) | `mainWindow.py:4773-4776` | high |
| `dummy` | `mainWindow.py:4778-4779` | high |
| `question_QCM` (docstring says "(unused)") | `popUp.py:18-54` | high |
| `info_not_blocking` | `popUp.py:214-228` | med |
| `get_Temperature_set_Worker` (`#TODO DELETE`) | `worker.py:377` | high |
| `my_stop` (`#TODO DELETE`) | `worker.py:382` | high |
| `serial_write` (`#TODO DELETE`) | `worker.py:386` | high |
| `get_overtone` (+ orphaned `_overtone_value`) | `worker.py:1064` | high |
| `CSV_sweeps_save` (only commented caller) | `common/fileStorage.py:137` | high |

Do **not** touch (verified live via callers/signals): all Qt overrides & slots,
`load_frequencies_file`, `_update_legend_single`, `_cursor_series`, `internet_on`,
`get_web_info`, `_reacquire_serial_lock`, `_run_firmware_updater`, `write` (Serial→worker:388),
`get_Temperature_set_Serial`, `get_freq_range_RT`, `get_readFREQ`, `get_frequencies*`.

### Dead attributes (assigned, never read)
- **Serial.py:** `_filtered_mag` (355), `_dummy` (546), `Temperature_Pid_default` (554-561, assigned twice), `_flag_error` (689/1045/1052).
- **Multiscan.py:** `_filtered_mag` (340), `_dummy` (523), `Temperature_Pid_default` (531-538), `_flag_error` (722/1216/1225), the non-suffixed `_frequency_buffer`/`_dissipation_buffer`/`_temperature_buffer` (784-786), `_temperature_buffer_1..4` (566-576), `_frequency_buffer_*_a` + `_my_list_f_a` (578-587), `_boolean_buffer_length` (818/1267). **Keep** `_frequency_buffer_1..4`/`_dissipation_buffer_1..4` (used via `_my_list_f`/`_my_list_d`) and `_temperature_buffer_0`.
- **Calibration.py:** `_QCStype_int` (664/690, med — keep the `_QCStype` string); redundant double `_flag2=0` (358/405, low).
- **mainWindow.py:** `_my_serial` (317), 6 ring buffers `_frequency_buffer`/`_1`/`_2` + `_dissipation_buffer`/`_1`/`_2` (320-327), `_arr` (664), `_plt1` (180 — see §6 bug #1), `_plt1_line` (190), `_labelref1/2` (509-510). **Medium (verify on-device first):** `_vector_reference_frequency/_dissipation` (read only in commented code), `_ser_err_usb` (tuple-unpacked; every read commented), `_QCS_installed`/`_QCS_on` (effectively constant `None`; passed to `Worker` — confirm the worker doesn't need it).
- **worker.py:** `_t1/_t2/_t3_store` (560/569/582, `#time (unused)`), `_data_current_tec` scalar (617), `_readFREQ_array` (150), `_A_multi`/`_P_multi` (72/73), `_queue_F_SWEEP_multi` (69, created never consumed), `_number_of_peaks` (med), `_overtone_value` (with `get_overtone`).

### Dead local variables (~50; from `pyflakes`, cross-checked)
- **plot_sweep_spline.py:** `foo()` (37-38, dead fn), `phs_1/3/5/7/9_a`, `sg_order`, `frq_a_sp`, `frq_1..9_a_min`, `amp_a_sp_min`, `frq_a_left/right`, `num_peaks`, `phs_n_a`, `amp_1_n_baseline`, `frq_n_a_min`, `amp_n_sp_min`.
- **data_view/main.py:** the `f_4_hadamard*` / `f_4_hadamard*_l` cluster (368-374 & 461-467) — computed, never displayed (see §6 bug #3).
- **mainWindow.py:** `pre_stop_flag` (2522), `byte_at_port` (1195), `labelweb3` (4712); no-op `if/else` in `_enable_ui` (1441-1445, both branches identical).
- **Processors:** `f_min`/`i_min` (Serial & Multiscan `parameters_finder`, used only in comments), `frequencies_file_length` (Multiscan 742/762), `freq_difference` (Calibration 143), plus the assorted `local ... never used` from the pyflakes report.

### Unused constants (`constants.py`, grep-confirmed HIGH)
`plot_max_lines` (84), `plot_color_temperature` (103), `overtone_maximum_number` (263),
`null_string` (501), `process_join_timeout_ms` (526), `parser_timeout_ms` (528),
`log_default_level` (537), `csv_delimiter` (569), `csv_default_prefix` (570 — note
`worker.py:304` hardcodes the same literal instead), `SG_order_environment` (697),
`SG_window_environment` (698). Plus the effectively-dead `simulator_default_speed` (527)
and nested `class SocketClient` (707-712) removed in Phase 1.
**Do NOT remove** the L5/R5/L10/R10/`SG_window_size*`/`Spline_factor*` family — read by
`common/switcher.py` (see §7 note).

---

## Phase 5 — Stale comments / banners / done TODOs (zero risk)

- Empty `TAG = ""#"[...]"` remnants: `Serial.py:22`, `Multiscan.py:26`, `Calibration.py:20`,
  `Parser.py:5`, `worker.py:25`, `fileStorage.py:10`, `arguments.py:8`, `app.py:18`,
  `mainWindow.py:52`, `switcher.py:3`.
- `# VER 0.1.x` changelog banners scattered in worker/constants/processors — noise.
- mainWindow: ~93 `TODO` + ~12 `#DEV/DEBUG`, many done/abandoned (e.g. `_plt3` that never
  existed at 182-184; `# TODO delete` at 274-275/466-473/1466-1467/2231-2232;
  `#DEBUG check the stop flag` above the dead `pre_stop_flag`).
- `popUp.py` mismatched `###` banners: `warning_exec` (137) & `critical_exec` (175) say
  "question dialog…"; `info_not_blocking` (211) says "warning dialog"; `info_not_blocking_rtf`
  (250) says "info dialog with a Ok buttons".
- Misleading `constants.py:79` `# ...(unused)` on the live `plot_colors`; correct/refresh.
- `Parser.py`/`Calibration.py`/`Serial.py`/`Multiscan.py` inaccurate copied class banners.

---

## 6. Bugs found during the audit (NOT cleanup — decide separately)

These are real defects surfaced while reading; listed so they aren't lost. Handle as
fixes (own commits / own decision), not silently folded into cleanup — except #1, which is
naturally resolved when `_plt1` is removed.

1. **`mainWindow.py:4186`** — `_toggle_grid` does `self._plt1.showGrid(...)` when
   `plot is self._plt0`, but `_plt1` is permanently `None` (its assignment at 1805 is
   inside a dead triple-quoted block). Toggling the amplitude/sweep plot grid via
   right-click → `AttributeError`. **Confirmed.** Fix: drop the `_plt1` branch when
   removing `_plt1`. Verify on-device (right-click the top plot → Show/Hide grid).
2. **`Serial.py:495`** — `Constants.csv_default_filename` is **not defined** anywhere →
   `AttributeError` if that CSV-writer path runs. **Confirmed.**
3. **`data_view/main.py:511,519`** — 9th overtone printed as `f_3_hadamard/9.0` (should be
   `f_4_hadamard`, which is exactly the dead computation in Phase 4).
4. **`plot_sweep_spline.py:151`** — `len(signal-1)` should be `len(signal)-1`.

---

## 7. Structural duplication (documented; NOT for the cleanup pass)

`Serial.py` (`SerialProcess`) and `Multiscan.py` (`MultiscanProcess`) are **~80% identical**
— Multiscan is the per-overtone-loop generalization of Serial. Line-for-line duplicates:
`parameters_finder`, `savitzky_golay`, `baseline_correction`/`baseline_coeffs`,
`load_frequencies_file`/`load_calibration_file`, `get_ports`/`_is_port_available`/`get_speeds`
(a 3rd copy in `Calibration.py`), `set_frequencies_RT`/`stop`/`_Temperature_PID_control`,
and the serial sweep read-loop (ADC decode / EOM / MTD415T bit-decode / TEC "A"). The
`self._parserN = ... = parser_process` aliasing is a redundant façade over one
`ParserProcess`. The `L5/R5/…/Spline_factor*` per-overtone constants are all set to the
same base value (per-overtone distinction no longer exists) — collapsible but **live**
(switcher reads them). Also within mainWindow: `_update_indicator_F/_D` vs their `_single`
variants, the four `_update_plot` branches, the firmware-prompt cascade.

**Consolidating these is a refactor** (behavior-preserving but invasive) — propose it as a
separate, approved task, not part of this cleanup.

---

## 8. Files essentially clean (no action)
`data_view/qt_designer_ui.py` (generated, live), `data_view/mplwidget.py` (live, 1
commented line), `ui/mainWindow_ui.py` (active hand-written builder — intentional hidden
widgets), `ui/theme.py`, `core/ringBuffer.py` (only debug-only `get_partial`/`__repr__`,
low value), `run.py`, `__main__.py`.
