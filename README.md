# openQCM NEXT

**Real-time Python GUI software for the openQCM NEXT Quartz Crystal Microbalance with Dissipation monitoring**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

An open-source Python application to display, process, and store data in real-time from the openQCM NEXT Quartz Crystal Microbalance with Dissipation monitoring. The software tracks resonance frequency and dissipation variations through real-time analysis of the resonance curve, driving a **Teensy 4.0** microcontroller and an **AD8302** gain/phase detector over USB.

> This repository is a monorepo (software + firmware + docs) with a **reconstructed development history**: the chronology is expressed through commits and tags.

---

## Table of Contents

- [About QCM Technology](#about-qcm-technology)
- [Quick Start](#quick-start)
- [Features](#features)
  - [Acquisition and Operating Modes](#acquisition-and-operating-modes)
  - [Visualization and Analysis](#visualization-and-analysis)
  - [Hardware Integration](#hardware-integration)
  - [User Interface](#user-interface)
- [Installation](#installation)
- [Usage](#usage)
- [Repository Structure](#repository-structure)
- [Architecture](#architecture)
- [Branches and Version History](#branches-and-version-history)
- [Roadmap](#roadmap)
- [License](#license)
- [Acknowledgements](#acknowledgements)
- [Links](#links)

---

## About QCM Technology

A **Quartz Crystal Microbalance (QCM)** measures mass changes and material properties at the nanoscale by monitoring the oscillation of a quartz crystal. When mass is deposited on the crystal surface, the resonance frequency shifts; by tracking frequency and dissipation simultaneously, the technique reveals both the amount of adsorbed material and its viscoelastic properties at the molecular scale.

**[openQCM](https://openqcm.com/)** is an open-hardware initiative — powered by Novaetech S.r.l. — built on the principle that high-quality research does not require expensive proprietary instruments.

**openQCM NEXT** is a QCM instrument for frequency and dissipation monitoring with multiple-overtone support (fundamental and n = 3, 5, 7, 9). It couples an **AD8302** RF/IF gain and phase detector with a frequency sweep driven by a **Teensy 4.0** microcontroller, and connects to the host over a plug-and-play USB serial link. Applications include protein biosensing, bacteria detection, drug discovery, material science, environmental monitoring, and electrochemistry.

---

## Quick Start

1. Connect the openQCM NEXT device via USB.
2. Install the Python dependencies (see [Installation](#installation)).
3. Launch the application:

   ```bash
   cd software
   python run.py          # or: python -m openQCM
   ```

4. In the GUI, click **Refresh** to scan for connected devices, select the serial port, and click **Connect**.
5. Run **Peak Detection** — the QCM type (5/10 MHz) is auto-detected.
6. Select the desired overtone (F0, F3, F5, F7, or F9) and click **Start** (enabled once connected).

> **Note on `software/openQCM/config.txt`.** The application rewrites it, and its contents are
> per-machine, so it shows up as a local modification on every working copy. It is tracked on
> purpose — it is read with `loadtxt` at start-up, so a clone without it will not run — which means
> `git pull` refuses until the change is put aside: `git stash push software/openQCM/config.txt`,
> pull, then `git stash pop`.

---

## Features

### Acquisition and Operating Modes

**Real-time data acquisition**

- Serial connection to the openQCM NEXT device (Teensy 4.0) with automatic port detection
- Multiprocessing architecture for non-blocking acquisition and UI rendering
- Support for **5 MHz** and **10 MHz** quartz crystal sensors
- Multiple overtones: fundamental, 3rd, 5th, 7th, 9th

**Operating modes**

- **Peak Detection** — Automatic identification of resonance peaks across the frequency spectrum, with QCM type auto-detection (5/10 MHz) and phase cross-validation.
- **Single Measurement** — Single-overtone frequency sweep with real-time resonance frequency and dissipation tracking.
- **Multiscan Measurement** — Sequential multi-overtone acquisition.

**Data logging**

- Automatic CSV export with timestamped filenames
- Single-measurement columns: `Date`, `Time`, `Relative_time`, `Temperature`, `Resonance_Frequency`, `Dissipation`
- Multi-overtone export with per-overtone frequency/dissipation columns

### Visualization and Analysis

- **Resonance Frequency** and **Dissipation** time-series plots, each with a **readout card** above
  it showing the live per-overtone values (F0/F3/F5/F7/F9 · D0/D3/D5/D7/D9) with color swatches
- **Amplitude / Phase** frequency sweep and **Temperature** plots in a **collapsible** top pane
  (hide them to give the frequency/dissipation plots the full height)
- **Temperature** monitoring, with a dedicated **TEC current** window
- **Light / dark theme** (toggle from *View → Theme* or the menu-bar corner button), high-performance
  real-time plotting via PyQtGraph (`setData`, 50 ms refresh)
- Per-plot **right-click menu** (auto-scale, reset zoom, pan/select, grid toggle), an **Autoscale**
  button (X+Y on all plots), and **Δ cursors** (Δt / ΔF / ΔD) on the frequency and dissipation plots
- **Raw Data View** — live visualization of the current sweep (Savitzky-Golay filtered points, spline fit, peak marker, bandwidth region)
- **Log Data View** — load and visualize previously recorded CSV files (single and multi-overtone formats)

**Peak detection algorithm**

Two-phase detection:

1. **Fundamental detection** — scans the frequency range to locate the fundamental peak with `scipy.signal.argrelextrema`, then auto-detects the QCM type (5 or 10 MHz).
2. **Overtone detection** — searches for odd harmonics (3rd, 5th, 7th, 9th) around expected positions, with phase cross-validation (peaks are discarded when the magnitude/phase frequency mismatch or a low phase amplitude indicates a false positive).

A legacy `FindPeak` routine remains available as a fallback.

### Hardware Integration

- **Teensy 4.0** microcontroller firmware (see [`firmware/`](firmware/)); USB-CDC serial link at 115200 baud, 8N1
- Frequency sweep command protocol (`start;stop;step`) with a magnitude/phase ADC data stream, and
  single-letter commands beside it: `F` firmware version, `S` machine identification number,
  `Q` end the sweep in progress, plus the TEC set
- **Machine identification number** stored in the Teensy EEPROM, written once per board by
  `firmware/openQCM_Next_SerialNumber/` and read back by the software (Tools → Check Board Serial
  Number). Format `SSNN`, one compact integer: series 19 unit 20 is `1920`. Verified on hardware
  across every case — a programmed board, an unwritten EEPROM (`NO_SERIAL`), and a firmware too old
  to know the command
- **TEC (thermo-electric) current monitoring** and temperature/PID control commands
- Bundled platform-specific firmware update tools (Teensy Loader for macOS/Windows) under [`software/openQCM/firmware_update/`](software/openQCM/firmware_update/)

### User Interface

- **Single-window layout**: a collapsible, scrollable **sidebar of control cards** (Connection,
  Measurement Setup, Temperature, Plot Controls) and a **center tab area** with a **Plots** tab and
  a **System Log** tab (mirrors the program's stdout/stderr with timestamps)
- **Light / dark theme** (persisted between launches; toggle via *View → Theme* or the menu-bar
  corner button)
- Explicit **Connect / Disconnect** and **Refresh** controls: the serial connection is a separate
  step (with a per-port lock against multiple instances), and **Start** is enabled only once connected
- Single **Start / Stop toggle** button (▷ play / □ stop glyphs; blue when idle, brown while running)
- Single **temperature ON / OFF toggle** (blue to enable, brown to disable; enabled once connected),
  with a settable setpoint (**T SET**) and a live temperature readout
- **Overtone quick-select** chips (F0/F3/F5/F7/F9): pick the measured overtone in single mode, or
  highlight traces in multiscan; the **frequency selector** is shown only in *Single Measurement*
- **Plot Controls** card: **AUTO** · **SET REF / UNSET REF** (toggle) · **CLEAR**
- Consistent lightweight **"secondary" button style** (blue outline, brown for the "deactivate"
  state, grey when disabled) sized to fit each label, and **bold card titles**
- **Bottom status bar**: program state, message, live F/D/T/S readings and the progress bar
- Real-time datalog **filename indicator** (sidebar + window title) during acquisition

---

## Installation

### Requirements

- Python 3.9
- An openQCM NEXT device connected via USB

### Recommended: conda environment (reproducible)

```bash
cd software
conda env create -f environment.yml
conda activate openqcm-next
python run.py
```

### Alternative: pip

```bash
cd software
pip install -r requirements.txt
```

> **Note:** PyQt5 is pinned to **5.9.2** — the GUI uses the classic `QtGui` widget
> namespace, and newer PyQt5 (≥5.11) moves widgets to `QtWidgets` and would break it.
> On modern systems (including Apple Silicon) the conda environment is the more
> reliable route; pip may not find PyQt5 5.9.2.

### Linux — serial port permissions

On Linux, grant your user access to the serial port:

```bash
sudo usermod -a -G dialout $USER
sudo usermod -a -G uucp $USER
```

Log out and back in for the change to take effect.

---

## Usage

```bash
cd software
python run.py          # or: python -m openQCM
```

---

## Repository Structure

```text
openqcm-next/
├── software/                                  # Python application
│   ├── run.py                                 # entry point (thin launcher)
│   ├── environment.yml · requirements.txt     # conda / pip dependencies
│   ├── openQCM/                               # main package
│   │   ├── __main__.py · app.py               # `python -m openQCM`, OPENQCM bootstrap
│   │   ├── core/
│   │   │   ├── worker.py                      # queues, processes, ring buffers, datalog writer
│   │   │   ├── constants.py                   # configuration parameters and tunables
│   │   │   ├── resonance.py                   # peak detection, dissipation band, filtering chain
│   │   │   ├── averaging.py                   # robust averaging of the ring buffers
│   │   │   ├── logAnalysis.py                 # two-window statistics over a logged run
│   │   │   └── ringBuffer.py                  # circular buffer for time series
│   │   ├── processors/
│   │   │   ├── Multiscan.py                   # multi-overtone acquisition and processing
│   │   │   ├── Serial.py                      # single-overtone acquisition
│   │   │   ├── Calibration.py                 # peak detection
│   │   │   ├── Parser.py                      # holds the multiprocessing queues
│   │   │   └── Sigma_Clip.py · Simulator.py · SocketClient.py
│   │   ├── common/
│   │   │   ├── fileStorage.py                 # CSV datalog
│   │   │   ├── tecStatus.py · tecReset.py · pidQuery.py   # TEC controller (MTD415T) over serial
│   │   │   ├── sweepDump.py                   # raw sweep dump (development only)
│   │   │   └── architecture.py · arguments.py · fdLimit.py · fileManager.py · logger.py · switcher.py
│   │   ├── ui/
│   │   │   ├── mainWindow.py · mainWindow_ui.py   # main window: controller and programmatic layout
│   │   │   ├── rawDataView.py · peakDataView.py · dataLogView.py   # data views
│   │   │   ├── pidControlDialog.py · tecCurrentView.py             # TEC windows
│   │   │   └── theme.py · widgets.py · plotMenu.py · popUp.py
│   │   ├── sweep_data/                        # Raw Data View plotting; sweep files are runtime
│   │   │   └── plot_sweep_spline.py
│   │   ├── util/                              # serial line reader, matplotlib-in-Qt helper
│   │   ├── res/ · icon/                       # icons and images
│   │   ├── firmware_update/                   # Teensy loaders (macOS, Windows) and firmware images
│   │   ├── config.txt                         # sweep / sampling parameters (per machine)
│   │   ├── PeakFrequencies.txt · PeakFrequenciesRT.txt   # detected peaks (runtime, versioned)
│   │   └── Calibration_5MHz.txt · Calibration_10MHz.txt  # peak-detection sweeps (runtime)
│   ├── *.ino.hex                              # older firmware release images
│   └── docs/                                  # sweep file format, license (GPL)
├── firmware/                                  # Teensy 4.0 sketches: 0.1.5a/b/c, -TEST variants, serial-number writer
├── research/                                  # development materials (peak-detection prototypes, notes)
├── docs/                                      # session prompt (impedance analysis on the dedicated branch)
│   └── datasheet/                             # AD8302, AD9851, AD5251/AD5252, MTD415T, Teensy 4.0
├── CHANGELOG.md · HANDOFF.md                  # history and developer notes
└── README.md
```

---

## Architecture

The application uses a **multiprocessing pipeline** to keep acquisition independent from the UI:

```text
+----------------+   Queues    +----------+   Buffers    +----------------+
| Serial process |----------->|  Worker   |------------->|   MainWindow   |
| (acquisition)  |            |           |              | (Qt event loop)|
+----------------+            +----------+               +----------------+
       |                                                         |
       v                                                         v
   USB serial                                            PyQtGraph plots
 (openQCM NEXT)                                             CSV export
```

- **Serial / Multiscan process** — reads raw ADC data, applies baseline correction, Savitzky-Golay filtering, spline interpolation, and peak/bandwidth computation.
- **Worker** — consumes the multiprocessing queues and stores data into ring buffers.
- **MainWindow** — a Qt timer (50 ms) reads the buffers and updates the plots via efficient `setData()` calls.

---

## Branches and Version History

| Tag | Branch | Highlights |
|-----|--------|-----------|
| `v0.1.5` | `main` | Production baseline (working, stable). |
| `v0.1.6-dev` | `main` | Automatic peak detection, TEC current monitoring, dark UI + high-performance real-time plotting. |
| `v0.1.6-dev-073` | `main` | GUI reorganized into an "Add-On" menu, I/O robustness, exit confirmation; firmware `0.1.5a` (POT_VALUE 240). |
| *(unreleased)* | `main` | **GUI redesign** — programmatic single-window shell: sidebar control cards, light/dark theme, Plots/System Log tabs, single Start/Stop toggle, overtone chips, per-plot frequency/dissipation readout cards, collapsible amplitude/temperature pane, plot right-click menu + Δ cursors, bottom status bar. **Robust trimmed-mean anti-outlier averaging** of the raw acquisition buffer; development plot auto-range. See `CHANGELOG.md`. |
| `v0.1.6G-test` | `impedance-analysis` | **Experimental**: impedance analysis via conductance spectrum `G(f)` derived from the AD8302 signals. |

The `impedance-analysis` branch is experimental and not merged into `main`. Its documentation lives under `docs/impedance-analysis/` on that branch.

---

## Roadmap

Selected planned work (non-exhaustive):

- GUI polish (the redesign, the scientific menu and the **PID Control** window are done): harmonise
  the remaining status colors toward the blue/brown palette, and a few minor layout refinements.
- Port selected backend improvements from the mature **openQCM Q-1** codebase: **disconnected-sensor
  detection**, **tracking safety** (auto-disable/resume), and peak-detection validations.
- Retire the superseded firmware folders (`0.1.5a`, `0.1.5b`) once no board runs them; `0.1.5c` is
  the current pair, and the no-TEC `-TEST` variant is kept while the prototype board is in use.
- Merge the `impedance-analysis` feature once stabilized (make the conductance method selectable rather than hardwired). The exact complex-impedance conductance formula is already implemented on that branch.

---

## License

This project is distributed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0). See the license text under `software/docs/`.

---

## Acknowledgements

Developed by the [openQCM Team](https://openqcm.com/) at [Novaetech S.r.l.](https://openqcm.com/), with contributions from the open-hardware community.

*Repository history reconstruction and documentation assisted by [Claude Code](https://claude.com/claude-code).*

---

## Links

- **Website**: [openqcm.com](https://openqcm.com/)
- **Repository**: [github.com/openQCM/openqcm-next](https://github.com/openQCM/openqcm-next)
- **Contact**: [info@openqcm.com](mailto:info@openqcm.com)
