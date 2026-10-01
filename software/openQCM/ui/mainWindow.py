
# from openQCM.ui.mainWindow_ui import Ui_Controls, Ui_Info, Ui_Plots

# GUI redesign R1: programmatic UI builder (was: generated mainWindow_new_ui)
from openQCM.ui.mainWindow_ui import Ui_MainWindow

#from openQCM.ui.ui_controls import Ui_Controls
#from openQCM.ui.ui_info import Ui_Info
#from openQCM.ui.ui_plots import Ui_Plots

from pyqtgraph import AxisItem
import pyqtgraph as pg

# from PyQt5 import QtCore, QtGui
# VER 0.1.2
# importing from PyQt5 or PySide2
try:
    from PyQt5 import QtCore, QtGui
except:
    from PySide2 import  QtCore, QtGui


from openQCM.core.worker import Worker
from openQCM.processors.Serial import SerialProcess
from openQCM.core.constants import Constants, SourceType, ElapsedTimeAxis, NonScientificAxis

from openQCM.ui.popUp import PopUp
from openQCM.ui import theme
from openQCM.ui.plotMenu import PlotMenu
from openQCM.ui.widgets import (_Chevroned, ChevronComboBox,
                                ChevronSpinBox, ChevronDoubleSpinBox)
from openQCM.common.logger import Logger as Log
from openQCM.common.architecture import Architecture,OSType
from openQCM.common import sweepDump as SweepDump
from openQCM.common import fdLimit
from openQCM.common.tecStatus import decode_error_register

import numpy as np
import sys
import serial
import os
import tempfile
import re

import time
from numpy import loadtxt
from openQCM.core.ringBuffer import RingBuffer


from time import sleep

# The legacy "Raw Data (from sweep files)" viewer and its matplotlib window are
# imported inside _raw_data_plot(), the only place that uses them: a release
# build has no sweep_data/*.txt to read and must not depend on that package
# existing, nor pay matplotlib's import at start-up for a menu entry it hides.


# VER 0.1.5b the identification number as the board reports it: one compact
# integer, SSNN, no separator. Valid range 100-25599 (series 1-255, unit 00-99),
# so three to five digits and nothing else. The old dashed form is not accepted.
_BOARD_SERIAL_RE = re.compile(r'^\d{3,5}$')


def _first_reply_line(text):
    """The first non-empty line of a board reply, stripped.

    ⚠️ Not text.rstrip('\r\n'), which was the rule here and only strips the
    TRAILING terminator: a leading blank line, or a second line after the one
    that matters, survives it and then fails an exact comparison for a reason
    nothing on screen explains. Every query goes through this now -- firmware
    version and identification number both.
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _firmware_is_current(version):
    """True when the board reports a firmware this software expects.

    Exact equality with Constants.FW_VERSION, plus -- while
    Constants.accept_test_firmware is on -- the same version carrying the
    '-TEST' suffix the no-TEC prototype firmware appends.

    ⚠️ One place, because the check appears four times in
    get_firmware_version, and a rule spelled out four times is a rule that
    drifts. The switch is a development one: a shipped instrument must not
    accept a prototype firmware without saying so.
    """
    if not version:
        return False
    if version == Constants.FW_VERSION:
        return True
    return (Constants.accept_test_firmware
            and version == Constants.FW_VERSION
                           + Constants.FW_VERSION_TEST_SUFFIX)

# _drain_serial outcomes. Three, not two: "the board never stopped talking" and
# "the handle raised" are opposite faults with opposite remedies -- wait, or
# reconnect -- and collapsing them into a single False is what reported a board
# that had just re-enumerated after a firmware update as a board still sweeping.
# The number that separates them is the elapsed time: a dead handle raises in
# ~0 ms, a busy board burns the whole 6 s timeout.
DRAIN_QUIET = "quiet"
DRAIN_BUSY = "busy"
DRAIN_LINK_LOST = "link-lost"

TAG = ""#"[MainWindow]"

class LogStream:
    """Mirror stdout/stderr into the System Log tab (timestamped) while still
    forwarding to the original stream. Adapted from openQCM Q-1 v3.0. Captures
    the main process's print() output; child-process prints and logging-module
    messages are not intercepted (they keep going to the terminal / log file).
    A line the acquisition process wants in here goes through
    ParserProcess.add_message(): the worker prints it in this process."""

    def __init__(self, text_widget, stream):
        self._text_widget = text_widget
        self._stream = stream

    def write(self, text):
        # keep the original stream working (terminal / redirected output)
        if self._stream is not None:
            self._stream.write(text)
            self._stream.flush()
        if not text:
            return
        line = text.rstrip()
        if line == "" or text == "\r":
            return
        stamp = time.strftime("[%H:%M:%S] ")
        # append is thread-safe via a queued cross-thread invocation
        QtCore.QMetaObject.invokeMethod(
            self._text_widget, "append", QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, stamp + line))

    def flush(self):
        if self._stream is not None:
            self._stream.flush()


##########################################################################################
# Package that handles the UIs elements and connects to worker service to execute processes
##########################################################################################

class MainWindow(QtGui.QMainWindow):

    ###########################################################################
    # Initializes methods, values and sets the UI
    ###########################################################################
    def __init__(self, samples=Constants.argument_default_samples):

        #:param samples: Default samples shown in the plot :type samples: int.
        # to be always placed at the beginning, initializes some important methods
        QtGui.QMainWindow.__init__(self)

        # VER 0.1.6 Flag to track closing state in closeEvent method 
        self._closing = False 

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        
        # VER 0.1.6 start time 
        self.start_time = None

        # Shared variables, initial values
        self._plt0 = None
        self._plt1 = None
        self._plt2 = None
        # TODO 2m self._plt3 DISSIPATION
        # TODO delete
        # self._plt3 = None
        self._plt4 = None
        self._pltD = None
        
        # VER 0.1.6 init references to the line object of PyQtGraph plot 
        self._plt0_line = None 
        self._plt1_line = None
        self._plt2_line = None
        self._plt4_line = None
        self._pltD_line = None
        
        # VER 0.1.6 init a referencve to the line object in PyQtGraph plot 
        self._plt2_multiline = [None, None, None, None, None]
        self._pltD_multiline = [None, None, None, None, None]
        
        # VER 0.1.6 init a reference to the line object amplitude sweep in multiscan mode
        self._plt0_multiline = [None, None, None, None, None]

        # VER 0.1.6 number of overtone lines/legend items; set per-run in start()
        # for serial/multiscan. Default 0 so stop()'s legend-removal loop is a
        # no-op in calibration/peak-detection mode (which never populates a legend)
        # — previously this attribute was undefined there and stop() (now reachable
        # via the Stop button during peak detection) raised AttributeError.
        self._overtones_number_all = 0

        self._timer_plot = None
        self._readFREQ = None
        self._QCS_installed = None
        self._ser_control = 0
        self._ser_error1 = 0
        self._ser_error2 = 0
        self._ser_err_usb= 0
        
        # VER 0.1.4
        # TEC status var
        self._TEC_status = 0
        self._old_value = 0
        # the TEC controller's active errors as last reported (names), and the
        # moment until which a requested RESET is still considered in progress
        self._tec_errors = set()
        self._tec_reset_pending_until = 0.0
        # GUI: intended state of the single Temperature ON/OFF toggle
        self._tec_on = False

        # internet connection variable
        self._internet_connected = False

        # Reference variables
        self._reference_flag = False
        self._nscale = False        # Plot Controls > N-SCALE
        self._vector_reference_frequency = None
        self._vector_reference_dissipation = None
        self._vector_1 = None
        self._vector_2 = None

        # Instantiates a Worker class
        self.worker = Worker()

        # Populates comboBox for sources
        self.ui.cBox_Source.addItems(Constants.app_sources)

        # VER 0.1.4
        # add datalog sampling time combobox
        self.ui.cBox_sampling_time.addItems(Constants.SAMPLING_TIME_LIST)
        self.ui.cBox_sampling_time.setCurrentIndex(Constants.SAMPLING_TIME_LIST_DEFAULT_INDEX)
        
        # VER 0.1.6 moved multiscan array selector here before self._configure_plot()
        self.scan_selector = [0, 0, 0, 0, 0]

        # Phase 3b: compact F0..F9 overtone quick-select buttons (proxy the
        # legacy radios, which stay the source of truth for scan_selector)
        self._setup_overtone_buttons()

        # Configures specific elements of the PyQtGraph plots
        self._configure_plot()

        # Phase 4: custom right-click menu, grid toggle, Δ cursors (F / D)
        self._setup_plot_interactions()

        # Configures specific elements of the QTimers
        self._configure_timers()

        # Configures the connections between signals and UI elements
        self._configure_signals()

        # Populates combo box for serial ports
        self._source_changed()
        # set calibration to default measurement mode
        self.ui.cBox_Source.setCurrentIndex(SourceType.calibration.value)

        # TODO delete sbox number of samples
        # self.ui.sBox_Samples.setValue(samples)  #samples

        # VER 0.1.6 the temperature/frequency/dissipation readout fields are now
        # styled by the theme QSS (via their objectNames), so they follow the
        # active light/dark theme instead of a hardcoded white background.

        # VER 0.1.6 theme system (GUI redesign Phase 0): build the View > Theme
        # menu and apply the saved theme (default light on first run).
        self._theme = "light"
        self._setup_theme_menu()
        _saved = QtCore.QSettings("openQCM", "NEXT").value("theme", "light")
        _saved = str(_saved) if _saved else "light"
        self._apply_theme(_saved if _saved in ("light", "dark") else "light")

        # VER 0.1.6 frequency and dissipation label color
        # init the array of frequency label color 
        label_F = [self.ui.label_F0_col, self.ui.label_F3_col, self.ui.label_F5_col, self.ui.label_F7_col, self.ui.label_F9_col]
        label_D = [self.ui.label_D0_col, self.ui.label_D3_col, self.ui.label_D5_col, self.ui.label_D7_col, self.ui.label_D9_col]
        
        # init the array of dissipation label color 
        for color, label in zip(Constants.plot_color_multi, label_F):
            rgb_color = "rgb(%d, %d, %d)" % (color[0], color[1], color[2])
            label.setStyleSheet("background-color: %s;" % rgb_color)
            
        for color, label in zip(Constants.plot_color_multi_diss, label_D):
            rgb_color = "rgb(%d, %d, %d)" % (color[0], color[1], color[2])
            label.setStyleSheet("background-color: %s;" % rgb_color)

        

        # enable ui
        self._enable_ui(True)

        # disable temperature control at startup
        self._Temperature_Setting_isEnabled(False)

        ###################################################################################################################################
        self.get_web_info(True)
        # Gets the QCS installed on the device (not used now)
        # self._QCS_installed = PopUp.question_QCM(self, Constants.app_title, "Please choose the Quartz Crystal Resonator installed on the openQCM-1 Device (default 5MHz if exit)")

        # TODO my serial for temeprature communication
        self._my_serial = serial.Serial()

        # TODO multi frequency buffer definition # FREQUENCY
        self._frequency_buffer = RingBuffer(Constants.ring_buffer_samples)
        self._frequency_buffer_1 = RingBuffer(Constants.ring_buffer_samples)
        self._frequency_buffer_2 = RingBuffer(Constants.ring_buffer_samples)

        # TODO multi dissipation buffer definition  # DISSIPATION
        self._dissipation_buffer = RingBuffer(Constants.ring_buffer_samples)
        self._dissipation_buffer_1 = RingBuffer(Constants.ring_buffer_samples)
        self._dissipation_buffer_2 = RingBuffer(Constants.ring_buffer_samples)

        self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("warn"))

        

        # set-point and flags to their defaults at init. ⚠️ Not the PID rows:
        # they are the operator's last Set PID and outlive a restart, so that
        # the controller is put back to them at the next connect.
        self._reset_temperature_config()

        # VER 0.1.6 TODO multiscan y-range limit lists
        # VER 0.1.2
        # multiscan y-range limit lists
        self._y_freq_max = [0, 0, 0, 0, 0]
        self._y_freq_min = [0, 0, 0, 0, 0]
        self._y_diss_max = [0, 0, 0, 0, 0]
        self._y_diss_min = [0, 0, 0, 0, 0]
        
# =============================================================================
#         # DEV RAWDATA
#         self._window_pro = ApplicationWindow()
#         self._window_pro.show()
#         
#         plot_sweep_spline.script()
# =============================================================================
        
        # VER 0.1.4 enable sampling time datalog only in multiscan mode 
        if ( self._get_source() == SourceType.calibration):
            self.ui.cBox_sampling_time.setEnabled(False)
        if (self._get_source() == SourceType.serial):
            self.ui.cBox_sampling_time.setEnabled(False)
        if (self._get_source() == SourceType.multiscan):
            self.ui.cBox_sampling_time.setEnabled(True)
        
        
        # VER 0.1.4  get device firmware version 
# =============================================================================
#         
#         self._get_firmware_version()
# 
# =============================================================================
        
        # VER 0.1.4 toolbar menu bar 
        self.ui.actionFirmware.triggered.connect(lambda: self.get_firmware_version(False))
        self.ui.actionSerialNumber.triggered.connect(
            lambda: self._query_serial_number(auto_mode=False))
# =============================================================================
#         self.ui.actionFirmware.triggered.connect(self.dummy)
# =============================================================================
        self.ui.actionSoftware.triggered.connect(lambda: self.get_web_info(False))
        # VER 0.1.6 (Fase 5) real Help target + About entry (replaces the dummy)
        self.ui.actionHelp.triggered.connect(self._open_help_website)
        try:
            self.ui.menuHelp.addSeparator()
            self._act_about = QtGui.QAction("About openQCM NEXT", self)
            self._act_about.triggered.connect(self._show_about)
            self.ui.menuHelp.addAction(self._act_about)
        except Exception:
            pass

        # VER 0.1.6 toolbar menu add on application
        self.ui.actionTEC_current.triggered.connect(self._open_tec_current_view)
        self.ui.actionRaw_Data.triggered.connect(self._raw_data_plot)
        self.ui.actionRawDataView.triggered.connect(self._open_raw_data_view)
        self.ui.actionPeakDataView.triggered.connect(self._open_peak_data_view)
        self.ui.actionPIDControl.triggered.connect(self._open_pid_control)
        self.ui.actionOpenLog.triggered.connect(self._open_datalog_view)
        self._peak_data_view = None
        # the PID Control window, while it is open
        self._pid_control = None
        # the Tec Current window, while it is open
        self._tec_current_view = None
        self._datalog_views = []

        # The file-based viewer only has something to read when the sweep dump is
        # on, and the dump is a development tool that is off in release. Hide the
        # entry rather than leave it there to open an empty or stale window.
        self.ui.actionRaw_Data.setVisible(SweepDump.is_enabled())

        # the live Raw Data View, while it is open
        self._raw_data_view = None

        # VER 0.1.6 init the null numpy array
        self._numpy_nan_signal = np.empty(Constants.ring_buffer_samples, dtype=float)
        self._numpy_nan_signal.fill(np.nan)
        self._numpy_nan_sweep = np.empty(Constants.SAMPLES, dtype=float)
        self._numpy_nan_sweep.fill(np.nan)

        # GUI redesign R1: the programmatic UI (ui/mainWindow_ui.py) builds the
        # single-window shell directly; here we only bind the runtime state.
        self._board_serial = None       # SSNN read from the board EEPROM
        self._setup_log_filename_label()
        self._install_system_log()

        # Nothing is connected yet, so the dot starts grey; _setup_serial_connection_ui
        # sets the message that says what to do about it.
        self._set_status("disconnected", "Standby")


    # https://stackoverflow.com/questions/63182608/colcount-not-working-for-legenditem-in-pyqtgraph-with-pyqt5-library
    # TODO legend horizontal layout
    def setColumnCount(self, legend, columnCount):
        '''
        change the orientation of all items of the legend
        '''
        def _addItemToLayout(legend, sample, label):
            col = legend.layout.columnCount()
            row = legend.layout.rowCount()
            if row:
                row -= 1
            nCol = legend.columnCount * 2
            # FIRST ROW FULL
            if col == nCol:
                for col in range(0, nCol, 2):
                    # FIND RIGHT COLUMN
                    if not legend.layout.itemAt(row, col):
                        break
                if col + 2 == nCol:
                    # MAKE NEW ROW
                    col = 0
                    row += 1
            legend.layout.addItem(sample, row, col)
            legend.layout.addItem(label, row, col + 1)

        legend.columnCount = columnCount
        legend.rowCount = int(len(legend.items) / columnCount)
        for i in range(legend.layout.count() - 1, -1, -1):
            legend.layout.removeAt(i)  # clear layout
        for sample, label in legend.items:
            _addItemToLayout(legend, sample, label)
        legend.updateSize()

    def _toggle_start_stop(self):
        # Phase 3a: single Start/Stop toggle — one button drives both actions.
        if self.worker.is_running():
            self.stop()
        else:
            self.start()

    ###########################################################################
    # Starts the acquisition of the selected serial port
    ###########################################################################
    def start(self):
        
        
        # VER 0.1.6 do not clear the console 
# =============================================================================
#         import os
#         os.system('cls' if os.name == 'nt' else 'clear')
# =============================================================================

        # This function is connected to the clicked signal of the Start button.
        #print("")
        print(TAG, 'Clicked START')
        Log.i(TAG, "Clicked START")

        # TODO Disable temperature control button
        #DEV
# =============================================================================
#         self.ui.pButton_Tswitch_OFF.setEnabled(False)
#         self.ui.pButton_Tswitch_ON.setEnabled(False)
# =============================================================================

        # Release the previous worker BEFORE building the new one: each holds
        # ~100 file descriptors (queues), and two at once took the process to
        # the edge of a 256 limit (bench, 2026-09-09: START failed twice in
        # Queue() with "Too many open files").
        if self.worker is not None:
            self.worker.close()
        print(TAG, "{} (before START)".format(fdLimit.describe()))
        Log.i(TAG, "{} (before START)".format(fdLimit.describe()))

        # Instantiates process
        self.worker = Worker(QCS_on = self._QCS_installed,
                             port = self.ui.cBox_Port.currentText(),
                             speed = self.ui.cBox_Speed.currentText(),
                             samples = Constants.argument_default_samples,
                             source = self._get_source(),
                             export_enabled = False,
                             sampling_time = self._get_sampling_time())

        # Hand the serial port over to the acquisition process: release the
        # persistent GUI handle so the child can open it exclusively.
        # (The level-1 lock file stays held by the GUI.)
        if self._serial_lock is not None and self._serial_lock.isOpen():
            self._serial_lock.close()
            # the port now belongs to the acquisition process
            self._enable_device_queries()

        # SINGLE
        # ---------------------------------------------------------------------
        if self.worker.start():
            # Phase 3d: show the datalog filename (empty in calibration mode)
            self._show_log_filename(self.worker.get_csv_filename())

            # Gets frequency range
            # self._readFREQ = self.worker.get_frequency_range()

            # Duplicate frequencies
            self._reference_flag = False
            self._update_reference_button()   # keep the Set/Clear toggle label in sync
            # self._vector_reference_frequency = list(self._readFREQ)
            self._reference_value_frequency = 0
            self._reference_value_dissipation = 0

            # init frequency reference array values
            self._reference_value_frequency_array = [0, 0, 0, 0, 0]
            # init dissipation reference array values
            self._reference_value_dissipation_array = [0, 0, 0, 0, 0]

            self._labelref1 = "not set"
            self._labelref2 = "not set"
            # progressbar variables
            self._completed = 0
            self._ser_control = 0
            # error variables
            self._ser_error1 = 0
            self._ser_error2 = 0
            self._ser_err_usb = 0
            ##### other useful location #########
            #self.get_web_info()
            #####
            
            # VER 0.1.4
            # disable the sampling time 
            self.ui.cBox_sampling_time.setEnabled(False)


            #### SINGLE
            # -----------------------------------------------------------------
            if self._get_source() == SourceType.serial:
                # TODO DELETE
                # overtones_number = len(self.worker.get_source_speeds(SourceType.serial))

                # for single scan Gets frequency range
                self._readFREQ = self.worker.get_frequency_range()

                self._vector_reference_frequency = list(self._readFREQ)
                self._overtones_number_all = len(self.worker.get_source_speeds(SourceType.serial))
                
                # VER 0.1.6 delete the quartz label in the drop down menu  
                # not necessary to manually select the fundamental frequency of quartz
                # it is automatically identified by the new peak detection procedure

# =============================================================================
#                 if ( float(self.worker.get_source_speeds(SourceType.serial)[self._overtones_number_all-1])>4e+06 and float(self.worker.get_source_speeds(SourceType.serial)[self._overtones_number_all-1])<6e+06):
#                    label_quartz = "@5MHz_QCM"
#                 elif (float(self.worker.get_source_speeds(SourceType.serial)[self._overtones_number_all-1])>9e+06 and float(self.worker.get_source_speeds(SourceType.serial)[self._overtones_number_all-1])<11e+06):
#                    label_quartz = "@10MHz_QCM"
# 
# =============================================================================
# =============================================================================
#                 #  TODO set the legend in single mode
#                 overtone_selected = self._overtones_number_all - self.ui.cBox_Speed.currentIndex() - 1
# =============================================================================
# =============================================================================
#                 # TODO PRINT THE LEGEND
#                 # frequency
#                 self._plt2.plot(pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], width = Constants.plot_line_width), name = Constants.name_legend[overtone_selected])
#                 # dissipation
#                 self._pltD.plot(pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], width = Constants.plot_line_width), name = Constants.name_legend[overtone_selected])
# =============================================================================
                
                # VER 0.1.6 clear the plot now 
                self.clear()    
                # clear the amplitude once again 
                self._plt0.clear()
                
                overtone_selected = self._overtones_number_all - self.ui.cBox_Speed.currentIndex() - 1

                # VER 0.1.6 reference to the line object frequency   
                self._plt2_line = self._plt2.plot(pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], 
                                                                 width = Constants.plot_line_width))
                                        
                # reference to the line object dissipation 
                self._pltD_line = self._pltD.plot(pen = pg.mkPen(color = Constants.plot_color_multi_diss[overtone_selected], 
                                                                 width = Constants.plot_line_width))
                                                
                
                # VER 0.1.6 after clear the plt create the reference to the ampli lines again 
                self._plt0_line = self._plt0.plot(pen=self._curve_color())
                
# =============================================================================
#                 # reference to the line object temperature 
#                 self._plt4_line = self._plt4.plot(pen=Constants.plot_colors[4])
# =============================================================================
                # reference to the line object temperature 
                self._plt4_line = self._plt4.plot(pen=self._curve_color())
                
                # VER 0.1.6 add legend in single mode 
                self._legend_f.addItem(item = self._plt2_line, name = Constants.name_legend[overtone_selected])
                self._legend_D.addItem(item = self._pltD_line, name = Constants.name_legend[overtone_selected])
                
                # VER 0.1.6 do not autorange  
# =============================================================================
#                 # enable autoragne here 
#                 self._plt4.enableAutoRange(axis= 'y', enable = True)
# =============================================================================


# =============================================================================
#                 # VER 0.1.2
#                 # add phase plot additional axis
#                 self._plt0.scene().addItem(self._plt1)
# =============================================================================
                
                # VER 0.1.6 BUG the ampli signal is not clear move the clear up
                # clear plot
                # self.clear()
                # VER 0.1.6 remove reference to phase signal
                
# =============================================================================
#                 self._plt1.clear()
# =============================================================================

            #### CALIBRATION
            # -----------------------------------------------------------------
            elif self._get_source() == SourceType.calibration:

                # VER 0.1.6 peak detection populates no overtone legend; keep the
                # count at 0 so a Stop-triggered stop() removes no legend items.
                self._overtones_number_all = 0

                # VER 0.1.6 delete the call to label_quartz in calibration peak detection mode
# =============================================================================
#                 label_quartz = self.ui.cBox_Speed.currentText()
# =============================================================================

                # VER 0.1.2
                # add phase plot additional axis
                # VER 0.1.6 remove reference to phase signal
# =============================================================================
#                 self._plt0.scene().addItem(self._plt1)
# =============================================================================
                # clear plot
                self.clear()
                # VER 0.1.6 remove reference to phase signal
# =============================================================================
#                 self._plt1.clear()
# =============================================================================



            #### MULTISCAN
            # -----------------------------------------------------------------
            elif self._get_source() == SourceType.multiscan:

                # TODO get number of overtones and do nothing apparently
                self._overtones_number_all = len(self.worker.get_source_speeds(SourceType.serial))
                
                # VER 0.1.6 TODO Initialize time_axis_new with NaNs
                self._time_axis_new = np.full(self._overtones_number_all, np.nan)
                
                # VER 0.1.6 delete the label quartz 
                # TODO get the quartz crystal fundamental frequency
# =============================================================================
#                 if ( float(self.worker.get_source_speeds(SourceType.multiscan)[self._overtones_number_all-1])>4e+06 and 
#                     float(self.worker.get_source_speeds(SourceType.multiscan)[self._overtones_number_all-1])<6e+06):
#                    label_quartz = "@5MHz_QCM"
#                 elif (float(self.worker.get_source_speeds(SourceType.multiscan)[self._overtones_number_all-1])>9e+06 and 
#                       float(self.worker.get_source_speeds(SourceType.multiscan)[self._overtones_number_all-1])<11e+06):
#                    label_quartz = "@10MHz_QCM"
# =============================================================================

                # TODO redefine the array here
                self._arr = np.zeros((self._overtones_number_all, Constants.ring_buffer_samples))

# =============================================================================
#                 # legend
#                 for idx in range(self._overtones_number_all):
#                     # TODO PRINT THE LEGEND
#                     # frequency
#                     self._plt2.plot(pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width), name = Constants.name_legend[idx])
#                     # dissipation
#                     self._pltD.plot(pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width), name = Constants.name_legend[idx])
# =============================================================================
                
                # VER 0.1.6 create the reference to the multi lines for real time plot
                # legend
                for idx in range(self._overtones_number_all):
                    
                    # frequency multilines 
                    self._plt2_multiline[idx] = self._plt2.plot(pen = pg.mkPen(color = Constants.plot_color_multi[idx], 
                                                                               width = Constants.plot_line_width))
                    # dissipation multilines 
                    self._pltD_multiline[idx] = self._pltD.plot(pen = pg.mkPen(color = Constants.plot_color_multi_diss[idx], 
                                                                               width = Constants.plot_line_width))
                
                
                # VER 0.1.6 create the reference to the sweep aplitude multi lines for real time plot
                for idx in range(self._overtones_number_all):
                    self._plt0_multiline[idx] = self._plt0.plot(pen = Constants.plot_color_multi[idx])
            
# =============================================================================
#                 # VER 0.1.6 reference to the line object temperature 
#                 self._plt4_line = self._plt4.plot(pen=Constants.plot_colors[4])    
# =============================================================================
                # VER 0.1.6 create the reference to theto the temperature line for real time plot
                self._plt4_line = self._plt4.plot(pen=self._curve_color())

                # init radio button
                self.ui.radioBtn_F0.setChecked(True)
                self.ui.radioBtn_F3.setChecked(True)
                self.ui.radioBtn_F5.setChecked(True)
                self.ui.radioBtn_F7.setChecked(True)
                self.ui.radioBtn_F9.setChecked(True)

                self._update_scan_selector()
                # Phase 3b: mirror the all-checked default on the quick-select row
                self._sync_overtone_buttons_from_radios()

# =============================================================================
#                 # VER 0.1.2
#                 # add phase plot additional axis
#                 self._plt0.scene().removeItem(self._plt1)
# =============================================================================

                # clear plot
                self.clear()


            # VER 0.1.6 the elapsed-time axes latch their reference from the
            # first samples of this run: clear the previous one here, so a second
            # acquisition does not count from the first one's start.
            self.start_time = None
            self._xaxis.reset_start_time()
            self._xaxisD.reset_start_time()
            self._xaxisT.reset_start_time()

            # SET TIMER UPDATE
            # -----------------------------------------------------------------
            self._timer_plot.start(Constants.plot_update_ms)

            # CONNECT UPDATE PLOT
            # -----------------------------------------------------------------
            # VER 0.1.6 BUG multiple executions of the connected slot (self._update_plot) for a single timer timeout.
            # self._timer_plot.timeout.connect(self._update_plot) # moved from _configure_timers mothod
            
            # VER 0.1.6 disconnect the slot before reconnecting it to avoid multiple executions of self._update_plot
            try:
                self._timer_plot.timeout.disconnect(self._update_plot)
            except TypeError:
                # handles the case where the slot was not connected
                pass 
            self._timer_plot.timeout.connect(self._update_plot)
            
            self._enable_ui(False)
            
            # VER 0.1.6 do not autorange here 
            # VER 0.1.2
            # auto scale frequency and dissipation plt
            
# =============================================================================
#             self._plt2.enableAutoRange(axis= 'y', enable = True)
#             self._pltD.enableAutoRange(axis= 'y', enable = True)
# =============================================================================

            if self._get_source() == SourceType.calibration:
               self.ui.pButton_Clear.setEnabled(False) #insert
               self.ui.pButton_Reference.setEnabled(False) #insert
               self.ui.pButton_Reference_Not.setEnabled(False)

        else:
            print(TAG, "Warning: port is not available!")
            Log.i(TAG, "Warning: port is not available")
            PopUp.warning(self, Constants.app_title, "Warning: Selected Port [{}] is not available!".format(self.ui.cBox_Port.currentText()))

    ###########################################################################
    # Stops the acquisition of the selected serial port
    ###########################################################################
    def stop(self):

        # This function is connected to the clicked signal of the Stop button.
        # Phase 3d: clear the datalog filename display (sidebar + window title)
        self._show_log_filename("")
        # R2: reset the bottom-bar compact readings
        self._reset_status_readings()
        # stop() re-acquires the port, so the dot goes back to connected-and-idle
        self._set_status("standby", "Standby")
        self._set_message("acquisition stopped")

        # VER 0.1.6 peak detection is the only mode that reaches stop() while
        # still running via the Stop button — normal completion (and errors)
        # tear down inline in _update_plot, never through stop(). So a stop()
        # during calibration is always a user cancellation: reflect it.
        if self._get_source() == SourceType.calibration:
            self._set_status("warn", "Peak detection cancelled")
            self._set_message("cancelled by user")
            # VER 0.1.6 clear the real-time amplitude sweep trace: the generic
            # clear() later in stop() is a no-op during calibration (its frequency
            # buffer is NaN), so the last partial sweep would otherwise linger on
            # the amplitude plot after a cancellation.
            self._plt0.clear()

        # Re-enable the temperature toggle after a run, but only if still
        # connected (it is gated on the serial connection).
        self.ui.pButton_Tswitch_ON.setEnabled(self._serial_connected)

        # remove legend item
        for idx in range(self._overtones_number_all):
            self._legend_f.removeItem(Constants.name_legend[idx])
            self._legend_D.removeItem(Constants.name_legend[idx])

        # set temperature to default value
        # self.ui.doubleSpinBox_Temperature.setValue( Constants.Temperature_Set_Value )

        self._timer_plot.stop()
        self._enable_ui(True)
        self.worker.stop()
        print(TAG, "{} (after STOP)".format(fdLimit.describe()))
        Log.i(TAG, "{} (after STOP)".format(fdLimit.describe()))

        # add a delay to prevent the error caused by the serial com port open
        time.sleep(1)

        # Re-acquire the serial port for the GUI (Standby) now that the child
        # acquisition process has released it, so the queries below can run.
        self._reacquire_serial_lock()

        # turn off the peltier
        self.Temperature_Control_OFF()

        # add a little delay
        time.sleep(0.5)
        # reset the temperature set-point to its default. ⚠️ The PID rows are
        # left alone: a STOP used to put them back to the default while the
        # controller kept what the acquisition had sent (measured: P800 in the
        # controller, 500 in the file), and the next START sent the default
        # again. Now file, window and controller stay the same across STOP.
        self._reset_temperature_config()

        # VER 0.1.4
        # set TEC status control to null 
        self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("off"))
        self.ui.label_Temperature_state.setText("Temperature Control")
        
# =============================================================================
#         # VER 0.1.4
#         self.clear()
# =============================================================================
        
        # VER 0.1.6 clear all plot and remove all the legend items 
        # self.clear_all_plot()
        self.clear()
        self._remove_legend()
        
        
        # VER 0.1.4
        # enable - disble the sampling time 
# =============================================================================
#         self.ui.cBox_sampling_time.setEnabled(True)
# =============================================================================
        # VER 0.1.4 enable sampling time datalog only in multiscan mode 
        if ( self._get_source() == SourceType.calibration):
            self.ui.cBox_sampling_time.setEnabled(False)
        if (self._get_source() == SourceType.serial):
            self.ui.cBox_sampling_time.setEnabled(False)
        if (self._get_source() == SourceType.multiscan):
            self.ui.cBox_sampling_time.setEnabled(True)
            
        # VER 0.1.6 enable again frequency drop down menu only if in single mode 
        if (self._get_source() == SourceType.serial):
            self.ui.cBox_Speed.setEnabled(True)

        # the Tec Current window shows a running acquisition; none, no window
        self._close_tec_current_view()

        # STOP put the temperature card back to idle above; if the controller
        # was in error when the run ended it still is -- X0 clears nothing --
        # so the lock comes back on top: OFF/T SET disabled, RESET the only
        # live control, from Standby (bench, 2026-09-10: the card went idle
        # with RESET grey while the latch-up was still set).
        self._reapply_tec_error_lock()
         
        # VER 0.1.6 the elapsed-time reference is cleared in start(), not here:
        # the finished run stays on screen after STOP and its ticks have to keep
        # meaning something.
        

    ###########################################################################
    # SET TEMPERATURE
    ###########################################################################
    def temperatureSet(self):
        '''
        print ("SET TEMPERATURE")
        var = self.ui.doubleSpinBox_Temperature.value()
        print ('T' + str(int(var)) + '\n')

        self._my_serial.port = self.ui.cBox_Port.currentText()
        self._my_serial.baudrate = Constants.serial_default_speed #115200
        self._my_serial.stopbits = serial.STOPBITS_ONE
        self._my_serial.bytesize = serial.EIGHTBITS
        self._my_serial.timeout = Constants.serial_timeout_ms
        self._my_serial.writetimeout = Constants.serial_writetimeout_ms

        # Gets the state of the serial port
#        if not self._my_serial.isOpen():
#            # OPENS the serial port
#            self._my_serial.open()
#            cmd = 'T' + str(int(var)) + '\n'
#            self._my_serial.write(cmd.encode())
##            print(self._my_serial.readall)
##            buffer = self._my_serial.read(self._my_serial.in_waiting).decode(Constants.app_encoding)
##            print(buffer)
        # OPENS the serial port
        self._my_serial.open()
        cmd = 'T' + str(int(var)) + '\n'
        self._my_serial.write(cmd.encode())
        self._my_serial.close()
        '''

        var = self._get_temperature()
        cmd = 'T' + str(int(var)) + '\n'

        print ("Set Temperature =  ", var/1000)

        # send the set-temperature command over the persistent connection
        self._serial_write(cmd.encode())

    def _get_temperature(self):
        _var = self.ui.doubleSpinBox_Temperature.value() * 1000
        _path = Constants.manual_frequencies_path
        # np.savetxt( _path,  np.row_stack( [_var, 1] ) )
        # np.savetxt( _path,  [_var])
        # return self.ui.doubleSpinBox_Temperature.value()

        # the flag that makes the acquisition send the set-point at its next sweep
        _var_bool = 1

        # ⚠️ Rows 1-4 (the PID) and 6 (TEC on/off) come from the file, not from
        # widgets. This used to copy the PID from the hidden sidebar spin boxes,
        # which nothing keeps up to date any more: every T SET silently put the
        # file's PID back to whatever they held, and the acquisition then sent
        # it (measured: P1000 I200 D100 after a T SET during a run).
        param = loadtxt(Constants.manual_frequencies_path)

        np.savetxt( _path,  np.row_stack( [_var, param[1], param[2], param[3], param[4], _var_bool, param[6]] ), fmt='%d'  )

        return _var

    # TEMPERATURE CONTROL FUNCTION
    ###########################################################################

    def _toggle_temperature_control(self):
        # Single ON/OFF toggle: turn the TEC off if it is on, otherwise on.
        if self._tec_on:
            self.Temperature_Control_OFF()
        else:
            self.Temperature_Control_ON()

    def _update_tec_toggle(self):
        # Reflect the TEC state on the single toggle button: accent "Temperature
        # ON" when the control is off (a click turns it on); brown "Temperature
        # OFF" when the control is on (a click turns it off).
        btn = self.ui.pButton_Tswitch_ON
        btn.setText("OFF" if self._tec_on else "ON")
        btn.setProperty("tecOn", self._tec_on)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def Temperature_Control_ON(self):

        # GUI: mark the toggle state on and restyle it (brown = will turn off)
        self._tec_on = True
        self._update_tec_toggle()

        # change the indicator color
        self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("active"))

        print ("Temperature Control ON")
        # enable TEC over the persistent connection
        var = 1
        cmd = 'X' + str(int(var)) + '\n'
        self._serial_write(cmd.encode())

# =============================================================================
#         # VER 0.1.2 TODO
#         elif  ( self.worker.is_running() == True ):
#             # DEV
#             print ("the worker is running ")
# =============================================================================

        # VER 0.1.2
        # save temperature control boolean to config file
        _path = Constants.manual_frequencies_path
        param = loadtxt(Constants.manual_frequencies_path)
        _ctrl_bool = 1
        np.savetxt( _path,  np.row_stack([param[0], param[1], param[2], param[3], param[4], param[5], _ctrl_bool]), fmt='%d' )

        # enable - disable UI control
        self._Temperature_Setting_isEnabled(True)


    def Temperature_Control_OFF(self):

        # GUI: mark the toggle state off and restyle it (accent = will turn on)
        self._tec_on = False
        self._update_tec_toggle()

        # change the led color
        self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("warn"))
        # ⚠️ The set-point spin box is NOT reset here. Switching the TEC off
        # changes neither the set-point in config.txt nor the one the
        # controller holds, and a reset here used to put 25 on the indicator
        # while both still had 20: the next ON then looked like it was going
        # to the wrong temperature (bench, 2026-09-08).

        print ("Temperature Control OFF ")
        # disable TEC over the persistent connection
        var = 0
        cmd = 'X' + str(int(var)) + '\n'
        self._serial_write(cmd.encode())

# =============================================================================
#         elif  ( self.worker.is_running() == True ):
#             #DEV
#             print ("waring: unable to send disable temperature control message")
# =============================================================================

        #DEV version 0.1.1.d
        # save temperature control boolean to config file
        _path = Constants.manual_frequencies_path
        param = loadtxt(Constants.manual_frequencies_path)
        _ctrl_bool = 0
        np.savetxt( _path,  np.row_stack([param[0], param[1], param[2], param[3], param[4], param[5], _ctrl_bool]), fmt='%d' )

        # enable - disable UI control
        self._Temperature_Setting_isEnabled(False)

    def _Temperature_Setting_isEnabled(self, my_bool):
        # T SET and its spin box follow the TEC switch; the PID has its own
        # window (Tools > PID Control) and follows the connection instead
        self.ui.pButton_Temperature_Set.setEnabled(my_bool)
        self.ui.doubleSpinBox_Temperature.setEnabled(my_bool)

    def _setup_overtone_buttons(self):
        """Phase 3b: compact F0..F9 quick-select buttons (adapted from openQCM
        Q-1 v3.0). They proxy the legacy overtone radios, which stay the source
        of truth for scan_selector but are hidden. Multiscan: multi-select,
        purely-visual curve filter (all overtones are always acquired).
        Serial: exclusive selection driving cBox_Speed."""
        self._overtone_radios = [self.ui.radioBtn_F0, self.ui.radioBtn_F3,
                                 self.ui.radioBtn_F5, self.ui.radioBtn_F7,
                                 self.ui.radioBtn_F9]
        # R1: the buttons are created (and the radios hidden) by the UI
        # builder — here we only mirror the initial state and wire the signals.
        self._overtone_buttons = list(self.ui.overtone_buttons)
        for idx, btn in enumerate(self._overtone_buttons):
            btn.setChecked(self._overtone_radios[idx].isChecked())
            btn.clicked.connect(lambda checked, i=idx: self._on_overtone_button(i, checked))
        self.ui.cBox_Speed.currentIndexChanged.connect(self._sync_overtone_buttons_from_speed)

    def _on_overtone_button(self, idx, checked):
        """Quick-select click: serial → exclusive selection driving cBox_Speed;
        multiscan → mirrors the hidden radio and refreshes scan_selector."""
        if self._get_source() == SourceType.serial:
            # exclusive: one measured overtone; keep the radios (sweep-display
            # gating) aligned with it
            for i, r in enumerate(self._overtone_radios):
                r.setChecked(i == idx)
            self._update_scan_selector()
            # the combo lists the calibrated overtones in reverse order
            count = self.ui.cBox_Speed.count()
            combo_index = count - 1 - idx
            if 0 <= combo_index < count:
                self.ui.cBox_Speed.setCurrentIndex(combo_index)
            self._sync_overtone_buttons_from_speed()
        else:
            self._overtone_radios[idx].setChecked(checked)
            self._update_scan_selector()

    def _sync_overtone_buttons_from_speed(self, *args):
        """Serial mode: reflect the cBox_Speed selection on the button row."""
        if self._get_source() != SourceType.serial:
            return
        count = self.ui.cBox_Speed.count()
        sel = (count - 1 - self.ui.cBox_Speed.currentIndex()) if count else -1
        for i, b in enumerate(self._overtone_buttons):
            b.blockSignals(True)
            b.setChecked(i == sel)
            b.blockSignals(False)

    def _sync_overtone_buttons_from_radios(self):
        """Mirror the radios' checked state onto the quick-select buttons."""
        for i, b in enumerate(self._overtone_buttons):
            b.blockSignals(True)
            b.setChecked(self._overtone_radios[i].isChecked())
            b.blockSignals(False)

    def _Overtone_radioBtn_isEnabled(self, my_bool):
        self.ui.radioBtn_F0.setEnabled(my_bool)
        self.ui.radioBtn_F3.setEnabled(my_bool)
        self.ui.radioBtn_F5.setEnabled(my_bool)
        self.ui.radioBtn_F7.setEnabled(my_bool)
        self.ui.radioBtn_F9.setEnabled(my_bool)
        # Phase 3b: the quick-select buttons follow the mode gating (multiscan:
        # my_bool; serial: enabled while idle — they drive cBox_Speed there)
        _serial_idle = (self._get_source() == SourceType.serial
                        and not self.worker.is_running())
        for b in getattr(self, "_overtone_buttons", []):
            b.setEnabled(my_bool or _serial_idle)


    # PID CONTROL FUNCTION
    ###########################################################################

    def _reset_temperature_config(self):
        """Set-point and the two flags back to their defaults; PID rows kept.

        Falls back to the full default file when config.txt is missing or
        unreadable, which is the only case in which the PID rows are written.
        """
        _path = Constants.manual_frequencies_path
        try:
            param = loadtxt(_path)
            cycling, p_share, i_share, d_share = (int(param[k]) for k in (1, 2, 3, 4))
        except Exception as e:
            print(TAG, "config.txt unreadable ({}): writing the full default".format(e))
            self._set_PID_T_default()
            return
        np.savetxt(_path, np.row_stack([Constants.Temperature_Set_Value * 1000,
                                        cycling, p_share, i_share, d_share,
                                        Constants.PID_boolean_default,
                                        Constants.CTRL_boolean_default]), fmt='%d')
        self.ui.doubleSpinBox_Temperature.setValue(Constants.Temperature_Set_Value)

    def _set_PID_T_default(self):
        """The whole config.txt back to the defaults. Only the fallback of
        `_reset_temperature_config` for a missing or unreadable file: nothing
        else may write the PID rows but Set PID (HANDOFF §3)."""
        _path = Constants.manual_frequencies_path
        # save default file in config.ini file
        np.savetxt( _path,  np.row_stack([Constants.Temperature_Set_Value * 1000,
                                          Constants.cycling_time_default,
                                          Constants.P_share_default,
                                          Constants.I_share_default,
                                          Constants.D_share_default,
                                          Constants.PID_boolean_default,
                                          Constants.CTRL_boolean_default]), fmt='%d'  )

        # update indicator to default value
        self.ui.doubleSpinBox_Temperature.setValue(Constants.Temperature_Set_Value)
        # the PID Control window, if open, must show the file and not the past
        self._sync_pid_control()
    
    # VER 0.1.4 check if the datalog sampling time is changed 
    def _datalog_sampling_time_changed(self):
        print ("datalog sampling time changed ")
        _my_index = self.ui.cBox_sampling_time.currentIndex()
        return _my_index
        
    def _get_sampling_time(self):
        index = self.ui.cBox_sampling_time.currentIndex()
        if index == 0:
            time = - 1
        else:
            time = int(Constants.SAMPLING_TIME_LIST[index])
        
        return time
        
    
    # VER 0.1.4 get frimware version 
    def get_firmware_version(self, autoMode):
        # query the device over the persistent connection (opened on Connect)

        # VER 0.1.5b no port, no question. Without this the query returns an
        # empty string and the branch below reads that as "no firmware
        # information", which answers a closed port with *Please update
        # firmware version* -- the wrong problem, and the one the operator then
        # goes looking for.
        if not self._can_query_device():
            if not autoMode:
                PopUp.warning(self, Constants.app_title,
                              "Serial port not available.\n"
                              "Connect to the device, and stop the acquisition "
                              "first.")
            print(TAG, "Firmware version query skipped: port not available")
            return

        # init the byte at port and read serlai string
        byte_at_port = 0
        read_serial = ""
        firmware_version_current = ""
        
        # chek if worker is running, to prevent conflict
        if ( (self.worker.is_running() == False) and (autoMode == True)):
            try:
                # query firmware version over the persistent connection
                read_serial += self._serial_query(b'F\n')

                # firmware version: first non-empty line of the reply
                firmware_version_current = _first_reply_line(read_serial)
                self._firmware_version = firmware_version_current
                # the raw reply, because the branches below that raise the
                # update warning print nothing, and then a wrong answer and no
                # answer at all look identical from the outside
                print (TAG, "Firmware version response: {} [{}]".format(
                    repr(read_serial), "auto" if autoMode else "menu"))
                Log.i(TAG, "Firmware version response: {}".format(
                    repr(read_serial)))

                # VER 0.1.6 a dead handle is not a busy board, and it is
                # checked first: after a firmware update the device
                # re-enumerates and every read raises instead of answering
                if self._link_lost():
                    self._report_link_lost("Firmware version query", autoMode)
                    return

                # VER 0.1.5c a board still finishing a sweep is not a board
                # with old firmware, and must not be reported as one
                if self._board_busy(firmware_version_current):
                    print (TAG, "Board still busy: firmware check skipped")
                    Log.w(TAG, "Board still busy: firmware check skipped")
                    if not autoMode:
                        PopUp.warning(self, Constants.app_title,
                                      "The board is still sending measurement "
                                      "data.\nWait a moment and try again.")
                    return

                # no firmware information
                if (firmware_version_current == ""):
                    # print ("No firmware information. Please upgrade firmware to the version ", Constants.FW_VERSION)
                    # VER 0.1.4 popup a warning
                    upgrade_firmware = PopUp.warning_exec(self, "FIRMWARE UPDATE", "Please update firmware version " + str(Constants.FW_VERSION) +
                                                          ". Press Yes button to continue the firmware update procedure")

                    if (upgrade_firmware == True):
                        # run the firmware the updater application
                        self._run_firmware_updater()

                    elif (upgrade_firmware == False):
                        # pop a critical
                        upgrade_firmware_critical = PopUp.critical_exec(self, "FIRMWARE UPDATE",
                                                                        "Failure to update the firmware may result in a software crash or malfunction." + "\n\r" +
                                                                        "Please update firmware version " + str(Constants.FW_VERSION) +
                                                                        ". Press Yes button to continue the firmware update procedure")
                        if (upgrade_firmware_critical == True):
                            # run the firmware the updater application
                            self._run_firmware_updater()

                # previous old firmware installed
                elif (not _firmware_is_current(firmware_version_current)):
                    # VER 0.1.4 popup a warning  
                    upgrade_firmware = PopUp.warning_exec(self, "FIRMWARE UPDATE", "Please update firmware version " + str(Constants.FW_VERSION) + 
                                                          ". Press Yes button to continue the firmware update procedure")
                    if (upgrade_firmware == True): 
                        # run the firmware the updater application
                        self._run_firmware_updater()
                    
                    elif (upgrade_firmware == False): 
                        # pop a critical 
                        upgrade_firmware_critical = PopUp.critical_exec(self, "FIRMWARE UPDATE", 
                                                                        "Failure to update the firmware may result in a software crash or malfunction." + "\n\r" + 
                                                                        "Please update firmware version " + str(Constants.FW_VERSION) + 
                                                                        ". Press Yes button to continue the firmware update procedure")
                 
                # firmware is update to the lates version    
                elif (_firmware_is_current(firmware_version_current)):
                    # the reported string, not the expected one: on the
                    # prototype board they differ, and the operator has to see
                    # which firmware actually answered
                    print ("Firmware Version " + str(firmware_version_current))
            
            except: 
                print ("Warning: Unable to open serial port. Please check device connection.")
    
        # AUTOMODE FALSE: GET FW INFO from MENU BAR only if the worker is not running     
        # VER 0.1.5 if the worker is not running get firmware info and eventually launch the firmware updater application                             
        elif ((self.worker.is_running() == False) and (autoMode == False)):
            try:
                # query firmware version over the persistent connection
                read_serial += self._serial_query(b'F\n')

                # firmware version: first non-empty line of the reply
                firmware_version_current = _first_reply_line(read_serial)
                self._firmware_version = firmware_version_current
                # the raw reply, because the branches below that raise the
                # update warning print nothing, and then a wrong answer and no
                # answer at all look identical from the outside
                print (TAG, "Firmware version response: {} [{}]".format(
                    repr(read_serial), "auto" if autoMode else "menu"))
                Log.i(TAG, "Firmware version response: {}".format(
                    repr(read_serial)))

                # VER 0.1.6 a dead handle is not a busy board, and it is
                # checked first: after a firmware update the device
                # re-enumerates and every read raises instead of answering
                if self._link_lost():
                    self._report_link_lost("Firmware version query", autoMode)
                    return

                # VER 0.1.5c a board still finishing a sweep is not a board
                # with old firmware, and must not be reported as one
                if self._board_busy(firmware_version_current):
                    print (TAG, "Board still busy: firmware check skipped")
                    Log.w(TAG, "Board still busy: firmware check skipped")
                    if not autoMode:
                        PopUp.warning(self, Constants.app_title,
                                      "The board is still sending measurement "
                                      "data.\nWait a moment and try again.")
                    return
                
                # no firmware information 
                if (firmware_version_current == ""): 
                    # print ("No firmware information. Please upgrade firmware to the version ", Constants.FW_VERSION)
                    # VER 0.1.4 popup a warning 
                    upgrade_firmware = PopUp.warning_exec(self, "FIRMWARE UPDATE", "Please update firmware version " + str(Constants.FW_VERSION) + 
                                                          ". Press Yes button to continue the firmware update procedure")
                   
                    if (upgrade_firmware == True): 
                        # run the firmware the updater application
                        self._run_firmware_updater()
                    
                    elif (upgrade_firmware == False): 
                        # pop a critical 
                        upgrade_firmware_critical = PopUp.critical_exec(self, "FIRMWARE UPDATE", 
                                                                        "Failure to update the firmware may result in a software crash or malfunction." + "\n\r" + 
                                                                        "Please update firmware version " + str(Constants.FW_VERSION) + 
                                                                        ". Press Yes button to continue the firmware update procedure")
                        if (upgrade_firmware_critical == True): 
                            # run the firmware the updater application
                            self._run_firmware_updater()
                
                # previous old firmware installed
                elif (not _firmware_is_current(firmware_version_current)):
                    # VER 0.1.4 popup a warning  
                    upgrade_firmware = PopUp.warning_exec(self, "FIRMWARE UPDATE", "Please update firmware version " + str(Constants.FW_VERSION) + 
                                                          ". Press Yes button to continue the firmware update procedure")
                    if (upgrade_firmware == True): 
                        # run the firmware the updater application
                        self._run_firmware_updater()
                    
                    elif (upgrade_firmware == False): 
                        # pop a critical 
                        upgrade_firmware_critical = PopUp.critical_exec(self, "FIRMWARE UPDATE", 
                                                                        "Failure to update the firmware may result in a software crash or malfunction." + "\n\r" + 
                                                                        "Please update firmware version " + str(Constants.FW_VERSION) + 
                                                                        ". Press Yes button to continue the firmware update procedure")
                 
                # VER 0.1.5 if the firmware is update send a feedback message 
                # firmware is update to the lates version    
                elif (_firmware_is_current(firmware_version_current)):
                    print ("Firmware Version " + str(firmware_version_current))
                    PopUp.info_not_blocking_rtf(self, "Firmware Information", 
                    "Firmware Version " +  str(firmware_version_current) + "<br>" + 
                    "openQCM Next installed the most recent firmware. " + "<br>"  + 
                    "For more info please visit " + "<br>"  + 
                    "<a href='https://openqcm.com/openqcm-next-software/'>openQCM NEXT Firmware webpage</a>"
                    )
            
            except: 
                print ("Warning: Unable to open serial port. Please check device connection.")
# =============================================================================
#             try:
#                 # open serial port
#                 self._my_serial.open()
#                 # send firmware version  
#                 cmd = 'F' + '\n'
#                 self._my_serial.write(cmd.encode())
#                 sleep(0.1)
#                 # serial read answer from the device 
#                 byte_at_port = self._my_serial.inWaiting()
#                 read_serial += self._my_serial.read(byte_at_port).decode(Constants.app_encoding)
#                 
#                 sleep(0.1)
#                 # close the serial 
#                 self._my_serial.close()
#         
#                 # firmare version from serial read strip new line char 
#                 firmware_version_current = read_serial.rstrip('\r\n')
#                 
#                 # no firmware information 
#                 if (firmware_version_current == ""): 
#                     PopUp.info_not_blocking(self, "Firmware information", "No firmware information. Please update firmware")
#                 
#                 # previous old firmware installed
#                 elif (firmware_version_current != Constants.FW_VERSION):
#                     # VER 0.1.5 get response action from popup
#                     PopUp.info_not_blocking(self, "Firmware information", "Previous firmware installed. Please update firmware")
#                     
#                 # firmware is update to the latest version        
#                 elif (firmware_version_current == Constants.FW_VERSION):
#                     print ("Firmware Version " +  str(Constants.FW_VERSION))
#                     
#                     PopUp.info_not_blocking_rtf(self, "Firmware Information", 
#                                                 "Firmware Version " +  str(Constants.FW_VERSION) + "<br>" + 
#                                                 "openQCM Next installed the most recent firmware. " + "<br>"  + 
#                                                 "For more info please visit " + "<br>"  + 
#                                                 "<a href='https://openqcm.com/openqcm-next-software/'>openQCM NEXT Firmware webpage</a>"
#                                                 )
#             except: 
#                 print ("Warning: Unable to open serial port. Please check device connection.")
# =============================================================================
        
        # VER 0.1.5 if the worker is running just open a warning pop-up window
        elif ((self.worker.is_running() == True) and (autoMode == False)):
            PopUp.warning_not_blocking(self, "Firmware information","Warning: unable to get firmware information during a measurement session")
    
    def _firmware_image(self, directory):
        """The .hex this software wants on the board, right variant included.

        ⚠️ Derived from Constants.FW_VERSION, never spelled out. The image and
        the version the check demands are the same fact, and a hard-coded file
        name is how the folder ended up shipping `0.1.5` while the software
        asked for `0.1.5c` -- the operator updated, and was asked to update
        again by the same dialog.

        The variant follows what the board has just answered. A no-TEC
        prototype reports the '-TEST' suffix, and handing it the TEC image
        would flash a firmware for hardware it does not have. When the board
        answered nothing at all the production image is the safe guess, and the
        log says which one was chosen either way.

        Returns None when the image is not there, which is not fatal: the
        loader still opens, just empty, exactly as it always did.
        """
        reported = getattr(self, "_firmware_version", "") or ""
        variant = ("_TEST"
                   if reported.endswith(Constants.FW_VERSION_TEST_SUFFIX)
                   else "")
        name = "openQCM_Next_py_{}{}_teensy.ino.TEENSY40.hex".format(
            Constants.FW_VERSION, variant)
        path = directory + name
        if os.path.exists(path):
            print(TAG, "Firmware image: {} (board reported {})"
                  .format(name, repr(reported)))
            Log.i(TAG, "Firmware image: {}".format(name))
            return path
        print(TAG, "Firmware image {} not found in {} -- the loader will open "
              "with no file".format(name, directory))
        Log.w(TAG, "Firmware image {} not found".format(name))
        return None

    def _run_firmware_updater(self):
        import os, sys, subprocess
        # ⚠️ Resolved from this module, not from os.getcwd(). The old path
        # only existed when the application happened to be started from
        # `software/`; from a launcher, a packaged build, or any other
        # directory the updater silently did not open at all. Same fix and
        # same reason as APP_ICON in mainWindow_ui.
        directory_firmware_update = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "firmware_update")) + os.sep
        
        exe_name = "TyUploader.exe"
        app_name = "Teensy.app"
      
        # ⚠️ The launch used to be silent whichever way it went. os.startfile
        # raises and `open` returns a non-zero code, and neither was looked
        # at, so a procedure that did nothing read exactly like one that
        # worked -- there was no line in the log either way.
        target = directory_firmware_update + (exe_name
                                              if sys.platform == "win32"
                                              else app_name)
        print(TAG, "Firmware updater: {} (present: {})"
              .format(target, os.path.exists(target)))
        Log.i(TAG, "Firmware updater: {}".format(target))
        # ⚠️ The loader used to open with no file, so the operator picked the
        # image by hand out of a folder whose only .hex was the wrong version
        # and, on a prototype, the wrong variant too. The software already knows
        # which one it wants -- it has just read the reported version, suffix
        # included -- so it hands it over. Teensy.app declares no document type
        # but does implement application:openFile:, which is what `open -a`
        # sends; verified on Teensy Loader 1.52.
        image = self._firmware_image(directory_firmware_update)
        try:
            if sys.platform == "win32":
                if image:
                    subprocess.Popen([target, image])
                else:
                    os.startfile(target)
            elif sys.platform == "darwin":
                argv = (["open", "-a", target, image] if image
                        else ["open", target])
                rc = subprocess.call(argv)
                if rc != 0 and image:
                    # passing the file is the improvement, not the requirement:
                    # fall back to the old behaviour rather than fail outright
                    print(TAG, "Firmware updater: open -a with the image "
                          "exited {}, retrying without it".format(rc))
                    Log.w(TAG, "Firmware updater: retrying without the image")
                    rc = subprocess.call(["open", target])
                if rc != 0:
                    raise OSError("open exited with code {}".format(rc))
            else:
                rc = subprocess.call(["xdg-open", target])
                if rc != 0:
                    raise OSError("xdg-open exited with code {}".format(rc))
        except Exception as e:
            print(TAG, "Firmware updater not launched: {}".format(str(e)))
            Log.e(TAG, "Firmware updater not launched: {}".format(str(e)))
            PopUp.warning(self, Constants.app_title,
                          "The firmware updater could not be launched.\n\n"
                          "{}".format(target))
            return

        # ⚠️ Reprogramming the board re-enumerates the USB device, so from
        # here the handle this window holds is dead -- not maybe, always.
        # And the launcher returns as soon as the loader is on screen, not
        # when the board has been flashed, so there is nothing to wait for
        # and nothing to detect: the connection is forfeit the moment the
        # operator starts. Saying so now is what stops the next query from
        # reading ENXIO off a stale handle and reporting it as a board
        # still sending measurement data.
        if self._serial_connected:
            self._disconnect_serial(
                "firmware update in progress -- reconnect when it is done")
            # ⚠️ The status bar already says it and the Connect button has
            # already flipped back, so this dialog is redundant by design --
            # and it is here anyway. The operator's attention is on the Teensy
            # Loader in another application at this moment, not on our status
            # bar, and coming back to a window that silently stopped being
            # connected is how the next query gets blamed on the board.
            # Non-blocking: the loader is what needs the hands right now.
            PopUp.info_not_blocking(
                self, "FIRMWARE UPDATE",
                "Disconnected from serial port.\n\n"
                "Firmware update in progress.\n"
                "Reconnect when it is done.")

            
    ###########################################################################
    # Overrides the QTCloseEvent,is connected to the close button of the window
    ###########################################################################
    # VER 0.1.6 added a confirmation dialog when closing the application
    def closeEvent(self, evnt):
        """
        Overrides the QTCloseEvent, is connected to the close button of the window
        :param evnt: QT evnt.
        """
        # Check if we're already handling a close event
        if self._closing:
            evnt.accept()
            return
            
        # Set the closing flag
        self._closing = True
        
        # Show confirmation popup before closing
        res = PopUp.question(self, "Exit Application", "Are you sure you want to quit the application?")
        
        if res:
            # If user confirms, handle closing process as before
            if self.worker.is_running():
                print(TAG, 'Window closed without stopping the capture, application will stop...')
                Log.i(TAG, "Window closed without stopping the capture, application will stop...")
                self.stop()

            # take the auxiliary views down with the window
            self._close_raw_data_view()
            self._close_peak_data_view()
            self._close_pid_control()
            self._close_tec_current_view()
            self._close_datalog_views()

            # Restore stdout/stderr before the window is destroyed
            self._restore_system_log()
            # Accept the close event
            evnt.accept()
        else:
            # If user cancels, reset the closing flag and ignore the event
            self._closing = False
            evnt.ignore()


    ###########################################################################
    # Enables or disables the UI elements of the window.
    ###########################################################################
    def _board_busy(self, response):
        """True when the reply cannot be trusted because the board was talking.

        ⚠️ The distinction matters more than it looks. An unrecognised reply
        used to reach the "no firmware information" branch, which answers with
        *Please update firmware version* -- so a board mid-sweep was reported as
        a board with old firmware, and the operator went looking for the wrong
        problem. Two signs, either is enough: the drain timed out with the port
        still talking, or the answer carries a semicolon, which no version and
        no identification number does but every sweep sample line does.

        ⚠️ A handle that *raised* is not one of the two. It used to be, because
        the drain returned the same False for both, and that is how a board
        which had just re-enumerated after a firmware update was reported as a
        board still sweeping. See _link_lost().
        """
        if getattr(self, "_last_drain", DRAIN_QUIET) == DRAIN_BUSY:
            return True
        return ";" in (response or "")

    def _link_lost(self):
        """True when the last query found a dead handle, not a busy board.

        ⚠️ _can_query_device() cannot catch this: pyserial's isOpen()
        returns the is_open flag, which stays True after the device node
        underneath it has gone. Only an actual read finds out.
        """
        return getattr(self, "_last_drain", DRAIN_QUIET) == DRAIN_LINK_LOST

    def _report_link_lost(self, what, auto_mode):
        """Say the link is gone, and make the GUI state match.

        ⚠️ Not "the board is still sending measurement data". That
        message tells the operator to wait, and waiting never revives a
        handle whose device node is gone -- which is what a firmware update
        leaves behind every single time, because reprogramming the Teensy
        re-enumerates the USB device. The remedy is a reconnect, so the
        window goes to Disconnected and says so.
        """
        print(TAG, "{}: serial link lost, the board re-enumerated or was "
              "unplugged".format(what))
        Log.w(TAG, "{}: serial link lost".format(what))
        self._disconnect_serial("connection to the board lost")
        if not auto_mode:
            PopUp.warning(self, Constants.app_title,
                          "The connection to the board was lost.\n\n"
                          "This is expected right after a firmware update: "
                          "the board\nreappears as a new device. Press "
                          "Connect to reconnect.")

    def _can_query_device(self):
        """True when the GUI itself can talk to the board right now.

        ⚠️ Not just `_serial_connected`: start() hands the port to the
        acquisition process by CLOSING the handle without dropping the
        reference, so `_serial_lock is not None` stays true while the child
        owns the port. Whether it is OPEN is what decides.

        The same predicate drives the menu state and the two query methods, so
        a greyed-out entry and a refused query can never disagree about what
        the instrument is doing.
        """
        if not self._serial_connected or self._serial_lock is None:
            return False
        try:
            if not self._serial_lock.isOpen():
                return False
        except Exception:
            return False
        return not (self.worker is not None and self.worker.is_running())

    def _enable_device_queries(self):
        """Grey out the two menu queries unless the board can actually answer.

        ⚠️ Both talk to the board over the persistent handle, so both need an
        open port and an idle acquisition -- while a measurement runs the child
        process owns the port. Disconnected, the query used to reach the
        firmware check anyway and come back empty, which that code reads as "no
        firmware information" and answers with *Please update firmware version*:
        a closed port reported as an out-of-date board.

        The runtime guards inside the two methods stay: a menu item can also be
        triggered by a shortcut, and the automatic query on connect does not go
        through the menu at all.
        """
        can_ask = self._can_query_device()
        for name in ("actionFirmware", "actionSerialNumber"):
            act = getattr(self.ui, name, None)
            if act is not None:
                act.setEnabled(can_ask)
        # PID Control is not a query: it has a path during an acquisition too,
        # so it follows the connection, not the idle port
        self._sync_pid_control()

    def _enable_ui(self, enabled):

        #:param enabled: The value to be set for the UI elements :type enabled: bool
        # VER 0.1.6b keep the port combo disabled while a connection is active
        self.ui.cBox_Port.setEnabled(enabled and not self._serial_connected)
        
        # VER 0.1.6 not enable the combo box in calibration peak detection mode  
        if ( self._get_source() == SourceType.calibration):
            self.ui.cBox_Speed.setEnabled(not enabled)
        else: 
            self.ui.cBox_Speed.setEnabled(not enabled)
            
        # self.ui.cBox_Speed.setEnabled(enabled)

        # Phase 3b: serial quick-select buttons are idle-only (multiscan keeps
        # them live during acquisition as a purely-visual curve filter)
        if self._get_source() == SourceType.serial:
            for b in getattr(self, "_overtone_buttons", []):
                b.setEnabled(enabled)

        # VER 0.1.6b Start requires an active serial connection
        # Phase 3a: pButton_Start is a single Start/Stop toggle — keep it usable
        # while running (to act as Stop); gate only on the active connection.
        self.ui.pButton_Start.setEnabled(self._serial_connected)
        # the two device queries follow the same rule as Start
        self._enable_device_queries()
        # reflect the running state on the toggle (enabled True == idle)
        _running = not enabled
        # minimalist outline glyphs: ▷ play (start), □ square (stop)
        self.ui.pButton_Start.setText("□  Stop" if _running else "▷  Start")
        self.ui.pButton_Start.setProperty("running", _running)
        self.ui.pButton_Start.style().unpolish(self.ui.pButton_Start)
        self.ui.pButton_Start.style().polish(self.ui.pButton_Start)

        # TODO delete or implement export txt file
        # self.ui.chBox_export.setEnabled(enabled)

        self.ui.cBox_Source.setEnabled(enabled)
        self.ui.pButton_Stop.setEnabled(not enabled)

        # TODO delete the sample
        # self.ui.sBox_Samples.setEnabled(not enabled) #insert

        self.ui.pButton_Clear.setEnabled(not enabled)
        self.ui.pButton_Reference.setEnabled(not enabled)
        self.ui.pButton_Autoscale.setEnabled(not enabled)
        self.ui.pButton_Reference_Not.setEnabled(not enabled)
        
        # VER 0.1.4
        # tec reset button 
        self.ui.pButton_TEC_Reset.setEnabled(not enabled)
        
        # VER 0.1.4 enable sampling time datalog only in multiscan mode 
        if ( self._get_source() == SourceType.calibration):
            self.ui.cBox_sampling_time.setEnabled(enabled)
        if (self._get_source() == SourceType.serial):
            self.ui.cBox_sampling_time.setEnabled(enabled)
        if (self._get_source() == SourceType.multiscan):
            self.ui.cBox_sampling_time.setEnabled(enabled)

        #DEV
# =============================================================================
#         self.ui.pButton_Tswitch_OFF.setEnabled(enabled)
#         self.ui.pButton_Tswitch_ON.setEnabled(enabled)
# =============================================================================


    ###########################################################################
    # VER 0.1.6 Theme system (GUI redesign Phase 0)
    ###########################################################################
    def _setup_theme_menu(self):
        """Add a View > Theme submenu with an exclusive Light/Dark choice."""
        # R1: the programmatic UI provides the View menu in the menu skeleton
        menu_view = getattr(self.ui, "menuView", None)
        if menu_view is None:
            menu_view = self.menuBar().addMenu("View")
        # Order taken from Q-1 v3.0: what the window shows first, what the plots
        # show next, then the theme last behind a separator. Same entries as
        # before -- only the order and the grouping move.
        # Fase 5: panel visibility toggles (Sidebar, Status bar)
        self._act_view_sidebar = QtGui.QAction("Sidebar", self)
        self._act_view_sidebar.setCheckable(True)
        self._act_view_sidebar.setChecked(True)
        self._act_view_sidebar.toggled.connect(self._toggle_sidebar)
        menu_view.addAction(self._act_view_sidebar)
        self._act_view_statusbar = QtGui.QAction("Status Bar", self)
        self._act_view_statusbar.setCheckable(True)
        self._act_view_statusbar.setChecked(True)
        self._act_view_statusbar.toggled.connect(self._toggle_statusbar)
        menu_view.addAction(self._act_view_statusbar)
        # Phase 4: Δ Cursors, Grid (frequency / dissipation panels).
        # Grid lives here because pyqtgraph's own right-click menu has no grid
        # entry, and the custom right-click menu that used to carry it is gone.
        # Q-1 has no Grid entry, so it sits beside the cursors, which is the
        # other plot-display toggle.
        self._act_cursors = QtGui.QAction("Δ Cursors (F / D)", self)
        self._act_cursors.setCheckable(True)
        self._act_cursors.toggled.connect(self._toggle_all_cursors)
        menu_view.addAction(self._act_cursors)
        self._act_grid = QtGui.QAction("Grid", self)
        self._act_grid.setCheckable(True)
        self._act_grid.toggled.connect(self._toggle_all_grids)
        menu_view.addAction(self._act_grid)

        menu_view.addSeparator()
        theme_menu = menu_view.addMenu("Theme")
        group = QtGui.QActionGroup(self)
        group.setExclusive(True)
        self._act_theme_light = QtGui.QAction("Light", self)
        self._act_theme_light.setCheckable(True)
        self._act_theme_dark = QtGui.QAction("Dark", self)
        self._act_theme_dark.setCheckable(True)
        group.addAction(self._act_theme_light)
        group.addAction(self._act_theme_dark)
        theme_menu.addAction(self._act_theme_light)
        theme_menu.addAction(self._act_theme_dark)
        self._act_theme_light.triggered.connect(lambda: self._apply_theme("light"))
        self._act_theme_dark.triggered.connect(lambda: self._apply_theme("dark"))
        # R2: menu-bar corner quick toggle (mockup top-right)
        _btn = getattr(self.ui, "themeToggleButton", None)
        if _btn is not None:
            _btn.clicked.connect(lambda: self._apply_theme(
                "dark" if self._theme == "light" else "light"))

    ###########################################################################
    # VER 0.1.6 Fase 5 — Help / View menu handlers
    ###########################################################################
    def _open_help_website(self):
        """Open the openQCM NEXT software page in the default browser."""
        import webbrowser
        try:
            webbrowser.open("https://openqcm.com/openqcm-next-software/")
        except Exception as e:
            print(TAG, "Could not open help URL: {}".format(str(e)))

    def _show_about(self):
        """About dialog: name, version, one-line description, website link."""
        msg = ("<b>openQCM NEXT</b> &mdash; version {}<br><br>"
               "Real-time acquisition and analysis software for the openQCM NEXT "
               "Quartz Crystal Microbalance.<br><br>"
               "<a href='https://openqcm.com/openqcm-next-software/'>"
               "openQCM NEXT software webpage</a>").format(Constants.app_version)
        PopUp.info_not_blocking_rtf(self, "About openQCM NEXT", msg)

    def _toggle_sidebar(self, checked):
        """Show/hide the left sidebar (mainSplitter pane 0)."""
        # the pane wraps the scroll area AND the pinned Start/Stop button, so it
        # is the pane that has to be hidden
        pane = getattr(self.ui, "sidebarPane", None) \
            or getattr(self.ui, "sidebarScroll", None)
        if pane is not None:
            pane.setVisible(checked)

    def _toggle_statusbar(self, checked):
        """Show/hide the bottom status bar."""
        bar = getattr(self.ui, "statusBarFrame", None)
        if bar is not None:
            bar.setVisible(checked)

    # The machine state lives in the COLOUR OF ONE DOT, as in Q-1 v3.0. It used to
    # be a coloured pill behind the status text plus <font> tags inside the
    # message, which said the same thing twice and left the message itself harder
    # to read. Absolute colours, not palette ones: these are state semantics, and
    # they have to mean the same on both themes.
    _STATUS_DOT = {
        "disconnected": "#888888",   # serial not connected
        "standby": "#ffd700",        # connected, not acquiring
        "warn": "#ff9800",           # processing, or a recoverable warning
        "ok": "#4caf50",             # monitoring / success
        "err": "#f44336",            # error
    }

    def _status_dot(self, key):
        """Stylesheet for the state dot; remembers the key so a theme switch can
        re-apply it."""
        self._status_key = key
        return "color: {}; font-size: 14px;".format(
            self._STATUS_DOT.get(key, self._STATUS_DOT["standby"]))

    def _set_status(self, key, text=None):
        """Colour the state dot and, optionally, set the plain status text."""
        self.ui.statusIndicator.setStyleSheet(self._status_dot(key))
        if text is not None:
            self.ui.infostatus.setText(text)

    def _set_message(self, text):
        """The message beside the status: plain text, no colour of its own."""
        self.ui.infobar.setText(text)

    # R2 polish: TEC state banner (softened colors, rounded; 'off' follows the
    # theme). Keys: off / warn (getting setpoint) / active / err.
    _TEC_PILL_BG = {"warn": ("#ffd54f", "#4a3f00"),
                    "active": ("rgba(0, 142, 192, 0.35)", None),
                    "err": ("#ef5350", "#ffffff")}

    def _tec_state_pill(self, key):
        """Stylesheet for label_Temperature_state; remembers the state so a
        theme switch can re-apply it."""
        self._tec_state_key = key
        if key == "off":
            p = getattr(self, "_theme_palette", theme.LIGHT)
            return ("background-color: {}; color: {}; border: 1px solid {}; "
                    "border-radius: 6px; padding: 3px 6px;").format(
                        p["field_bg"], p["text"], p["border"])
        bg, fg = self._TEC_PILL_BG[key]
        fg_css = "color: {};".format(fg) if fg else ""
        return ("background-color: {}; {} border: 1px solid transparent; "
                "border-radius: 6px; padding: 3px 6px;").format(bg, fg_css)

    def _set_indicator_temperature(self, value):
        """Sidebar temperature readout + bottom-bar mirror (R2)."""
        self.ui.indicator_temperature.setText(str(value))
        self.ui.statusTempValue.setText("T: {}".format(value))

    def _reset_status_readings(self):
        """Reset the bottom-bar compact readings to placeholders (R2)."""
        for lbl, tag in ((self.ui.statusTempValue, "T"),
                         (self.ui.statusSampValue, "S")):
            lbl.setText("{}: --".format(tag))

    def _apply_theme(self, name):
        """Apply the light/dark theme: window QSS + pyqtgraph repaint + persist."""
        name = "dark" if name == "dark" else "light"
        self._theme = name
        self._theme_palette = theme.palette(name)
        # window-wide Qt Style Sheet
        self.setStyleSheet(theme.qss(self._theme_palette))
        # The combo chevron is painted, not styled, so a stylesheet cannot reach
        # it: hand it the palette here. Class attributes, so every combo in the
        # application follows in one step.
        _Chevroned.chevron_colour = self._theme_palette["muted"]
        _Chevroned.chevron_colour_disabled = self._theme_palette["disabled_text"]
        # the popup needs its own sheet, set on its own widgets: the window's
        # style sheet does not reach a top-level popup container
        ChevronComboBox.popup_qss = theme.popup_qss(self._theme_palette)
        ChevronComboBox.popup_background = self._theme_palette["panel"]
        # the three classes explicitly, rather than QtGui.QWidget: the widgets are
        # only reachable through QtGui here because pyqtgraph injects them, and
        # leaning on that is what broke File > Open Log
        for cls in (ChevronComboBox, ChevronSpinBox, ChevronDoubleSpinBox):
            for widget in self.findChildren(cls):
                if isinstance(widget, ChevronComboBox):
                    widget._style_popup()
                widget.update()
        # Phase 3c: re-apply the status pill so 'standby' follows the theme
        self.ui.statusIndicator.setStyleSheet(
            self._status_dot(getattr(self, "_status_key", "standby")))
        # R2: corner toggle shows the theme it switches to
        _btn = getattr(self.ui, "themeToggleButton", None)
        if _btn is not None:
            _btn.setText("☾ dark" if name == "light" else "☀ light")
        # R2 polish: re-apply the TEC state banner so 'off' follows the theme
        self.ui.label_Temperature_state.setStyleSheet(
            self._tec_state_pill(getattr(self, "_tec_state_key", "off")))
        # pyqtgraph plots (background / axes / titles)
        self._apply_plot_theme(theme.PLOT[name])
        # the open auxiliary views follow too: their canvases took the palette
        # at construction, and the QSS alone repaints only the frame around them
        views = [getattr(self, attr, None)
                 for attr in ("_tec_current_view", "_raw_data_view", "_peak_data_view")]
        views.extend(getattr(self, "_datalog_views", []))
        for view in views:
            if view is None or not hasattr(view, "apply_theme"):
                continue
            try:
                view.apply_theme(name)
            except RuntimeError:
                pass
        # keep the menu checkmarks in sync
        try:
            self._act_theme_light.setChecked(name == "light")
            self._act_theme_dark.setChecked(name == "dark")
        except Exception:
            pass
        # persist the choice for the next launch
        try:
            QtCore.QSettings("openQCM", "NEXT").setValue("theme", name)
        except Exception:
            pass

    def _apply_plot_theme(self, pt):
        """Repaint pyqtgraph backgrounds, axes and titles for the active theme."""
        # GraphicsLayoutWidget backgrounds
        for w in (getattr(self.ui, "plt", None),
                  getattr(self.ui, "pltB", None),
                  getattr(self.ui, "pltD", None)):
            if w is not None:
                try:
                    w.setBackground(pt["bg"])
                except Exception:
                    pass
        # per-plot axes + title (guarded: some refs are ViewBoxes or None)
        for plot in (self._plt0, self._plt1, self._plt2, self._pltD, self._plt4):
            if plot is None:
                continue
            for side in ("left", "bottom", "right", "top"):
                try:
                    ax = plot.getAxis(side)
                except Exception:
                    continue
                if ax is None:
                    continue
                try:
                    ax.setPen(pg.mkPen(color=pt["axis"]))
                except Exception:
                    pass
                try:
                    ax.setTextPen(pg.mkPen(color=pt["axis"]))
                except Exception:
                    pass
                if side in ("left", "bottom"):
                    try:
                        ax.setLabel(**{"color": pt["axis"]})
                    except Exception:
                        pass
            # recolor the plot title if it has one
            try:
                title_item = getattr(plot, "titleLabel", None)
                if title_item is not None and title_item.text:
                    plot.setTitle(title_item.text, color=pt["title"])
            except Exception:
                pass
        # VER 0.1.7 recolor the theme-dependent single curves: the amplitude
        # sweep (Constants.plot_colors[0]) and temperature (plot_color_temperature)
        # are white and vanish on the light theme's white plot background — give
        # them the theme foreground curve color.
        curve = pt.get("curve", pt["axis"])
        for line in (getattr(self, "_plt0_line", None),
                     getattr(self, "_plt4_line", None)):
            if line is not None:
                try:
                    line.setPen(pg.mkPen(color=curve))
                except Exception:
                    pass

    def _curve_color(self):
        """Foreground curve color for the active theme (amplitude sweep and
        temperature; their hardcoded white pen is invisible on the light
        theme's white plot background)."""
        return theme.PLOT[self._theme].get("curve", "#333333")

    ###########################################################################
    # VER 0.1.6 GUI redesign Phase 1 — single-window splitter shell
    ###########################################################################
    def _install_system_log(self):
        """Redirect stdout/stderr into the System Log tab, keeping the original
        streams (terminal / file logging unaffected). Reversed in closeEvent."""
        self.systemLog = self.ui.systemLog   # created by the UI builder
        self._stdout_orig = sys.stdout
        self._stderr_orig = sys.stderr
        sys.stdout = LogStream(self.systemLog, self._stdout_orig)
        sys.stderr = LogStream(self.systemLog, self._stderr_orig)
        print(TAG, "System Log ready.")

    def _restore_system_log(self):
        """Restore the original stdout/stderr (called when the window closes)."""
        if getattr(self, "_stdout_orig", None) is not None:
            sys.stdout = self._stdout_orig
        if getattr(self, "_stderr_orig", None) is not None:
            sys.stderr = self._stderr_orig

    def _setup_log_filename_label(self):
        """Phase 3d: datalog-filename label (created by the UI builder in the
        sidebar status area, hidden while idle — calibration writes no log)."""
        self._window_title_base = self.windowTitle()
        self.lblLogFile = self.ui.lblLogFile

    def _window_title(self, filename=None):
        """Compose the window title: name, board number, datalog.

        One place, because the two suffixes arrive from unrelated events -- the
        board answers 'S' on connect, the filename appears on START -- and
        composing them where they arrive is how one erases the other.
        """
        title = self._window_title_base
        if self._board_serial:
            title = "{} [{}]".format(title, self._board_serial)
        if filename:
            title = "{} — {}".format(title, filename)
        return title

    def _first_valid_timestamp(self, values, times):
        """Timestamp of the OLDEST sample that actually carries a datum.

        ⚠️ RingBuffer.get_all() returns the **newest** sample at index 0 and
        pads the tail with NaN, so array order runs backwards in time. The
        warm-up samples -- real timestamps, NaN values, because no mean exists
        until the circular buffer has filled -- therefore sit at the HIGH
        indices, behind the valid ones. The oldest datum actually drawn is the
        last element of the leading run of non-NaN values, and that is the
        instant the relative axis should call zero.

        Returns None while nothing valid has arrived yet, so the caller can try
        again on the next tick instead of latching a reference to a sample the
        user will never see.
        """
        oldest = None
        for i in range(len(values)):
            if np.isnan(values[i]):
                break
            if not np.isnan(times[i]):
                oldest = times[i]
        return oldest

    def _show_log_filename(self, filename):
        """Show/clear the datalog filename in the sidebar and window title.

        ⚠️ The eliding is the label's own job now (ui/widgets.ElidedLabel) and
        must not come back here. This method runs while the label is still
        hidden, so the width it could measure is Qt's default 100 px, not the
        260-400 px the sidebar actually gives it -- the name was cut to 140 px
        with 244 available. And the sidebar is draggable, so even a correct
        width measured here would be stale as soon as the splitter moved.
        """
        if filename:
            self.lblLogFile.setText("Log: " + filename)
            self.lblLogFile.show()
        else:
            self.lblLogFile.clear()
            self.lblLogFile.setToolTip("")
            self.lblLogFile.hide()
        self._current_log_filename = filename
        self.setWindowTitle(self._window_title(filename))

    def _show_board_serial(self, serial_number):
        """Put the board number under the brand and into the window title."""
        self._board_serial = serial_number
        if serial_number:
            self.ui.lblSerialNumber.setText("S/N {}".format(serial_number))
            self.ui.lblSerialNumber.show()
        else:
            self.ui.lblSerialNumber.clear()
            self.ui.lblSerialNumber.hide()
        self.setWindowTitle(
            self._window_title(getattr(self, "_current_log_filename", None)))

    ###########################################################################
    # VER 0.1.5b machine identification number
    ###########################################################################
    def _query_serial_number(self, auto_mode=False):
        """Ask the board for its identification number (serial command 'S').

        The firmware reads four bytes of EEPROM and answers SSNN -- 1920 -- or
        NO_SERIAL when the board has never been programmed. Three outcomes, and
        they mean different things: no valid answer at all is a firmware older
        than 0.1.5b, NO_SERIAL is a board whose EEPROM was never written, and
        anything else is the number.

        auto_mode runs it silently, which is how the connect path uses it: a
        popup on every connect would be noise.
        """
        if self.worker is not None and self.worker.is_running():
            if not auto_mode:
                PopUp.warning(self, Constants.app_title,
                              "Cannot read the board number during an "
                              "acquisition.\nStop it first.")
            return

        if not self._can_query_device():
            if not auto_mode:
                PopUp.warning(self, Constants.app_title,
                              "Serial port not available.\n"
                              "Connect to the device, and stop the acquisition "
                              "first.")
            print(TAG, "Board number query skipped: port not available")
            return

        try:
            reply = self._serial_query(b'S\n')
        except Exception as e:
            print(TAG, "Board number query failed: {}".format(e))
            Log.e(TAG, "Board number query failed: {}".format(e))
            if not auto_mode:
                PopUp.warning(self, Constants.app_title,
                              "Failed to communicate with the device."
                              "\n\nError: {}".format(e))
            return

        response = _first_reply_line(reply)
        print(TAG, "Board number response: '{}' (raw {}) [{}]".format(
            response, repr(reply), "auto" if auto_mode else "menu"))
        Log.i(TAG, "Board number response: '{}'".format(response))

        if self._link_lost():
            self._report_link_lost("Board number query", auto_mode)
            return

        if self._board_busy(response):
            print(TAG, "Board still busy: number query skipped")
            Log.w(TAG, "Board still busy: number query skipped")
            if not auto_mode:
                PopUp.warning(self, Constants.app_title,
                              "The board is still sending measurement data.\n"
                              "Wait a moment and try again.")
            return

        if response == "NO_SERIAL":
            # the board answers, the EEPROM was never written
            self._show_board_serial(None)
            self.ui.lblSerialNumber.setText("S/N not programmed")
            self.ui.lblSerialNumber.show()
            if not auto_mode:
                PopUp.warning(self, Constants.app_title,
                              "This board has no identification number.\n\n"
                              "Its EEPROM has never been written by the "
                              "SerialNumber programmer sketch.")
            else:
                Log.w(TAG, "Board EEPROM not programmed (NO_SERIAL)")

        elif not (_BOARD_SERIAL_RE.match(response)
                  and 100 <= int(response) <= 25599):
            # no answer, or sweep bytes from a firmware that does not know 'S'
            self._show_board_serial(None)
            if not auto_mode:
                PopUp.warning(self, Constants.app_title,
                              "The firmware did not answer the board number "
                              "request.\n\nThis needs firmware {} or later."
                              "\nUpdate it from Tools > Check Firmware "
                              "Version.".format(Constants.FW_VERSION))
            else:
                Log.w(TAG, "Firmware does not support the board number query")

        else:
            self._show_board_serial(response)
            print(TAG, "Board identification number: {}".format(response))
            Log.i(TAG, "Board identification number: {}".format(response))
            if not auto_mode:
                # info_not_blocking, not info: NEXT's PopUp has no info(). That
                # is a Q-1 method, and porting the call without checking is how
                # the success path raised AttributeError on the first click.
                PopUp.info_not_blocking(self, Constants.app_title,
                                        "Board identification number: {}"
                                        .format(response))

    ###########################################################################
    # Configures specific elements of the PyQtGraph plots.
    ###########################################################################
    def _configure_plot(self):

        #----------------------------------------------------------------------
        # set background color background="#0c2c36"
        # TEMPERATURE and SWEEP PLOT #0c2c36
        self.ui.plt.setBackground(background=Constants.plot_background_color)
        # FREQUENY PLOT
        self.ui.pltB.setBackground(background=Constants.plot_background_color)
        # DISSIPATION PLOT
        self.ui.pltD.setBackground(background=Constants.plot_background_color)
        #----------------------------------------------------------------------

        # defines the graph title
        title1 = "Real-Time Plot: Amplitude / Phase"
        title2 = "Real-Time Plot: Resonance Frequency "
        title3 = "Real-Time Plot: Temperature"
        #----------------------------------------------------------------------

        # Configures elements of the PyQtGraph plots: amplitude
        self.ui.plt.setAntialiasing(True)
        self.ui.pltB.setAntialiasing(True)
        self.ui.pltD.setAntialiasing(True)

        self._xaxis_sweep =  NonScientificAxis(orientation='bottom')
        self._xaxis_sweep.enableAutoSIPrefix(False)

        '''
        -----------------------------------------------------------------------
        SWEEP PLOT AMPLITUDE PHASE
        -----------------------------------------------------------------------
        '''
        self._plt0 = self.ui.plt.addPlot(row=0, col=0, title= title1, **{'font-size':'10pt'}, axisItems={"bottom":self._xaxis_sweep})
        # self._plt0.showGrid(x=True, y=True)
        self._plt0.setLabel('bottom', 'Frequency', units='Hz')
        # VER 0.1.6 simplify the plot label 
        # self._plt0.setLabel('left', 'Amplitude', units='dB', color=Constants.plot_title_color, **{'font-size':'10pt'})
        self._plt0.setLabel('left', 'Amplitude', units='dB')


        '''
        # Configures elements of the PyQtGraph plots: phase
        self._plt1 = self.u2.plt.addPlot(row=1, col=1, title= "Real-Time Plot: Phase", **{'font-size':'12pt'})
        # Phase 4: grids default OFF everywhere (toggle via right-click menu)
        self._plt1.showGrid(x=False, y=False)
        self._plt1.setLabel('bottom', 'Samples', units='n')
        self._plt1.setLabel('left', 'Phase', units='deg')
        '''
        #--------------------------------------------------------------------------------------------------------------
        # Configures elements of the PyQtGraph plots: Multiple Plot amplitude and phase
        
        # VER 0.1.6 remove reference to phase signal
# =============================================================================
#         self._plt1 = pg.ViewBox()
#         self._plt0.showAxis('right')
#         self._plt0.scene().addItem(self._plt1)
#         self._plt0.getAxis('right').linkToView(self._plt1)
#         self._plt1.setXLink(self._plt0)
#         self._plt0.enableAutoRange(axis= 'y', enable = True)
#         self._plt1.enableAutoRange(axis= 'y', enable = True)
#         self._plt0.setLabel('right', 'Phase', units='deg', color = Constants.plot_title_color, **{'font-size':'10pt'})
# =============================================================================

        # VER 0.1.2
        # editing pyqtgraph context menu
        # https://groups.google.com/g/pyqtgraph/c/h-dyr0l6yZU/m/NpMQxh-jf5cJ
        # get rid of 'Plot Options'
        # setMenuEnabled(False) silences the PlotItem menu AND the ViewBox one;
        # `ctrlMenu = None` only removed the former, which is why the default menu
        # kept appearing under the custom one.
        self._plt0.setMenuEnabled(False)
        
        # VER 0.1.6 remove reference to phase signal
# =============================================================================
#         self._plt1.ctrlMenu = None
# =============================================================================
        # get rid of 'Export'
        self._plt0.scene().contextMenu = None
        # VER 0.1.6 remove reference to phase signal
# =============================================================================
#         self._plt1.scene().contextMenu = None
# =============================================================================

        '''
        -----------------------------------------------------------------------
        FREQUENCY PLOT
        -----------------------------------------------------------------------
        '''
        #--------------------------------------------------------------------------------------------------------------
        # Configures elements of the PyQtGraph plots: resonance
        self._yaxis = NonScientificAxis(orientation='left')
        self._yaxis.enableAutoSIPrefix(False)
        #self._yaxis.setTickSpacing(levels=[(280, 0),(25, 0), (10, 0)]) #(20,1, None)
        # VER 0.1.6 TODO
        self._xaxis = ElapsedTimeAxis(orientation='bottom')

        '''
        TODO 2m 
        '''
        # Configures elements of the PyQtGraph plots: dissipatin
        self._yaxisD = NonScientificAxis(orientation='left')
        self._yaxisD.enableAutoSIPrefix(False)
        #self._yaxis.setTickSpacing(levels=[(280, 0),(25, 0), (10, 0)]) #(20,1, None)
        # VER 0.1.6 TODO
        self._xaxisD = ElapsedTimeAxis(orientation='bottom')
        


        '''
        self._plt2 = self.PlotsWin.ui2.pltB.addPlot(row=0, col=2, title= title2, **{'font-size':'12pt'}, axisItems={"bottom":self._xaxis, 'left':self._yaxis})
        '''
        '''
        TODO 2m
        FREQUENCY PLOT
        '''
        self._plt2 = self.ui.pltB.addPlot(row=0, col=2, title= title2, **{'font-size':'12pt'}, axisItems={"bottom":self._xaxis, 'left':self._yaxis})

        # self._plt2.showGrid(x=True, y=True)
# =============================================================================
#         self._plt2.setLabel('bottom', 'Time',units='s')
# =============================================================================
        
        # VER 0.1.6 set x axis as h:m:s and disable SI prefix 
        self._xaxis.enableAutoSIPrefix(False)
        self._plt2.setLabel('bottom', 'Time (hh:mm:ss)')
       
        # VER 0.1.6 optimize the frequency real time plot 
        # self._plt2.setLabel('left', 'Resonance Frequency', units='Hz', color = Constants.plot_title_color, **{'font-size':'10pt'})
        self._plt2.setLabel('left', 'Resonance Frequency', units='Hz')
        
        # VER 0.1.6 reference to the plot legend item frequency 
        # https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.11.0/graphicsItems/legenditem.html
        self._legend_f = self._plt2.addLegend()
        
        # change the orientation of all items of the legend
        # self._legend_f.setColumnCount(5)
        # TODO LEGEND
        # self.setColumnCount(self._legend_f, 5)

        # VER 0.1.2
        # editing pyqtgraph context menu
        # https://groups.google.com/g/pyqtgraph/c/h-dyr0l6yZU/m/NpMQxh-jf5cJ
        # get rid of 'Plot Options'
        # setMenuEnabled(False) silences the PlotItem menu AND the ViewBox one;
        # `ctrlMenu = None` only removed the former, which is why the default menu
        # kept appearing under the custom one.
        self._plt2.setMenuEnabled(False)
        # get rid of 'Export'
        self._plt2.scene().contextMenu = None

        '''
        TODO 2m
        DISSIPATION PLOT
        '''
        # self._pltD = self.ui.pltD.addPlot(row=0, col=1, title= "Real-Time Plot: Dissipation", **{'font-size':'12pt'}, axisItems={"bottom":self._xaxisD, 'left':self._yaxisD})
        self._pltD = self.ui.pltD.addPlot(row=0, col=1, title= "Real-Time Plot: Dissipation", **{'font-size':'12pt'}, axisItems={"bottom":self._xaxisD})
# =============================================================================
#         self._pltD.setLabel('bottom', 'Time',units='s')
# =============================================================================
        # VER 0.1.6 set x axis as h:m:s
        self._xaxisD.enableAutoSIPrefix(False)
        self._pltD.setLabel('bottom', 'Time (hh:mm:ss)')
        
        # VER 0.1.6 optimize the dissipation real time plot 
        # self._pltD.setLabel('left', 'Dissipation', units='', color = Constants.plot_title_color, **{'font-size':'10pt'})
        self._pltD.setLabel('left', 'Dissipation', units='')
        
        # VER 0.1.6 reference to the plot legend item dissipation 
        # https://pyqtgraph.readthedocs.io/en/pyqtgraph-0.11.0/graphicsItems/legenditem.html
        self._legend_D = self._pltD.addLegend()
        
        # change the orientation of all items of the legend
        # self._legend_D.setColumnCount(5)
        # TODO LEGEND
        # self.setColumnCount(self._legend_D, 5)

        # VER 0.1.2
        # editing pyqtgraph context menu
        # https://groups.google.com/g/pyqtgraph/c/h-dyr0l6yZU/m/NpMQxh-jf5cJ
        # get rid of 'Plot Options'
        # setMenuEnabled(False) silences the PlotItem menu AND the ViewBox one;
        # `ctrlMenu = None` only removed the former, which is why the default menu
        # kept appearing under the custom one.
        self._pltD.setMenuEnabled(False)
        # get rid of 'Export'
        self._pltD.scene().contextMenu = None

        # CONNECT PLOT
        # ---------------------------------------------------------------------
        self._pltD.setXLink(self._plt2)
        '''
        TODO 2m
        it is not TRIVIAL to connect y axis with different range
        # self._pltD.setYLink(self._plt2)
        '''

        #--------------------------------------------------------------------------------------------------------------
        # Configures elements of the PyQtGraph plots: Multiple Plot resonance frequency and dissipation

        # Configures elements of the PyQtGraph plots: temperature
        
        self._xaxisT = ElapsedTimeAxis(orientation='bottom')
        self._xaxisT.enableAutoSIPrefix(False)
        self._plt4 = self.ui.plt.addPlot(row=0, col=1, title= title3, axisItems={'bottom': self._xaxisT})
        # self._plt4.showGrid(x=True, y=True)

        # do not autoscale y axis
        # VER 0.1.6 enable autorange at the end of the configure plot 
# =============================================================================
#         self._plt4.enableAutoRange(axis= 'y', enable = True)
# =============================================================================

        # VER 0.1.2
        # change the Temperature Y-range to 5 - 45 Â°C
        # self._plt4.setYRange(5, 45, padding = 0)

# =============================================================================
#         self._plt4.setLabel('bottom', 'Time',units='s')
# =============================================================================
        # VER 0.1.6 set x axis as h:m:s
        self._plt4.getAxis('bottom').enableAutoSIPrefix(False)
        self._plt4.setLabel('bottom', 'Time (hh:mm:ss)')
        
        # VER 0.1.6 optimize the temperature real time plot 
        # self._plt4.setLabel('left', 'Temperature', units='°C', color = Constants.plot_title_color, **{'font-size':'10pt'})
        self._plt4.setLabel('left', 'Temperature', units='°C')
        
        # VER 0.1.2
        # editing pyqtgraph context menu
        # https://groups.google.com/g/pyqtgraph/c/h-dyr0l6yZU/m/NpMQxh-jf5cJ
        # get rid of 'Plot Options'
        # setMenuEnabled(False) silences the PlotItem menu AND the ViewBox one;
        # `ctrlMenu = None` only removed the former, which is why the default menu
        # kept appearing under the custom one.
        self._plt4.setMenuEnabled(False)
        # get rid of 'Export'
        self._plt4.scene().contextMenu = None
        
        # VER 0.1.6 enable auto range for all plot
        # amplitude sweep 
        self._plt0.enableAutoRange(enable=True)
        # frequency 
        self._plt2.enableAutoRange(enable=True)
        # dissipation 
        self._pltD.enableAutoRange(enable=True)
        # temperature 
        self._plt4.enableAutoRange(enable=True)
        
        # VER 0.1.6 update legend in configure plot 
        self._update_legend()
        
    ###########################################################################
    # Configures specific elements of the QTimers
    ###########################################################################
    def _configure_timers(self):

        self._timer_plot = QtCore.QTimer(self)
        # moved to start method
        #self._timer_plot.timeout.connect(self._update_plot) 

    ###########################################################################
    # Serial connection managed as a separate feature (Connect/Disconnect)
    # VER 0.1.6b - Step 1: explicit, port-locked connection decoupled from the
    # operation mode. The persistent exclusive handle (_serial_lock) plus the
    # migration of GUI queries and acquisition hand-off are a later step.
    ###########################################################################
    def _setup_serial_connection_ui(self):
        # Serial connection state
        self._serial_connected = False
        self._connected_port = None
        self._lock_file = None

        # R1: Connect / Refresh are created by the UI builder inside the
        # connection card (bottom row); here we only wire their signals.
        self.ui.pButton_Refresh.clicked.connect(self._refresh_ports)
        self.ui.pButton_Connect.clicked.connect(self._toggle_serial_connection)

        # Initial connection status
        self.ui.label_COM_status.setText("Disconnected")
        self._set_status("disconnected", "Standby")
        self._set_message("select a port and click Connect")

    def _refresh_ports(self):
        # Rescan connected devices (serial ports) and repopulate the port combo.
        # Disabled while connected (no rescan on a held port).
        if self._serial_connected:
            return
        source = self._get_source()
        ports = self.worker.get_source_ports(source)
        self.ui.cBox_Port.clear()
        if ports is not None:
            self.ui.cBox_Port.addItems(ports)
        n = len(ports) if ports is not None else 0
        self.ui.label_COM_status.setText("Disconnected - {} port(s) found".format(n))
        self._set_status("disconnected", "Standby")
        self._set_message("ready to connect" if n else "no serial port found")
        print(TAG, "Serial ports refreshed: {} found".format(n))
        Log.i(TAG, "Serial ports refreshed: {} found".format(n))

    def _get_lock_file_path(self, port):
        # Build a filesystem-safe lock-file path for the given port
        safe_port_name = re.sub(r'[^A-Za-z0-9_.-]', '_', port)
        lock_dir = os.path.join(tempfile.gettempdir(), 'openqcm_locks')
        os.makedirs(lock_dir, exist_ok=True)
        return os.path.join(lock_dir, safe_port_name + '.lock')

    def _acquire_port_lock(self, port):
        # Level-1 lock (multi-instance protection). Windows COM ports are
        # natively exclusive, so the file lock is only needed on Unix.
        if sys.platform == 'win32':
            return True
        import fcntl
        lock_path = self._get_lock_file_path(port)
        try:
            self._lock_file = open(lock_path, 'w')
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file.write(str(os.getpid()))
            self._lock_file.flush()
            return True
        except (IOError, OSError):
            if self._lock_file:
                self._lock_file.close()
                self._lock_file = None
            return False

    def _release_port_lock(self):
        if sys.platform == 'win32':
            return
        if self._lock_file:
            try:
                import fcntl
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception as e:
                print(TAG, "Warning: error releasing port lock: {}".format(str(e)))
            self._lock_file = None

    def _toggle_serial_connection(self):
        # Connect or disconnect the serial port as an explicit action,
        # independent from the selected operation mode.
        if not self._serial_connected:
            # ---- CONNECT ----
            port = self.ui.cBox_Port.currentText()
            if not port:
                PopUp.warning(self, Constants.app_title, "No serial port selected!")
                return
            # Level 1: multi-instance lock file
            if not self._acquire_port_lock(port):
                self._set_status("err")
                self._set_message("port locked by another instance")
                PopUp.warning(self, Constants.app_title,
                              "Port [{}] is already in use by another openQCM instance!".format(port))
                return
            # Open the persistent, exclusive serial handle (held in Standby)
            try:
                self._open_serial_lock(port)
            except Exception as e:
                self._release_port_lock()
                self._serial_lock = None
                self._set_status("err")
                self._set_message("port busy or unavailable")
                PopUp.warning(self, Constants.app_title,
                              "Unable to open port [{}]:\n{}".format(port, str(e)))
                print(TAG, "Connection failed: {}".format(str(e)))
                return
            # Connected (Standby)
            self._serial_connected = True
            self._connected_port = port
            self.ui.pButton_Connect.setText("Disconnect")
            self.ui.pButton_Connect.setProperty("connected", True)
            self.ui.pButton_Connect.style().unpolish(self.ui.pButton_Connect)
            self.ui.pButton_Connect.style().polish(self.ui.pButton_Connect)
            self.ui.cBox_Port.setEnabled(False)
            self.ui.pButton_Refresh.setEnabled(False)
            self.ui.pButton_Start.setEnabled(True)
            self.ui.pButton_Tswitch_ON.setEnabled(True)
            self._enable_device_queries()
            self.ui.label_COM_status.setText("Connected: {}".format(port))
            self.ui.label_COM_status.setToolTip("Connected: {}".format(port))
            self._set_status("standby", "Standby")
            self._set_message("connected to {} (exclusive)".format(port))
            print(TAG, "Connected to serial port {}".format(port))
            Log.i(TAG, "Connected to serial port {}".format(port))
            # Firmware version check on connection (moved here from app startup)
            self.get_firmware_version(True)
            # VER 0.1.5b and the board's own identification number, silently:
            # it is printed on nothing else, so the GUI is where it becomes
            # visible at all.
            self._query_serial_number(auto_mode=True)
            # and the TEC controller's PID, which is volatile: after a power
            # cycle it holds the factory values whatever the file says
            self._align_pid_with_controller()
            # and the error register, so the temperature card starts locked if
            # the controller is in error, released if it is not
            self._refresh_tec_error_lock_from_device()
        else:
            # ---- DISCONNECT ----
            self._disconnect_serial()

    def _disconnect_serial(self, message="disconnected"):
        """Drop the persistent handle and put the window back in Disconnected.

        ⚠️ Lifted out of _toggle_serial_connection because the button is no
        longer the only thing that can end a connection: a firmware update
        re-enumerates the board and forfeits the handle without anyone
        pressing anything. Eleven widgets have to move together, and a
        second copy of that list is how a window ends up claiming Connected
        over a port that no longer exists.

        `message` reaches the status bar, so the reason survives to the
        operator instead of a bare "disconnected".
        """
        if self._serial_lock is not None:
            try:
                self._serial_lock.close()
            except Exception:
                pass
            self._serial_lock = None
        self._release_port_lock()
        self._serial_connected = False
        self._connected_port = None
        self.ui.pButton_Connect.setText("Connect")
        self.ui.pButton_Connect.setProperty("connected", False)
        self.ui.pButton_Connect.style().unpolish(self.ui.pButton_Connect)
        self.ui.pButton_Connect.style().polish(self.ui.pButton_Connect)
        self.ui.cBox_Port.setEnabled(True)
        self.ui.pButton_Refresh.setEnabled(True)
        self.ui.pButton_Start.setEnabled(False)
        self.ui.pButton_Tswitch_ON.setEnabled(False)
        self._enable_device_queries()
        self.ui.label_COM_status.setText("Disconnected")
        self._show_board_serial(None)
        self._set_status("disconnected", "Standby")
        self._set_message(message)
        print(TAG, "Disconnected from serial port ({})".format(message))
        Log.i(TAG, "Disconnected from serial port ({})".format(message))

    def _open_serial_lock(self, port):
        # Open the persistent, exclusive serial handle held by the GUI while
        # connected and idle (Standby). Configuration matches the former
        # per-query setup.
        self._serial_lock = serial.Serial()
        self._serial_lock.port = port
        self._serial_lock.baudrate = Constants.serial_default_speed
        self._serial_lock.stopbits = serial.STOPBITS_ONE
        self._serial_lock.bytesize = serial.EIGHTBITS
        self._serial_lock.timeout = Constants.serial_timeout_ms
        self._serial_lock.writetimeout = Constants.serial_writetimeout_ms
        try:
            self._serial_lock.exclusive = True
        except Exception:
            pass
        self._serial_lock.open()

    def _reacquire_serial_lock(self):
        # Re-open the persistent handle after the acquisition process released
        # the port (called on stop). No-op if not connected or already open.
        if not self._serial_connected:
            return
        if self._serial_lock is not None and self._serial_lock.isOpen():
            return
        try:
            self._open_serial_lock(self._connected_port)
            # VER 0.1.5c firmware 0.1.5c ends the sweep in progress on 'Q'.
            # On an older firmware the letter has no branch, so it is only sent
            # when the reported version is one that knows it.
            #
            # ⚠️ Measured at the bench 2026-09-01, and it does NOT shorten the
            # tail after a Stop: 7172 bytes drained with 'Q' and 7172 without,
            # the same to the byte. The reason is this method's position in the
            # sequence, not the firmware -- the parent regains the port only
            # after the child releases it, and the child releases it once the
            # board has finished sweeping, so the letter always arrives to an
            # idle board and those bytes are backlog already in the OS buffer.
            # The drain below is what actually recovers the port; 'Q' is kept
            # because it is the right primitive and costs one write, not
            # because it is doing anything here. A timely 'Q' would have to be
            # sent by the child, and could save at most the ~146 ms of readout
            # -- the 250 ms quiet window is unconditional -- which is why the
            # stop path has not been restructured around it.
            try:
                if _firmware_is_current(getattr(self, "_firmware_version", "")):
                    self._serial_lock.write(Constants.serial_stop_sweep)
                    print(TAG, "Stop-sweep sent to firmware {}".format(
                        self._firmware_version))
            except Exception as e:
                print(TAG, "Warning: stop-sweep command failed: {}".format(e))
        except Exception as e:
            print(TAG, "Warning: could not re-acquire serial port: {}".format(str(e)))
            Log.w(TAG, "Could not re-acquire serial port: {}".format(str(e)))
        finally:
            # ⚠️ Here, not in stop(): stop() calls _enable_ui BEFORE
            # worker.stop() and a second before the port comes back, so the
            # menu state it computes is a second out of date. Every path that
            # regains the port ends here -- Stop, a peak detection finishing,
            # an acquisition ending by itself -- so this is the one place that
            # sees the true state.
            self._enable_device_queries()

    def _serial_write(self, payload):
        # Write a command on the persistent connection. Requires an active
        # connection and no running acquisition (the child owns the port then).
        if not self._serial_connected or self._serial_lock is None:
            print(TAG, "Serial write skipped: not connected")
            return False
        if self.worker.is_running():
            print(TAG, "Serial write skipped: acquisition running")
            return False
        try:
            self._serial_lock.write(payload)
            return True
        except Exception as e:
            print(TAG, "Serial write error: {}".format(str(e)))
            Log.e(TAG, "Serial write error: {}".format(str(e)))
            return False

    def _drain_serial(self, quiet_ms=None, timeout_s=None):
        """Read and discard until the board stops talking.

        Returns DRAIN_QUIET, DRAIN_BUSY or DRAIN_LINK_LOST.

        ⚠️ reset_input_buffer() is not enough on its own. It empties what has
        arrived, not what is still coming, and the board keeps streaming the
        rest of its sweep after the host has stopped listening -- so a question
        asked right after a Stop comes back answered with amplitude;phase data,
        which the firmware check then reports as a version to update. This waits
        for a real silence instead.
        """
        if self._serial_lock is None:
            return DRAIN_LINK_LOST
        quiet = (Constants.serial_quiet_ms if quiet_ms is None else quiet_ms) / 1000.0
        limit = (Constants.serial_quiet_timeout_s if timeout_s is None else timeout_s)
        started = time.time()
        last_byte = time.time()
        dropped = 0
        while True:
            try:
                n = self._serial_lock.inWaiting()
            except Exception as e:
                return self._drain_link_lost(e, started)
            if n:
                try:
                    dropped += len(self._serial_lock.read(n))
                except Exception as e:
                    return self._drain_link_lost(e, started)
                last_byte = time.time()
            elif time.time() - last_byte >= quiet:
                if dropped:
                    # ⚠️ The elapsed time is what says where those bytes came
                    # from, and the count alone cannot. Backlog already sitting
                    # in the OS buffer reads out in a few ms and then the quiet
                    # window runs out the clock; a board still sweeping trickles
                    # bytes in for as long as it takes. Same count, opposite
                    # meaning -- and only the second case is one 'Q' can shorten.
                    print(TAG, "Drained {} bytes in {:.0f} ms ({:.0f} ms of it "
                          "waiting for silence) before the port went quiet"
                          .format(dropped, (time.time() - started) * 1000,
                                  (time.time() - last_byte) * 1000))
                return DRAIN_QUIET
            if time.time() - started > limit:
                print(TAG, "Port still busy after {:.0f} s ({} bytes drained)"
                      .format(limit, dropped))
                Log.w(TAG, "Port still busy after {:.0f} s".format(limit))
                return DRAIN_BUSY
            sleep(0.02)

    def _drain_link_lost(self, error, started):
        """The handle raised mid-drain: the device is gone, not busy.

        ⚠️ The elapsed time is the observable, and it is printed for that
        reason alone. A board still sweeping keeps the drain alive for the
        full 6 s timeout; a re-enumerated one raises on the first
        inWaiting(), in about a millisecond. Without the number in the log
        the two failures read the same, which is how one got reported as
        the other for a whole firmware update.
        """
        print(TAG, "Serial link lost after {:.0f} ms: {}"
              .format((time.time() - started) * 1000, str(error)))
        Log.w(TAG, "Serial link lost: {}".format(str(error)))
        return DRAIN_LINK_LOST

    def _serial_query(self, payload, wait=0.4):
        # Write a command on the persistent connection and read the reply.
        if not self._serial_connected or self._serial_lock is None:
            return ""
        # nothing sensible can be read while the board is still mid-sweep
        self._last_drain = self._drain_serial()
        try:
            self._serial_lock.reset_input_buffer()
            self._serial_lock.write(payload)
            sleep(wait)
            n = self._serial_lock.inWaiting()
            data = self._serial_lock.read(n).decode(Constants.app_encoding)
            sleep(wait)
            return data
        except Exception as e:
            print(TAG, "Serial query error: {}".format(str(e)))
            Log.e(TAG, "Serial query error: {}".format(str(e)))
            return ""

    ###########################################################################
    # Configures the connections between signals and UI elements
    ###########################################################################
    def _configure_signals(self):

        # VER 0.1.6b set up the serial connection feature (button + state)
        self._setup_serial_connection_ui()

        # Phase 3a: single Start/Stop toggle — pButton_Start drives both; Stop hidden.
        self.ui.pButton_Start.setStyleSheet("")   # drop inline style so theme QSS (#pButton_Start) applies
        self.ui.pButton_Start.clicked.connect(self._toggle_start_stop)
        self.ui.pButton_Stop.hide()
        self.ui.pButton_Clear.clicked.connect(self.clear)
        self.ui.pButton_Autoscale.clicked.connect(self.autoscale)
        self.ui.pButton_NScale.toggled.connect(self._set_nscale)
        # single Set/Clear Reference toggle (pButton_Reference_Not is hidden)
        self.ui.pButton_Reference.clicked.connect(self._toggle_reference)
        self.ui.pButton_Reference_Not.clicked.connect(self.reference_not)

        # TODO delete sample box
        # self.ui.sBox_Samples.valueChanged.connect(self._update_sample_size)

        self.ui.cBox_Source.currentIndexChanged.connect(self._source_changed)
        self.ui.pButton_Temperature_Set.clicked.connect(self.temperatureSet)

        # VER 0.1.4
        # add changed sampling data file function 
        self.ui.cBox_sampling_time.currentIndexChanged.connect(self._datalog_sampling_time_changed)

        # Temperature control button
        # GUI: single Temperature control ON/OFF toggle. pButton_Tswitch_ON is
        # repurposed as the toggle; the separate OFF button is hidden.
        self.ui.pButton_Tswitch_ON.clicked.connect(self._toggle_temperature_control)
        self.ui.pButton_Tswitch_OFF.hide()
        self._update_tec_toggle()
        # gated on the serial connection: disabled/grey until connected
        self.ui.pButton_Tswitch_ON.setEnabled(self._serial_connected)
        
        
        # VER 0.1.4
        # TEC controller reset button
        self.ui.pButton_TEC_Reset.clicked.connect(self._TEC_Reset_button)

        # Frequency scan selector
        self.ui.radioBtn_F0.clicked.connect(self._update_scan_selector)
        self.ui.radioBtn_F3.clicked.connect(self._update_scan_selector)
        self.ui.radioBtn_F5.clicked.connect(self._update_scan_selector)
        self.ui.radioBtn_F7.clicked.connect(self._update_scan_selector)
        self.ui.radioBtn_F9.clicked.connect(self._update_scan_selector)

        '''
        #--------
        self.InfoWin.ui3.pButton_Download.clicked.connect(self.start_download)
        '''
        '''
        TODO 2m
        connect start download
        
        '''
        
        '''
        # Buttons removed. Action moved in the menu bar

        # DEV RAWDATA
        self.ui.rawData_btn.clicked.connect(self._raw_data_plot)
        
        # VER 0.1.6 push button for TEC current data plot secondary window 
        self.ui.pButtonSecondWindow.clicked.connect(self.open_second_window)
        '''
    
    # Live Raw Data View: reads the acquisition buffers in memory, never a file.
    def current_single_overtone(self):
        """Single-frequency mode: index of the overtone being interrogated
        (0 = fundamental, the slot the acquisition fills); None in multiscan.
        Same mapping as the F1..F9 chips: cBox_Speed lists the overtones
        highest first."""
        if self._get_source() != SourceType.serial:
            return None
        count = self.ui.cBox_Speed.count()
        if not count:
            return None
        return count - 1 - self.ui.cBox_Speed.currentIndex()

    def _open_raw_data_view(self):
        from openQCM.ui.rawDataView import RawDataViewDialog

        # already open: raise it instead of stacking a second timer on the same
        # buffers
        if self._raw_data_view is not None:
            self._raw_data_view.raise_()
            self._raw_data_view.activateWindow()
            return

        dialog = RawDataViewDialog(self, theme_name=self._theme, parent=self)
        # WA_DeleteOnClose means the C++ object is gone after the close; drop our
        # reference with it, or closeEvent below would touch a dead object
        dialog.destroyed.connect(self._forget_raw_data_view)
        self._raw_data_view = dialog
        dialog.show()

    def _forget_raw_data_view(self, *_args):
        self._raw_data_view = None

    # Peak Data View: a snapshot of the last Peak Detection, read from the
    # calibration files. Not a live view -- Peak Detection runs once and writes
    # them -- so it is loaded on open and never polled.
    def _open_peak_data_view(self):
        from openQCM.ui.peakDataView import (PeakDataViewDialog,
                                             latest_calibration_path)

        if self._peak_data_view is not None:
            self._peak_data_view.raise_()
            self._peak_data_view.activateWindow()
            return

        calibration = latest_calibration_path()
        peaks = Constants.cvs_peakfrequencies_path
        if calibration is None or not os.path.exists(peaks):
            PopUp.warning(self, "Peak Data View",
                          "No calibration data found.\n"
                          "Run Peak Detection first.")
            return

        dialog = PeakDataViewDialog(theme_name=self._theme, parent=self)
        if not dialog.load(calibration, peaks):
            # the dialog says what went wrong in its own label; a window showing
            # only an error message is worse than none
            PopUp.warning(self, "Peak Data View", dialog.info.text())
            dialog.deleteLater()
            return
        dialog.destroyed.connect(self._forget_peak_data_view)
        self._peak_data_view = dialog
        dialog.show()

    def _forget_peak_data_view(self, *_args):
        self._peak_data_view = None

    # File > Open Log…: pick a datalog and plot it. Unlike the other views this
    # one is NOT a singleton -- comparing two runs side by side is the reason to
    # open a log at all -- so every invocation makes a new window and the list
    # only exists to close them with the application.
    def _open_datalog_view(self):
        # This module imports QtCore and QtGui only, never QtWidgets: the widgets
        # are reachable as QtGui.* solely because pyqtgraph's Qt.py copies them
        # there for Qt4 compatibility. Import the dialog explicitly rather than
        # leaning on that side effect -- which is what Q-1 does at the same spot.
        try:
            from PyQt5.QtWidgets import QFileDialog
        except ImportError:                       # pragma: no cover
            from PySide2.QtWidgets import QFileDialog
        from openQCM.ui.dataLogView import DataLogViewDialog

        path, _filter = QFileDialog.getOpenFileName(
            self, "Open datalog", Constants.csv_export_path,
            "openQCM datalog (*.csv);;All files (*)")
        if not path:
            return

        dialog = DataLogViewDialog(theme_name=self._theme, parent=self)
        if not dialog.load(path):
            PopUp.warning(self, "Open Log", dialog.info.text())
            dialog.deleteLater()
            return
        dialog.destroyed.connect(
            lambda *_a, d=dialog: self._forget_datalog_view(d))
        self._datalog_views.append(dialog)
        dialog.show()

    def _forget_datalog_view(self, dialog):
        self._datalog_views = [d for d in self._datalog_views if d is not dialog]

    def _close_datalog_views(self):
        views, self._datalog_views = self._datalog_views, []
        for dialog in views:
            try:
                dialog.close()
            except RuntimeError:
                pass

    def _close_peak_data_view(self):
        dialog = self._peak_data_view
        self._peak_data_view = None
        if dialog is None:
            return
        try:
            dialog.close()
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Tools > PID Control: the TEC controller's loop parameters
    # ------------------------------------------------------------------
    # Two paths to the controller, and a number that tells them apart.
    # Standby: the GUI holds the port, sends C/P/I/D itself and then asks the
    # controller C? P? I? D? -- the four values it reports are shown in the
    # window, so "set" means "read back", not "written". Acquisition running:
    # the child process owns the port; the values go into config.txt, which
    # `_Temperature_PID_control` re-reads at every sweep and forwards, and
    # each parameter it actually sends is printed by the process. Nothing here
    # touches the temperature set-point or the two flags in that file: the old
    # PID Set raised the flag that re-sends the temperature, for no reason.
    def _open_pid_control(self):
        from openQCM.ui.pidControlDialog import PIDControlDialog

        if self._pid_control is not None:
            self._pid_control.raise_()
            self._pid_control.activateWindow()
            return

        dialog = PIDControlDialog(self._read_pid_config(),
                                  theme_name=self._theme, parent=self)
        dialog.apply_requested.connect(self._apply_pid)
        dialog.read_requested.connect(self._read_pid)
        dialog.destroyed.connect(self._forget_pid_control)
        self._pid_control = dialog
        self._sync_pid_control()
        dialog.show()

    def _forget_pid_control(self, *_args):
        self._pid_control = None

    def _close_pid_control(self):
        dialog = self._pid_control
        self._pid_control = None
        if dialog is None:
            return
        try:
            dialog.close()
        except RuntimeError:
            pass

    def _sync_pid_control(self):
        """Values from config.txt, Set PID enabled iff a board is connected."""
        dialog = getattr(self, "_pid_control", None)
        if dialog is None:
            return
        try:
            dialog.set_values(*self._read_pid_config())
            dialog.set_device_state(self._serial_connected,
                                    self.worker is not None and self.worker.is_running())
        except RuntimeError:
            self._pid_control = None

    def _read_pid_config(self):
        """(C, P, I, D) as config.txt holds them; the defaults if it cannot be read."""
        try:
            param = loadtxt(Constants.manual_frequencies_path)
            return tuple(int(param[k]) for k in (1, 2, 3, 4))
        except Exception as e:
            print(TAG, "config.txt unreadable, showing the PID defaults: {}".format(e))
            return (Constants.cycling_time_default, Constants.P_share_default,
                    Constants.I_share_default, Constants.D_share_default)

    def _write_pid_config(self, cycling, p_share, i_share, d_share):
        """Rows 1-4 of config.txt; the set-point and the two flags stay as they are."""
        _path = Constants.manual_frequencies_path
        param = loadtxt(_path)
        np.savetxt(_path, np.row_stack([param[0], cycling, p_share, i_share,
                                        d_share, param[5], param[6]]), fmt='%d')

    # -- shared by Set PID and the connect-time alignment -----------------
    @staticmethod
    def _pid_text(values):
        """(C, P, I, D) -> 'C50 P500 I50 D300'; None prints as '?'."""
        return " ".join("{}{}".format(k, "?" if v is None else int(v))
                        for k, v in zip("CPID", values))

    def _query_pid(self):
        """Ask the controller C? P? I? D?; a value it did not answer is None.

        Returns None as a whole when the board is still streaming sweep data,
        because then nothing it says is an answer to these questions.
        """
        reported = []
        for key in "CPID":
            reply = _first_reply_line(self._serial_query(
                "{}?\n".format(key).encode(), wait=0.2))
            if self._board_busy(reply):
                return None
            try:
                reported.append(int(reply))
            except ValueError:
                reported.append(None)
        return tuple(reported)

    def _send_pid(self, values):
        """Write C/P/I/D on the idle port; the first failed write ends it."""
        for key, value in zip("CPID", values):
            sleep(0.1)
            if not self._serial_write("{}{}\n".format(key, int(value)).encode()):
                return False
        return True

    def _pid_dialog_status(self, text):
        dialog = self._pid_control
        if dialog is not None:
            try:
                dialog.show_status(text)
            except RuntimeError:
                pass

    def _apply_pid(self, cycling, p_share, i_share, d_share):
        wanted = (int(cycling), int(p_share), int(i_share), int(d_share))
        sent = self._pid_text(wanted)

        def status(text):
            print(TAG, "PID Control: {}".format(text))
            Log.i(TAG, "PID Control: {}".format(text))
            self._pid_dialog_status(text)

        try:
            self._write_pid_config(*wanted)
        except Exception as e:
            status("could not write config.txt ({}); nothing sent.".format(e))
            return

        if self.worker is not None and self.worker.is_running():
            status("{} saved. The acquisition owns the port: it sends every "
                   "changed parameter at its next sweep, and prints each one "
                   "in the console as 'PID sent to the controller'.".format(sent))
            return

        if not self._can_query_device():
            status("{} saved to config.txt only: the port is not available, "
                   "nothing was sent.".format(sent))
            return

        if not self._send_pid(wanted):
            status("{}: a write failed, see the console.".format(sent))
            return

        # read back: the observable that separates "written" from "accepted"
        reported = self._query_pid()
        if reported is None:
            status("Sent {}. The board is still sending measurement data, the "
                   "read-back was skipped.".format(sent))
            return
        shown = self._pid_text(reported)
        wrong = [k for k, w, r in zip("CPID", wanted, reported) if r != w]
        if not wrong:
            status("Sent {}. Controller reports {}: all four match.".format(sent, shown))
        elif all(r is None for r in reported):
            status("Sent {}. The controller did not answer the read-back "
                   "({}): is the TEC controller powered?".format(sent, shown))
        else:
            status("Sent {}. Controller reports {}: MISMATCH on {}.".format(
                sent, shown, ", ".join(wrong)))

    def _read_pid(self):
        """Read PID: show what the controller holds. Nothing is written.

        Standby: the GUI asks the port itself. Acquisition running: the child
        owns the port, so the request is raised on the parser and the process
        answers between two sweeps; the answer comes back through the worker
        and lands in _update_plot, which calls _show_pid_reported.
        """
        if self.worker is not None and self.worker.is_running():
            if self.worker.request_pid_read():
                self._pid_status("asked; the acquisition reads the controller at "
                                 "the end of the current sweep.")
            else:
                self._pid_status("cannot ask: the acquisition is not ready yet.")
            return
        if not self._can_query_device():
            self._pid_status("cannot read now: the port is not available to the GUI.")
            return
        reported = self._query_pid()
        if reported is None:
            self._pid_status("the board is still sending measurement data; try "
                             "again in a moment.")
            return
        self._show_pid_reported(reported, "read now")

    def _pid_status(self, text):
        print(TAG, "PID Control: {}".format(text))
        Log.i(TAG, "PID Control: {}".format(text))
        self._pid_dialog_status(text)

    def _show_pid_reported(self, reported, via):
        """Put a controller answer in the window and say how it compares to the file."""
        if any(v is None for v in reported):
            self._pid_status("the controller did not answer ({}, {}). Is the TEC "
                             "controller powered?".format(self._pid_text(reported), via))
            return
        dialog = self._pid_control
        if dialog is not None:
            try:
                dialog.set_values(*reported)
            except RuntimeError:
                pass
        in_file = tuple(self._read_pid_config())
        if tuple(reported) == in_file:
            self._pid_status("Controller reports {} ({}): same as config.txt.".format(
                self._pid_text(reported), via))
        else:
            self._pid_status("Controller reports {} ({}), config.txt has {}. Shown, "
                             "not saved: Set PID makes these the file's values.".format(
                                 self._pid_text(reported), via, self._pid_text(in_file)))

    def _align_pid_with_controller(self):
        """On connect: make the controller hold what config.txt holds.

        The MTD415T is volatile -- after a power cycle it has its factory
        values whatever anyone set before -- so the file is the memory and the
        alignment goes software -> machine, the same direction START has
        always taken at its first sweep. What the controller had, what it was
        set to and what it reads back afterwards all go to the log: one line,
        with the numbers, is how this stays verifiable.
        """
        if not self._can_query_device():
            return

        def report(text):
            print(TAG, "PID on connect: {}".format(text))
            Log.i(TAG, "PID on connect: {}".format(text))
            self._pid_dialog_status(text)

        wanted = tuple(self._read_pid_config())
        had = self._query_pid()
        if self._link_lost():
            report("link lost while asking the controller; nothing sent.")
            return
        if had is None:
            report("the board is still sending measurement data; nothing sent.")
            return
        if all(v is None for v in had):
            report("the TEC controller did not answer ({}); nothing sent. Is it "
                   "powered?".format(self._pid_text(had)))
            return
        if had == wanted:
            report("aligned, controller reports {}.".format(self._pid_text(had)))
            return

        if not self._send_pid(wanted):
            report("controller had {}, write of {} failed, see the console.".format(
                self._pid_text(had), self._pid_text(wanted)))
            return
        back = self._query_pid()
        if back is None or all(v is None for v in back):
            report("controller had {}, set to {}, read back: no answer.".format(
                self._pid_text(had), self._pid_text(wanted)))
        elif back == wanted:
            report("controller had {}, set to {}, read back: match.".format(
                self._pid_text(had), self._pid_text(wanted)))
        else:
            report("controller had {}, set to {}, read back {}: MISMATCH.".format(
                self._pid_text(had), self._pid_text(wanted), self._pid_text(back)))

    def _close_raw_data_view(self):
        """Called from the main closeEvent; the dialog may already be gone."""
        dialog = self._raw_data_view
        self._raw_data_view = None
        if dialog is None:
            return
        try:
            dialog.close()
        except RuntimeError:
            # the underlying C++ object was already deleted
            pass

    # VER 0.1.4
    # add-on view sweep raw data plot
    def _raw_data_plot(self):
        # VER 0.1.6 Try-except code block to prevent the software from freezing when calling the raw data plot

        # Development viewer, reading sweep_data/*.txt. Imported here, not at
        # module level, so that a production tree without that dump (and the
        # package that plots it) still starts; the menu entry that reaches
        # this method is hidden unless the sweep dump is enabled.
        from openQCM.sweep_data import plot_sweep_spline

        # multiscan mode 
        if  (self._get_source() == SourceType.multiscan):
            try:
                plot_sweep_spline.script()
            except Exception as e:
                print ("Warning: unable to plot raw data in multiscn mode.")
                print(f"error occurred: {e}")
        
        # else if single mode 
        elif (self._get_source() == SourceType.serial):
            try:
                overtone_nn = self._overtones_number_all - self.ui.cBox_Speed.currentIndex() - 1
                plot_sweep_spline.script_single(overtone_nn)
            except Exception as e:
                print ("Warning: unable to plot raw data in single mode ")
                print(f"error occurred: {e}")
            
    # VER 0.1.4
###########################################################################
    # Updates the sample size of the plot (now not used)
    ###########################################################################
    def _update_sample_size(self):

        # This function is connected to the valueChanged signal of the sample Spin Box.
        if self.worker is not None:
            self.worker.reset_buffers(Constants.argument_default_samples)

    ###########################################################################
    # Updates and redraws the graphics in the plot.
    ###########################################################################
    def _update_plot(self):

        # This function is connected to the timeout signal of a QTimer
        self.worker.consume_queue1()
        self.worker.consume_queue2()
        self.worker.consume_queue3()
        self.worker.consume_queue4()
        # TODO note that data is logged here, when self.worker.consume_queue5() is called
        self.worker.consume_queue5()
         
        # VER 0.1.6 consume TEC current queue 
        self.worker.consume_queueCurrentTec()
        
        # general error queue
        self.worker.consume_queue6()
        # lines from the acquisition process for the System Log
        self.worker.consume_queue_message()
        # a Read PID the acquisition process was asked to make
        self.worker.consume_queue_pid()
        reported = self.worker.pop_pid_reported()
        if reported is not None:
            self._show_pid_reported(reported, "read by the acquisition between sweeps")

        self.worker.consume_queue_F_multi()
        self.worker.consume_queue_D_multi()

        self.worker.consume_queue_A_multi()
        # The phase sweep has to be drained whether anything draws it or not:
        # MultiscanProcess fills its queue on every sweep.
        self.worker.consume_queue_P_multi()


        # VER 0.1.4 get time elapsed 
# =============================================================================
#         print ("THE TIMER IS NOW ")
#         print (self.worker.get_time_elapsed())
# =============================================================================
        # ⚠️ Two different quantities under two different labels, and they used
        # to be one. get_time_elapsed() is the sampling INTERVAL -- seconds
        # between datalog writes -- which is exactly what the status bar's "S:"
        # means, and never what the sidebar's "Time elapsed" promised. The
        # sidebar now reads the run's own clock.
        sampling_value = float("{0:.1f}".format(self.worker.get_time_elapsed()))
        elapsed_value = float("{0:.1f}".format(self.worker.get_run_elapsed()))
        self.ui.time_indicator.setText(str(elapsed_value))
        # R2: bottom-bar sampling-interval mirror
        self.ui.statusSampValue.setText("S: {} s".format(sampling_value))

        #### SINGLE check 
        # --------------------------------------------------------------------
        if  self._get_source() == SourceType.serial:
            vector1 = self.worker.get_d1_buffer()
            vector2 = self.worker.get_d2_buffer()
            # VER 0.1.6 update temperature data plot using setData, round to 2 decimals
            vectortemp = self.worker.get_d3_buffer().round(decimals = 1)

            # TODO changed the get error number of elemts
            # self._ser_error1,self._ser_error2, self._ser_control,self._ser_err_usb = self.worker.get_ser_error()
            self._ser_error1, self._ser_error2, self._ser_control,self._ser_err_usb, self._overtone_number = self.worker.get_ser_error()
            
            # VER 0.1.4
            # get TEC status current value 
            self._TEC_status = self.worker.get_TEC_status()
            # update TEC status 
            self._update_TEC_status(self._TEC_status)
            self._update_tec_error_lock(self.worker.get_TEC_error_register())

            #print(self._ser_err_usb, end='\r')
            #if self._ser_err_usb <=1:
            if vector1.any:
               # progressbar
               if self._ser_control<=Constants.environment:
                   self._completed = self._ser_control * 100 / Constants.environment

               # VER 0.1.6 the axis origin is the first DISPLAYED datum, in
               # epoch microseconds -- the unit the axes plot in.
               #
               # ⚠️ This replaces np.nanmin(t1_buffer), which was the oldest
               # timestamp in the buffer and therefore sweep 0. Serial.elaborate
               # pushes a timestamp on EVERY sweep but a NaN value until
               # `_k >= environment`, so the oldest timestamp belongs to a
               # sample that is never drawn, and the first point that IS drawn
               # landed at `environment x sweep_period` on the axis: measured at
               # 4-6 s with environment = 3, and 15-20 s with 10.
               #
               # ⚠️ nanmin was a deliberate choice, recorded in HANDOFF S3, on
               # the reading that zero means "acquisition started". It is
               # reversed on purpose: zero now means "first measurement shown",
               # which is what multiscan has always done a few hundred lines
               # below -- it takes buffer[0], the newest sample, at exactly the
               # moment the warm-up ends. The two modes agreed on the wording
               # and disagreed on the instant.
               #
               # Retried every tick until a datum exists, rather than fired once
               # on `_ser_control == environment`: the counter and the data
               # arrive on different queues, so the tick that sees the counter
               # need not be the tick that sees the sample.
               if self.start_time is None:
                   origin = self._first_valid_timestamp(
                       vector1, self.worker.get_t1_buffer())
                   if origin is not None:
                       self.start_time = origin
                       self._xaxis.set_start_time(origin)
                       self._xaxisD.set_start_time(origin)
                       self._xaxisT.set_start_time(origin)

               if str(vector1[0])=='nan' and not self._ser_error1 and not self._ser_error2:
                  label1 = 'processing...'
                  label2 = 'processing...'
                  label3 = 'processing...'
                  labelstatus = 'Processing'
                  self.ui.statusIndicator.setStyleSheet(self._status_dot("warn")) #ff8000

                  labelbar = 'processing early data...'

               elif (str(vector1[0])=='nan' and (self._ser_error1 or self._ser_error2)):
                      if self._ser_error1 and self._ser_error2:
                        label1= ""
                        label2= ""
                        label3= ""
                        labelstatus = 'Warning'
                        labelbar = 'Warning: -3dB frequencies not found'
                        self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))

                      elif self._ser_error1:
                        label1= ""
                        label2= ""
                        label3= ""
                        labelstatus = 'Warning'
                        labelbar = 'Warning: lower -3dB frequency not found'
                        # self.ControlsWin.ui1.infostatus.setStyleSheet(self._status_dot("err"))
                      elif self._ser_error2:
                        label1= ""
                        label2= ""
                        label3= ""
                        labelstatus = 'Warning'
                        labelbar = 'Warning: upper -3dB frequency not found'
                        self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))
               else:
                  if not self._ser_error1 and not self._ser_error2:
                      if not self._reference_flag:
                          d1=float("{0:.2f}".format(vector1[0]))
                          d2=float("{0:.4f}".format(vector2[0]*1e6))
                          d3=float("{0:.2f}".format(vectortemp[0]))
                      else:
                          a1= vector1[0]-self._reference_value_frequency
                          a2= vector2[0]-self._reference_value_dissipation
                          d1=float("{0:.2f}".format(a1))
                          d2=float("{0:.4f}".format(a2*1e6))
                          d3=float("{0:.2f}".format(vectortemp[0]))
                      label1= str(d1)+ " Hz"
                      label2= str(d2)+ "e-06"
                      label3= str(d3)+ " °C"
                      labelstatus = 'Monitoring'
                      labelbar = 'Monitoring!'
                      self.ui.statusIndicator.setStyleSheet(self._status_dot("ok"))

                  else:
                      if self._ser_error1 and self._ser_error2:
                        label1= "-"
                        label2= "-"
                        label3= "-"
                        labelstatus = 'Warning'
                        labelbar = 'Warning: -3dB frequencies not found'
                        self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))

                      elif self._ser_error1:
                        label1= "-"
                        label2= "-"
                        label3= "-"
                        labelstatus = 'Warning'
                        labelbar = 'Warning: lower -3dB frequency not found'
                        self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))

                      elif self._ser_error2:
                        label1= "-"
                        label2= "-"
                        label3= "-"
                        labelstatus = 'Warning'
                        labelbar = 'Warning: upper -3dB frequency not found'
                        self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))
               
               self.ui.infostatus.setText(labelstatus)
               self.ui.infobar.setText(labelbar)
               # progressbar
               self.ui.progressBar.setValue(self._completed)

            #elif self._ser_err_usb >1:
                # PopUp.warning(self, Constants.app_title, "Warning: USB cable device disconnected!")
                # self.stop()
            
            # VER 0.1.6 BUG coreection sweep range x-axis get the current frequency range 
            # use a try-except code block. If an error is encountered when opening the file, use the global value and continue.
            try: 
                self._readFREQ = self.worker.get_frequency_range()
            except Exception as e:
                # print(f"An error occurred: {e}")
                pass

        #### CALIBRATION check
        # ---------------------------------------------------------------------
    
        elif self._get_source() == SourceType.calibration:
            # flag for terminating calibration
            stop_flag = 0
            # VER 0.1.6 DEBUG check the stop flag variable 
            pre_stop_flag = stop_flag
            
            # VER 0.1.6 user cancellation (ported from openQCM Q-1 v3.0): if the
            # user pressed Stop mid-sweep, CalibrationProcess emitted the -1
            # sentinel and the worker latched it — tear down cleanly, once.
            # The Stop button is intentionally left ENABLED during peak detection
            # (it used to be disabled here) so the procedure can be cancelled.
            if self.worker.is_calibration_cancelled():
                if self._timer_plot.isActive():   # guard: run the teardown once
                    self.stop()
                return

            # get additional error flag 
            vector1 = self.worker.get_value1_buffer()
            # vector2[0] and vector3[0] flag error
            vector2 = self.worker.get_t3_buffer()
            # VER 0.1.6 update temperature data plot using setData, rounding to one decimal place
            vector3 = self.worker.get_d3_buffer().round(decimals = 1)
            
            #print(vector1[0],vector2[0],vector3[0])
            label1 = 'not available'
            label2 = 'not available'
            label3 = 'not available'
            labelstatus = 'Peak Detection Processing'
            labelbar = 'please wait...'

            self.ui.statusIndicator.setStyleSheet(self._status_dot("warn"))

            # request the error data from Worker.py
            error1, error2, error3, self._ser_control, self._overtone_number = self.worker.get_ser_error()
                    
            # VER 0.1.4
            # get TEC status current value
            self._TEC_status = self.worker.get_TEC_status()
            # update TEC status
            self._update_TEC_status(self._TEC_status)
            self._update_tec_error_lock(self.worker.get_TEC_error_register())
            
            # progressbar update 
            if self._ser_control < (Constants.calib_sections):
                      self._completed = (self._ser_control/(Constants.calib_sections))*100 
            
            # CHECK THE STATUS ERROR
            # -----------------------------------------------------------------
            # EXCEPTION: Calibration buffer empty
            #if vector1[0]== 0 and vector3[0]==1:
            if error1 == 1 and vector3[0] == 1:
              label1 = 'not available'
              label2 = 'not available'
              label3 = 'not available'
              labelstatus = 'Calibration Warning'
              self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))
              labelbar = 'empty buffer - reconnect the device and retry'
              # set stop flag True
              stop_flag = 1
              
            # EXCEPTION: Calibration buffer empty and ValueError from the serial port
            elif error1 == 1 and vector2[0] == 1:
              label1 = 'not available'
              label2 = 'not available'
              label3 = 'not available'
              labelstatus = 'Calibration Warning'
              self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))
              labelbar = 'empty buffer / value error - reconnect the device and retry'
              # set stop flag True
              stop_flag=1
            
            # NOT EXCEPTION: Calibration buffer not empty
            elif error1 == 0:
              
              label1 = 'not available'
              label2 = 'not available'
              label3 = 'not available'
              labelstatus = 'Peak Detection Processing'
              labelbar = 'please wait...'
              
              # CALIBRATION SUCCESS 
              # ---------------------------------------------------------------
              if vector2[0] == 0 and vector3[0] == 0:
                 labelstatus = 'Calibration Success'
                 self.ui.statusIndicator.setStyleSheet(self._status_dot("ok"))
                 labelbar = 'peak detection completed - ready for baseline correction'
                 
                 # Set the boolean stop flag True to stop the loop                   
                 stop_flag = 1
                 
              elif vector2[0] == 1 or vector3[0] == 1:
                 labelstatus = 'Calibration Warning'
                 self.ui.statusIndicator.setStyleSheet(self._status_dot("err"))

                 if vector2[0]== 1:
                   labelbar = 'signal acquisition error - retry'
                   stop_flag=1 ##
                 elif vector3[0]== 1:
                     
                   PopUp.warning_not_blocking(self, "Peak Detection", "WARNING: unable to identify fundamental peak. Please, repeat the calibration")
                   
                   labelbar = 'peak not found - retry'
                   stop_flag=1 ##
            
            self.ui.infostatus.setText(labelstatus)
            self.ui.infobar.setText(labelbar)
            
            # progressbar -------------
            self.ui.progressBar.setValue(self._completed + 10)
            
            # terminate the  calibration (simulate clicked stop)
            if stop_flag == 1:
               
               # VER 0.1.6 make a pop-up window at the end of calibration
               sleep(1.0)
               # make a pop up window at the end of the calibration 
               if vector2[0]== 0 and vector3[0]== 0:
                   # get peak 
                   data  = loadtxt(Constants.cvs_peakfrequencies_path)
                   peaks_mag = data[:,0]
                   # slect the quart sensor at 5 MHz 
                   if ((peaks_mag[0]>4e+06 and peaks_mag[0]<6e+06)):
                       label = "5 MHz"
                   # slect the quartz sensor at 10 MHz     
                   elif ((peaks_mag[0]>9e+06 and peaks_mag[0]<11e+06)):
                       label = "10 MHz"   
                   # VER 0.1.6 TODO generalize to other quartz sensors 
                   
                   
                   # pop-up info on peak detection
                   PopUp.info_exec_rtf(self, "Peak Detection", "Fundamental Frequency = " +  label + "<br>" + 
                                               "Number of overtones detected = " + str(len(peaks_mag)) + "<br>" + 
                                               "Frequency detected = " + str(peaks_mag))
               
               if vector3[0] == 1:
                 # pop-up warning on peak detection
                 PopUp.warning_blocking(self, "Peak Detection", "WARNING: unable to identify fundamental peak. Please, repeat the calibration")    
                
               # VER 0.1.6 stop the timer and the worker
# =============================================================================
#                sleep(1.0)  
# =============================================================================
               self._timer_plot.stop()
               self._enable_ui(True)
               # VER 0.1.5c a peak detection ends here, not through stop(), so
               # this is the only place that can give the port back to the GUI.
               # Without it the two device queries stay greyed out until the
               # user disconnects and reconnects.
               self._reacquire_serial_lock()
               self.worker.stop()
               
               time.sleep(1)
               
               # reset stop flag 
               stop_flag = 0
               
        #### MULTISCAN check
        # ---------------------------------------------------------------------
        elif self._get_source() == SourceType.multiscan:
            vector1 = self.worker.get_d1_buffer()

            # TODO update plot
            self._ser_error1, self._ser_error2, self._ser_control, self._ser_err_usb, self._overtone_number = self.worker.get_ser_error()
        
# =============================================================================
#             # TODO DEBUG STOP SOFTWARE
#             if self._ser_error1:
#                 print ("WARNING:: general error of kind #1 ")
#             if self._ser_error2:
#                 print ("WARNING:: general error of kind #2 ")
#             if self._ser_err_usb:
#                 print("WARNING: Main Window general error on serial ")
# =============================================================================

            # VER 0.1.4
            # get TEC status current value
            self._TEC_status = self.worker.get_TEC_status()
            # update TEC status 
            self._update_TEC_status(self._TEC_status)
            self._update_tec_error_lock(self.worker.get_TEC_error_register())

            if vector1.any:
               # progressbar
               # VER 0.1.6 minus 
               if self._ser_control <= Constants.environment:
                  # VER 0.1.2 just a little thing  
                  self._completed = self._ser_control * 100 / Constants.environment
                  
                  # VER 0.1.2
                  # Optimize and update infobar and infostatus in multiscan mode
                  labelstatus = 'Processing'
                  labelbar = 'processing early data...'
                  self._set_status("warn", labelstatus)
                  self._set_message(labelbar)

               # progressbar
               self.ui.progressBar.setValue(self._completed)
               
            if self._ser_control == Constants.environment:
                
                # VER 0.1.6 TODO set the start time using the time axis buffer 
                
                # 1 option 
# =============================================================================
#                 # VER 0.1.6 save the start time 
#                 # self.start_time = time.time()  
#                 import datetime
#                 epoch= datetime.datetime(1970, 1, 1, 0, 0)
#                 self.start_time = (datetime.datetime.now() - epoch).total_seconds()
#                 self._xaxis.start_time = self.start_time
#                 # print (self.start_time)
#                 # set the start time on the x-axis
# =============================================================================
                
                # VER 0.1.6 TODO
                
                # 2 option 
                
                # Iterate over each overtone and update time_axis_new
                for idx in range(self._overtones_number_all):
                    buffer = self.worker.get_time_values_buffer(idx)
                    # Check if the buffer is not empty and the first element is not NaN
                    if buffer.size > 0 and not np.isnan(buffer[0]): 
                        # Assuming the buffer is a list-like structure and you want the first element
                        self._time_axis_new[idx] = buffer[0]
                    
                # Set start_time to the smallest value in time_axis_new
                self.start_time = np.nanmin(self._time_axis_new)
                
                # VER 0.1.6 clear plt reset buffer at the end of processing early data
                # TODO not necessary to clear here ?
                self.clear()
                
                # VER 0.1.6 TODO wait ?
                
                # VER 0.1.6 set the start time after the clear
                self._xaxis.set_start_time(self.start_time)
                self._xaxisD.set_start_time(self.start_time)
                self._xaxisT.set_start_time(self.start_time)
                
                # VER 0.1.2
                # Optimize and update infobar and infostatus in multiscan mode
                labelstatus = 'Monitoring'
                labelbar = 'Monitoring!'
                self._set_status("ok", labelstatus)
                self._set_message(labelbar)
            
            # VER 0.1.6 check bandwidth error 
            if self._ser_control > Constants.environment:
               
                if (self._ser_error1 or self._ser_error2):
                  labelstatus = 'Warning'
                  labelbar = f'Warning: bandwidth not measurable on F{2*self._overtone_number + 1}'
                  self._set_status("warn", labelstatus)
                  self._set_message(labelbar)
                
                else: 
                    # VER 0.1.2
                    # Optimize and update infobar and infostatus in multiscan mode
                    labelstatus = 'Monitoring'
                    labelbar = 'Monitoring!'
                    self._set_status("ok", labelstatus)
                    self._set_message(labelbar)
                    

        #### REFERENCE SET
        # ---------------------------------------------------------------------
        if self._reference_flag:

            #### SINGLE Reference set
            # -----------------------------------------------------------------
            if self._get_source() == SourceType.serial:

# =============================================================================
#                 self._plt2.setLabel('left', 'Resonance Frequency', units='Hz', color=Constants.plot_colors[6], **{'font-size':'10pt'})
#                 self._plt2.setLabel('right', 'Dissipation', units='', color=Constants.plot_colors[7], **{'font-size':'10pt'})
# =============================================================================
                '''
                self.InfoWin.ui3.inforef1.setText("<font color=#0000ff > Ref. Frequency </font>" + self._labelref1)
                self.InfoWin.ui3.inforef2.setText("<font color=#0000ff > Ref. Dissipation </font>" + self._labelref2)
                '''
                '''
                TODO 2m set reset frequency abnd dissipation
                '''

                # AMPLITUDE and PHASE
                # -------------------------------------------------------------
                
                
                
# =============================================================================
#                 self._plt0.clear()
#                 self._plt0.plot(x=self._readFREQ, y=self.worker.get_value1_buffer(), pen=Constants.plot_colors[0])
# =============================================================================
                
                x_sweep_reduced = self._readFREQ[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT]
                y_sweep = self.worker.get_value1_buffer()
                y_sweep_reduced = y_sweep[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT]
# =============================================================================
#                 self._plt0_line.setData(x = self._readFREQ, y = self.worker.get_value1_buffer(), pen=Constants.plot_colors[0])
# =============================================================================
                self._plt0_line.setData(x = x_sweep_reduced, y = y_sweep_reduced, pen=self._curve_color())
        
                
                
                # VER 0.1.6 remove reference to phase signal
# =============================================================================
#                 def updateViews1():
#                     self._plt0.clear()
#                     
# =============================================================================
                    # VER 0.1.6 remove reference to phase signal
                    
# =============================================================================
#                     # VER 0.1.2
#                     # software freeze when interacting with software when resizing GUI window
#                     if self._get_source() != SourceType.multiscan:
#                         self._plt1.clear()
#                     self._plt1.setGeometry(self._plt0.vb.sceneBoundingRect())
#                     self._plt1.linkedViewChanged(self._plt0.vb, self._plt1.XAxis)
# =============================================================================

                
                # VER 0.1.6 remove reference to phase signal
# =============================================================================
#                 # updates for multiple plot y-axes
#                 updateViews1()
#                 self._plt0.vb.sigResized.connect(updateViews1)
#                 self._plt0.plot(x=self._readFREQ, y=self.worker.get_value1_buffer(), pen=Constants.plot_colors[0])
#                 self._plt1.addItem(pg.PlotCurveItem(x=self._readFREQ, y=self.worker.get_value2_buffer(), pen=Constants.plot_colors[1]))
# =============================================================================
                
                
                # VER 0.1.6 Do not clear the frequency and dissipation plot each time the plot is updated.
                # This causes the GUI to slow down when many data points are plotted. 
                # It's necessary to reference the 'line' object and update it with real-time data for more efficient plot handling
# =============================================================================
#                 # frequency and dissipation update view
#                 def updateViews2():
#                     self._plt2.clear()
#                     self._pltD.clear()
# 
#                 updateViews2()
#                 self._plt2.vb.sigResized.connect(updateViews2)
# =============================================================================

                #  TODO set the legend in single mode
                overtone_selected = self._overtones_number_all - self.ui.cBox_Speed.currentIndex() - 1

                # FREQUENCY and DISSIPATION
                # -------------------------------------------------------------
                self._vector_1 = self._nscaled(
                    overtone_selected,
                    np.array(self.worker.get_d1_buffer()) - self._reference_value_frequency)
                self._vector_2 = np.array(self.worker.get_d2_buffer()) - self._reference_value_dissipation
                
                # VER 0.1.6 Do not set the y-range axis 
                # TODO try to set the minimum and maximum y-range axis 

# =============================================================================
#                 # VER 0.1.2
#                 # get y_freq and y_dissipation max value
#                 y_freq_single_max = np.nanmax(self._vector_1)
#                 y_freq_single_min = np.nanmin(self._vector_1)
#                 y_diss_single_max = np.nanmax(self._vector_2)
#                 y_diss_single_min = np.nanmin(self._vector_2)
# 
#                 # VER 0.1.2 
#                 # set the y-range of dissipation and frequency axis 
#                 try: 
#                     self._plt2.setYRange(y_freq_single_min - 100, y_freq_single_max + 100, padding = 0)
#                     self._pltD.setYRange(y_diss_single_min - 0.000001, y_diss_single_max + 0.000001, padding = 0)
#                 except: 
#                     pass
# =============================================================================
                
                
                # VER 0.1.6 DO NOT replot again over and over 
                # this causes the GUI to slow down when many data points are plotted.
# =============================================================================
#                 self._plt2.plot( x = self.worker.get_t1_buffer(), y = self._vector_1, pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], width = Constants.plot_line_width))
#                 self._pltD.plot(x = self.worker.get_t1_buffer(), y = self._vector_2, pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], width = Constants.plot_line_width))
# =============================================================================

                # VER 0.1.6 update plot using setData 
                # SOLVED resources available here 
                # https://www.pythonguis.com/tutorials/plotting-pyqtgraph/
                time_x = self.worker.get_t1_buffer()
                self._plt2_line.setData(x = time_x, y = self._vector_1)
                self._pltD_line.setData(x = time_x, y = self._vector_2)  
                
# =============================================================================
#              # VER 0.1.6 TODO set y range 
# =============================================================================
                # get freq and dissipation min and max
                y_freq_single_max = np.nanmax(self._vector_1)
                y_freq_single_min = np.nanmin(self._vector_1)
                y_diss_single_max = np.nanmax(self._vector_2)
                y_diss_single_min = np.nanmin(self._vector_2)
                
                # check if nan 
                if all(not np.isnan(val) for val in [y_freq_single_max, y_freq_single_min, y_diss_single_max, y_diss_single_min]):
                    # TODO make it a constants 
                    y_f_range = 50
                    y_d_range = y_f_range * 10e-6
                    y_f_max = y_freq_single_max + y_f_range
                    y_f_min = y_freq_single_min - y_f_range
                    y_d_max = y_diss_single_max + y_d_range
                    y_d_min = y_diss_single_min - y_d_range
                  
                    # set y range axis 
                    self._set_yrange_forced(self._plt2, y_f_min, y_f_max)
                    self._set_yrange_forced(self._pltD, y_d_min, y_d_max)
# =============================================================================
#                
# =============================================================================

                # update frequency and dissipation indicator
                self._update_indicator_F_single (overtone_selected, self._vector_1)
                self._update_indicator_D_single (overtone_selected, self._vector_2)


                # Prevent the user from zooming/panning out of this specified region
                # TODO set limit of y range axis
# =============================================================================
#
#                 if self._get_source() == SourceType.serial:
#                    #dy = [(value, str(value)) for value in (range(int(min(self._readFREQ)), int(max(self._readFREQ)+1)))]
#                    #self._yaxis.setTicks([dy])
#                    #tickBottom = {self._readFREQ[250]:self._readFREQ[0],self._readFREQ[-1]:self._readFREQ[250]}
#                    #self._yaxis.setTicks([tickBottom.items()])
#                    self._plt2.setLimits(yMax=self._vector_reference_frequency[-1],yMin=self._vector_reference_frequency[0], minYRange=5)
#     #               self._plt3.setLimits(yMax=self._vector_reference_dissipation[-1],yMin=self._vector_reference_dissipation[0], minYRange=1e-7)
#                    self._plt4.setLimits(yMax=50,yMin=-10)
#     #            self._plt3.addItem(pg.PlotCurveItem(self.worker.get_t2_buffer(),self._vector_2, pen=Constants.plot_colors[7]))
# =============================================================================

                # TEMPERATURE
                # -------------------------------------------------------------
                # VER 0.1.6 update temperature data plot using setData, round to 1 decimal
                y_temperature = self.worker.get_d3_buffer().round(decimals = 1)
                
                # VER 0.1.6 do not set the y-axis range 
                
# =============================================================================
#                 # VER 0.1.6 get min and max 
#                 y_temperature_max = np.nanmax(y_temperature)
#                 y_temperature_min = np.nanmin(y_temperature)
#                 # VER 0.1.6 TODO set temperature y-axis 
#                 try:
#                     self._plt4.setYRange(y_temperature_min - 0.1, y_temperature_max + 0.1, padding = 0)
#                 except:
#                     pass
# =============================================================================
                
                # VER 0.1.6 update temperature data plot using setData 
                self._plt4_line.setData(x = time_x, y = y_temperature)
                
# =============================================================================
#              # VER 0.1.6 TODO set y range 
# =============================================================================
                # get temperature min and max                 
                y_temperature_max = np.nanmax(y_temperature)               
                y_temperature_min = np.nanmin(y_temperature)
                if all(not np.isnan(val) for val in [y_temperature_min, y_temperature_max]):
                    # TODO make it a constants 
                    y_t_range = 1
                    y_t_min = y_temperature_min - y_t_range
                    y_t_max = y_temperature_max + y_t_range
                    self._set_yrange_forced(self._plt4, y_t_min, y_t_max)
# =============================================================================
# 
# =============================================================================
                
                # VER 0.1.6 round to 1 decimal
                label_indicator_temperature = float("{0:.1f}".format(y_temperature[0]))
                self._set_indicator_temperature(label_indicator_temperature)
                
# =============================================================================
#                 self._plt4.clear()
#                 # do not autoscale y
#                 self._plt4.enableAutoRange(axis= 'y', enable = True)
# 
#                 # set temperature y range
#                 # VER 0.1.2
#                 
#                 # self._plt4.setYRange(5, 45, padding = 0)
# 
#                 # get temperature buffer
#                 y_temperature = self.worker.get_d3_buffer()
#                 self._plt4.plot(x = self.worker.get_t3_buffer(), y = y_temperature, pen=Constants.plot_colors[4])
# 
#                 # set temperature current value
#                 label_indicator_temperature = float("{0:.2f}".format(y_temperature[0]))
#                 self._set_indicator_temperature(label_indicator_temperature)
# =============================================================================

                # VER 0.1.6 TEC CURRENT update plot
                # -------------------------------------------------------------
                self._update_tec_current_view()
 

            #### MULTISCAN Reference set
            # -----------------------------------------------------------------
            elif self._get_source() == SourceType.multiscan:
                # VER 0.1.6 remove the call to updateViews_multi() 
# =============================================================================
#                 def updateViews_multi():
#                     # VER 0.1.6 remove reference to phase signal
#                     print (" # VER 0.1.6 remove reference to phase signal")
# =============================================================================
# =============================================================================
#                     self._plt1.setGeometry(self._plt0.vb.sceneBoundingRect())
#                     self._plt1.linkedViewChanged(self._plt0.vb, self._plt1.XAxis)
# =============================================================================

                ''' -----------------------------------------------------------
                # AMPLITUDE
                # ------------------------------------------------------------
                # Loads frequencies from calibration file
                peaks_mag = self.load_frequencies_file()
                # get sweep frequency range for each overtone
                x_sweep_axis = self.worker.get_frequency_range_multi(Constants.argument_default_samples, self._overtone_number)
                # center the sweep frequency axis around each overtone frequency peak
                x_sweep_axis = x_sweep_axis - peaks_mag[self._overtone_number]

                # 10M
                if (peaks_mag[0] >9e+06 and peaks_mag[0]<11e+06):
                   # set XY constant in multiscan mode
                   self._plt0.setXRange(-(Constants.L10_5th_overtone + 1000), Constants.R10_5th_overtone + 1000, padding = 0)
                   self._plt0.setYRange(-5, 30, padding = 0)

                # TODO 5M
                if (peaks_mag[0] >4e+06 and peaks_mag[0]<6e+06):
                   self._plt0.setXRange( -(Constants.L5_7th_overtone + 1000), Constants.R5_7th_overtone + 1000, padding = 0 )


                # updates for multiple plot y-axes
                updateViews_multi()
                self._plt0.vb.sigResized.connect(updateViews_multi)

                # TODO AMPLITUDE PLOT
                # clear plot at fundamental sweep
                if self._overtone_number == 0:
                   self._plt0.clear()

                # TODO AMPLITUDE PLOT
                if self.scan_selector[self._overtone_number] == True:
                    self._plt0.plot ( x = x_sweep_axis, y = self.worker.get_value1_buffer(), pen = Constants.plot_color_multi[self._overtone_number] )
                 -----------------------------------------------------------'''

                # AMPLITUDE
                # -------------------------------------------------------------
                # Loads frequencies from calibration file
                peaks_mag = self.load_frequencies_file()

                # VER 0.1.2 do not set XY limit
# =============================================================================
#                 # 10M
#                 if (peaks_mag[0] >9e+06 and peaks_mag[0]<11e+06):
#                     # set XY constant in multiscan mode
#                     self._plt0.setXRange(-(Constants.L10_5th_overtone + 1000), Constants.R10_5th_overtone + 1000, padding = 0)
#                     # self._plt0.setYRange(-10, 40, padding = 0)
#                 # TODO 5M
#                 if (peaks_mag[0] >4e+06 and peaks_mag[0]<6e+06):
#                     # set XY constant in multiscan mode
#                     self._plt0.setXRange( -(Constants.L5_7th_overtone + 1000), Constants.R5_7th_overtone + 1000, padding = 0 )
#                     # self._plt0.setYRange(-5, 30, padding = 0)
# =============================================================================

# =============================================================================
#                 # updates for multiple plot y-axes
#                 updateViews_multi()
#                 self._plt0.vb.sigResized.connect(updateViews_multi)
# 
#                 self._plt0.clear()
# 
#                 # loop on the lines
#                 # TODO introduce this control because I've some trouble in reset buffer ???
#                 if self._ser_control > Constants.environment:
#                     for idx in range(self._overtones_number_all):
#                         # get and scale frequency axis
#                         x_sweep_axis = self.worker.get_F_Sweep_values_buffer(idx) - peaks_mag[idx]
#                         # get amplitude axis
#                         y_sweep_axis = self.worker.get_A_values_buffer(idx)
# 
#                         # plot sweep
#                         # TODO there is something stange in worker.reset_buffers()
#                         if self.scan_selector[idx] == True and isinstance(x_sweep_axis, np.ndarray):
#                            self._plt0.plot ( x = x_sweep_axis, y = y_sweep_axis, pen = Constants.plot_color_multi[idx] )
# =============================================================================
                
                # AMPLITUDE
                # -------------------------------------------------------------
                # VER 0.1.6 update amplitude plot using setData without destroy the plot 
                if self._ser_control > Constants.environment:
                    for idx in range(self._overtones_number_all):
                        # get and scale frequency axis
                        x_sweep_axis = self.worker.get_F_Sweep_values_buffer(idx) - peaks_mag[idx]
                        # get amplitude axis
                        y_sweep_axis = self.worker.get_A_values_buffer(idx)
                        
                        # VER 0.1.6 reduce the array to plot
                        if isinstance(x_sweep_axis, np.ndarray):
                            x_sweep_axis_reduced = x_sweep_axis[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT]
                            y_sweep_axis_reduced = y_sweep_axis[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT] 
                        
                        # check the scan selector
                        if self.scan_selector[idx] == True and isinstance(x_sweep_axis, np.ndarray):
                            self._plt0_multiline[idx].setData(x = x_sweep_axis_reduced, 
                                                              y = y_sweep_axis_reduced, 
                                                              pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width))
                                                    
                        else: 
                            # VER 0.1.6 set the current data to nan 
                            self._plt0_multiline[idx].setData(x = self._numpy_nan_sweep, y = self._numpy_nan_sweep)
                
                

                # FREQUENCY and DISSIPATION
                # ------------------------------------------------------------
                
                # VER 0.1.6 do not clear plt
# =============================================================================
#                 self._plt2.clear()
# 
#                 self._pltD.clear()
# =============================================================================

                for idx in range(self._overtones_number_all):
                    if self.scan_selector[idx] == True:
                        # get time axis
                        time_axis_new = self.worker.get_time_values_buffer(idx)

                        # get y frequency and dissipation axis
                        y_freq = self._nscaled(
                            idx,
                            np.array( self.worker.get_F_values_buffer(idx) ) - self._reference_value_frequency_array[idx])
                        y_diss = np.array( self.worker.get_D_values_buffer(idx) ) - self._reference_value_dissipation_array[idx]
                        
                        # VER 0.1.6 do not set the y-range axis 

# =============================================================================
#                         # VER 0.1.2
#                         # get y_freq and y_dissipation max and min values array
#                         self._y_freq_max[idx] = np.nanmax(y_freq)
#                         self._y_freq_min[idx] = np.nanmin(y_freq)
#                         self._y_diss_max[idx] = np.nanmax(y_diss)
#                         self._y_diss_min[idx] = np.nanmin(y_diss)
# 
#                         # get the frequency and dissipation max and min on overtones
#                         y_freq_max = max(self._y_freq_max)
#                         y_freq_min = min(self._y_freq_min)
#                         y_diss_max = max(self._y_diss_max)
#                         y_diss_min = min(self._y_diss_min)
# 
#                         # print ("GET MAXIMUM VALUES FREQ AND DISSIP = ")
#                         # print (y_freq_max), print (y_diss_max)
# 
#                         try:
#                             # VER 0.1.2
#                             # set the y-range of dissipation and frequency axis
#                             self._plt2.setYRange(y_freq_min - 100, y_freq_max + 100, padding = 0)
#                             self._pltD.setYRange(y_diss_min - 0.000005, y_diss_max + 0.000005, padding = 0)
#                         except:
#                             pass
# =============================================================================
                        
                        # VER 0.1.6 do not call the entire plt
# =============================================================================
#                         # plot frequency and dissipation data
#                         self._plt2.plot(x = time_axis_new, y = y_freq, pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width))
#                         self._pltD.plot(x = time_axis_new, y = y_diss, pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width))
# =============================================================================
                        
                        # VER 0.1.6 update lines using setData
                        self._plt2_multiline[idx].setData(x = time_axis_new, y = y_freq, 
                                                          pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width))
                        self._pltD_multiline[idx].setData(x = time_axis_new, y = y_diss, 
                                                          pen = pg.mkPen(color = Constants.plot_color_multi_diss[idx], width = Constants.plot_line_width))

                        self._update_indicator_F (idx, y_freq)
                        self._update_indicator_D (idx, y_diss)
                        
                        # VER 0.1.6 TODO set y range 
# =============================================================================
                        # get y_freq and y_dissipation max and min values array for each overtones
                        self._y_freq_max[idx] = np.nanmax(y_freq)
                        self._y_freq_min[idx] = np.nanmin(y_freq)
                        self._y_diss_max[idx] = np.nanmax(y_diss)
                        self._y_diss_min[idx] = np.nanmin(y_diss)
                        # get the frequency and dissipation max and min on all overtones
                        y_freq_max = max(self._y_freq_max)
                        y_freq_min = min(self._y_freq_min)
                        y_diss_max = max(self._y_diss_max)
                        y_diss_min = min(self._y_diss_min)
                        
                        # check if nan 
                        if all(not np.isnan(val) for val in [y_freq_max, y_freq_min, y_diss_max, y_diss_min]):
                            # TODO make it a constants 
                            y_f_range = 50
                            y_d_range = y_f_range * 10e-6
                            y_f_max = y_freq_max + y_f_range
                            y_f_min = y_freq_min - y_f_range
                            y_d_max = y_diss_max + y_d_range
                            y_d_min = y_diss_min - y_d_range
                            
                            # set y range axis 
                            self._set_yrange_forced(self._plt2, y_f_min, y_f_max)
                            self._set_yrange_forced(self._pltD, y_d_min, y_d_max)

                    else:
                        dummy = [0]
                        self._update_indicator_F (idx, dummy)
                        self._update_indicator_D (idx, dummy)
                        
                        self._legend_f.removeItem(Constants.name_legend[idx])
                        
                        # VER 0.1.6 set the current data to nan 
                        self._plt2_multiline[idx].setData(x = self._numpy_nan_signal, y = self._numpy_nan_signal) 
                                                          
                        self._pltD_multiline[idx].setData(x = self._numpy_nan_signal, y = self._numpy_nan_signal)
                                                         
                        # VER 0.1.6 TODO set to nan 
                        
                        # VER 0.1.2
                        # reset limits to get the correct y-ranges
                        self._y_freq_max[idx] = 0
                        self._y_freq_min[idx] = 0
                        self._y_diss_max[idx] = 0
                        self._y_diss_min[idx] = 0

                # TEMPERATURE
                # ------------------------------------------------------------
                # VER 0.1.6 update temperature data plot using setData, round to 1 decimal
                y_temperature = self.worker.get_d3_buffer().round(decimals = 1)
                
                # VER 0.1.6 get min and max 
                y_temperature_max = np.nanmax(y_temperature)
                y_temperature_min = np.nanmin(y_temperature)
                
                # VER 0.1.6 do not set temperature y-axis
                
# =============================================================================
#                 # VER 0.1.6 TODO set temperature y-axis 
#                 try:
#                     self._plt4.setYRange(y_temperature_min - 0.1, y_temperature_max + 0.1, padding = 0)
#                 except:
#                     pass
# =============================================================================
                
                # VER 0.1.6 update temperature data plot using setData 
                self._plt4_line.setData(x = self.worker.get_t3_buffer(), y = y_temperature)
                
                # VER 0.1.6 round to 1 decimal
                label_indicator_temperature = float("{0:.1f}".format(y_temperature[0]))
                self._set_indicator_temperature(label_indicator_temperature)
                
                
                # VER 0.1.6 TODO set y range temperature 
# =============================================================================               
                # get temperature min and max                 
                y_temperature_max = np.nanmax(y_temperature)               
                y_temperature_min = np.nanmin(y_temperature)
                if all(not np.isnan(val) for val in [y_temperature_min, y_temperature_max]):
                    # TODO make it a constants 
                    y_t_range = 1
                    y_t_min = y_temperature_min - y_t_range
                    y_t_max = y_temperature_max + y_t_range
                    self._set_yrange_forced(self._plt4, y_t_min, y_t_max)
                    
                    
# =============================================================================
#                 self._plt4.clear()
#                 # do not autoscale y
#                 self._plt4.enableAutoRange(axis= 'y', enable = True)
# 
#                 # set temperature y range
#                 # VER 0.1.2
#                 # self._plt4.setYRange(5, 45, padding = 0)
# 
#                 # get temperature buffer
#                 y_temperature = self.worker.get_d3_buffer()
# 
#                 self._plt4.plot( x = self.worker.get_t3_buffer(), y = y_temperature, pen=Constants.plot_colors[4])
# 
#                 # set temperature current value
#                 label_indicator_temperature = float("{0:.2f}".format(y_temperature[0]))
#                 self._set_indicator_temperature(label_indicator_temperature)
# =============================================================================

                # VER 0.1.6 TEC CURRENT update plot
                # VER 0.1.6 TODO start time set to zero in multi mode
                # -------------------------------------------------------------
                self._update_tec_current_view()

        #### REFERENCE NOT SET
        # ---------------------------------------------------------------------
        else:
            
            
            # self._plt2.setLabel('left', 'Resonance Frequency', units='Hz', color=Constants.plot_title_color, **{'font-size':'10pt'})
            # VER 0.1.6 optimize plt
            self._plt2.setLabel('left', 'Resonance Frequency', units='Hz')
            
            # VER 0.1.6 remove update views function 
# =============================================================================
#             # define update views for amplitude plt
#             def updateViews1():
#                 self._plt0.clear()
# =============================================================================
                
                # VER 0.1.6 remove reference to phase signal
                
# =============================================================================
#                 # VER 0.1.2
#                 # software freeze when interacting with software when resizing GUI window
#                 if self._get_source() != SourceType.multiscan:
#                         self._plt1.clear()
#                 self._plt1.setGeometry(self._plt0.vb.sceneBoundingRect())
#                 self._plt1.linkedViewChanged(self._plt0.vb, self._plt1.XAxis)
# =============================================================================
                
              # VER 0.1.6 remove update views function   
# =============================================================================
#             # VER 0.1.6 remove reference to phase signal
#             def updateViews_multi():
#                 print ( "VER 0.1.5a_DEV remove reference to phase signal")
# =============================================================================
# =============================================================================
#                 self._plt1.setGeometry(self._plt0.vb.sceneBoundingRect())
#                 self._plt1.linkedViewChanged(self._plt0.vb, self._plt1.XAxis)
# =============================================================================


            #### CALIBRATION
            # -----------------------------------------------------------------
            if self._get_source() == SourceType.calibration:
                
               # VER 0.1.6 do not update, what the hell is that !
# =============================================================================
#                # updates for multiple plot y-axes
#                updateViews1()
#                self._plt0.vb.sigResized.connect(updateViews1)
# =============================================================================
               
               # VER 0.1.6 clear plot and plot again  
               self._plt0.clear()
               
               # VER 0.1.6 the calibration curve white color
               calibration_readFREQ  = np.arange(len(self.worker.get_value1_buffer())) * (Constants.calib_fStep) + Constants.calibration_frequency_start
               self._plt0.plot(x=calibration_readFREQ, y=self.worker.get_value1_buffer(), pen=self._curve_color())
               
               # VER 0.1.6 remove reference to phase signal
# =============================================================================
#                self._plt1.addItem(pg.PlotCurveItem(x=calibration_readFREQ,y=self.worker.get_value2_buffer(),pen=Constants.plot_colors[1]))
# =============================================================================

            #### SINGLE Reference NOT set
            # -----------------------------------------------------------------
            elif self._get_source() == SourceType.serial:

               # AMPLITUDE and PHASE
               # -------------------------------------------------------------
               
               # VER 0.1.6 do not update 
               # updates for multiple plot y-axes
# =============================================================================
#                updateViews1()
#                self._plt0.vb.sigResized.connect(updateViews1)
# =============================================================================
               


               # VER 0.1.6 reduce sweep data points
               x_sweep_reduced = self._readFREQ[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT]
               y_sweep = self.worker.get_value1_buffer()
               y_sweep_reduced = y_sweep[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT]
# =============================================================================
#                 self._plt0_line.setData(x = self._readFREQ, y = self.worker.get_value1_buffer(), pen=Constants.plot_colors[0])
# =============================================================================
               self._plt0_line.setData(x = x_sweep_reduced, y = y_sweep_reduced, pen=self._curve_color())

# =============================================================================
#                self._plt0.clear()
#                self._plt0.plot(x = self._readFREQ, y = self.worker.get_value1_buffer(), pen = Constants.plot_colors[0])
# =============================================================================
               
               # VER 0.1.6 remove reference to phase signal
# =============================================================================
#                self._plt1.addItem(pg.PlotCurveItem(x = self._readFREQ,y=self.worker.get_value2_buffer(),pen=Constants.plot_colors[1]))
# =============================================================================

               #  TODO set the legend in single mode
               overtone_selected = self._overtones_number_all - self.ui.cBox_Speed.currentIndex() - 1

               y_freq = self._nscaled(overtone_selected,
                                      self.worker.get_d1_buffer())
               y_diss = self.worker.get_d2_buffer()
               
               # VER 0.1.6 do not get max and min 
# =============================================================================
#                # VER 0.1.2
#                # get y_freq and y_dissipation max value
#                y_freq_single_max = np.nanmax(y_freq)
#                y_freq_single_min = np.nanmin(y_freq)
#                y_diss_single_max = np.nanmax(y_diss)
#                y_diss_single_min = np.nanmin(y_diss)
# =============================================================================

               # FREQUENCY and DISSIPATION
               # --------------------------------------------------------------
               
               # VER 0.1.6 do not clear plt
# =============================================================================
#                self._plt2.clear()
# =============================================================================
               # VER 0.1.6 do not clear plt
# =============================================================================
#                self._pltD.clear()
# =============================================================================
               
               time_x = self.worker.get_t1_buffer()
               time_x_D = self.worker.get_t3_buffer()
               
               # VER 0.1.6 do not set y-axis 
# =============================================================================
#                # VER 0.1.2
#                # check if t y-axis limit is not a nan
#                if not ( np.isnan(y_freq_single_max ) ):
#                    try:
#                        self._plt2.setYRange(y_freq_min - 100, y_freq_max + 100, padding = 0)
#                        self._pltD.setYRange(y_diss_min - 0.000001, y_diss_max + 0.000001, padding = 0)
#                    except:
#                        pass
# =============================================================================
                
               # VER 0.1.6 DO NOT CLEAR PLOT DO NOT CREATE AGAIN THE PLOT      
# =============================================================================
#                self._plt2.plot(x= time_x, y = y_freq, pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], width = Constants.plot_line_width))
#                self._pltD.plot(x = time_x_D, y = y_diss, pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], width = Constants.plot_line_width))
# =============================================================================
                
               # VER 0.1.6 update plot using setData 
               # SOLVED resources available here 
               # https://www.pythonguis.com/tutorials/plotting-pyqtgraph/
               self._plt2_line.setData(x = time_x, y = y_freq)
               self._pltD_line.setData(x = time_x_D, y = y_diss)   
               
# =============================================================================
#              # VER 0.1.6 TODO set y range 
# =============================================================================
               # get freq and dissipation min and max
               y_freq_single_max = np.nanmax(y_freq)
               y_freq_single_min = np.nanmin(y_freq)
               y_diss_single_max = np.nanmax(y_diss)
               y_diss_single_min = np.nanmin(y_diss)
               
               # check if nan 
               if all(not np.isnan(val) for val in [y_freq_single_max, y_freq_single_min, y_diss_single_max, y_diss_single_min]):
                   y_f_range = 50
                   y_d_range = y_f_range * 10e-6
                   y_f_max = y_freq_single_max + y_f_range
                   y_f_min = y_freq_single_min - y_f_range
                   y_d_max = y_diss_single_max + y_d_range
                   y_d_min = y_diss_single_min - y_d_range
                 
                   # set y range axis 
                   self._set_yrange_forced(self._plt2, y_f_min, y_f_max)
                   self._set_yrange_forced(self._pltD, y_d_min, y_d_max)
# =============================================================================
#                
# =============================================================================

               # update frequency and dissipatuon indicator
               self._update_indicator_F_single (overtone_selected, y_freq)
               self._update_indicator_D_single (overtone_selected, y_diss)

               # TEMPERATURE
               # -----------------------------------------------------------------
               # VER 0.1.6 update temperature data plot using setData, round to 1 decimal
               y_temperature = self.worker.get_d3_buffer().round(decimals = 1)
               
               # VER 0.1.6 get min and max 
# =============================================================================
#                y_temperature_max = np.nanmax(y_temperature)
#                y_temperature_min = np.nanmin(y_temperature)
# =============================================================================
               
               # VER 0.1.6 do not set temperature yaxis 
               
# =============================================================================
#                # VER 0.1.6 TODO set temperature y-axis 
#                try:
#                    self._plt4.setYRange(y_temperature_min - 0.1, y_temperature_max + 0.1, padding = 0)
#                except:
#                    pass
# =============================================================================
               
               self._plt4_line.setData(x = time_x, y = y_temperature)
               
# =============================================================================
#              # VER 0.1.6 TODO set y range 
# =============================================================================
               # get temperature min and max                 
               y_temperature_max = np.nanmax(y_temperature)               
               y_temperature_min = np.nanmin(y_temperature)
               if all(not np.isnan(val) for val in [y_temperature_min, y_temperature_max]):
                   # TODO make it a constants 
                   y_t_range = 1
                   y_t_min = y_temperature_min - y_t_range
                   y_t_max = y_temperature_max + y_t_range
                   self._set_yrange_forced(self._plt4, y_t_min, y_t_max)
# =============================================================================
# 
# =============================================================================               
               
               # VER 0.1.6 temprature round to 1 decimal
               label_indicator_temperature = float("{0:.1f}".format(y_temperature[0]))
               self._set_indicator_temperature(label_indicator_temperature)
               
# =============================================================================
# 
#                self._plt4.clear()
#                # do not autoscale y
#                self._plt4.enableAutoRange(axis= 'y', enable = True)
#                # set temperature y range
#                # VER 0.1.2
#                # change the Temperature Y-range to 5 - 45 °C
#                # self._plt4.setYRange(5, 45, padding = 0)
# 
#                # get temperature buffer
#                y_temperature = self.worker.get_d3_buffer()
#                self._plt4.plot(x = time_x_D, y = y_temperature, pen=Constants.plot_colors[4])
# 
#                # set temperature current value
#                label_indicator_temperature = float("{0:.2f}".format(y_temperature[0]))
#                self._set_indicator_temperature(label_indicator_temperature)
# =============================================================================

               # VER 0.1.6 TEC CURRENT update plot
               # -------------------------------------------------------------
               self._update_tec_current_view()

            #### MULTISCAN Reference NOT set
            # -----------------------------------------------------------------
            elif self._get_source() == SourceType.multiscan:
               '''
               # AMPLITUDE
               # -------------------------------------------------------------
               # Loads frequencies from calibration file
               peaks_mag = self.load_frequencies_file()
               # get sweep frequency range for each overtone
               x_sweep_axis = self.worker.get_frequency_range_multi(Constants.argument_default_samples, self._overtone_number)
               # center the sweep frequency axis around each overtone frequency peak
               x_sweep_axis = x_sweep_axis - peaks_mag[self._overtone_number]

               # 10M
               if (peaks_mag[0] >9e+06 and peaks_mag[0]<11e+06):
                   # set XY constant in multiscan mode
                   self._plt0.setXRange(-(Constants.L10_5th_overtone + 1000), Constants.R10_5th_overtone + 1000, padding = 0)
                   self._plt0.setYRange(-5, 30, padding = 0)

               # TODO 5M
               if (peaks_mag[0] >4e+06 and peaks_mag[0]<6e+06):
                   self._plt0.setXRange( -(Constants.L5_7th_overtone + 1000), Constants.R5_7th_overtone + 1000, padding = 0 )

               # updates for multiple plot y-axes
               updateViews_multi()
               self._plt0.vb.sigResized.connect(updateViews_multi)

               # TODO clear plot at fundamental sweep
               if self._overtone_number == 0:
                   self._plt0.clear()

               # plot
               if self.scan_selector[self._overtone_number] == True:
                   self._plt0.plot ( x = x_sweep_axis, y = self.worker.get_value1_buffer(), pen = Constants.plot_color_multi[self._overtone_number] )
               '''

               # AMPLITUDE
               # -------------------------------------------------------------
               # Loads frequencies from calibration file
               peaks_mag = self.load_frequencies_file()

               # VER 0.1.2
# =============================================================================
#                # 10M
#                if (peaks_mag[0] >9e+06 and peaks_mag[0]<11e+06):
#                    # set XY constant in multiscan mode
#                    self._plt0.setXRange(-(Constants.L10_5th_overtone + 1000), Constants.R10_5th_overtone + 1000, padding = 0)
#                    # self._plt0.setYRange(-5, 35, padding = 0)
#                # TODO 5M
#                if (peaks_mag[0] >4e+06 and peaks_mag[0]<6e+06):
#                    # set XY constant in multiscan mode
#                    self._plt0.setXRange( -(Constants.L5_7th_overtone + 1000), Constants.R5_7th_overtone + 1000, padding = 0 )
#                    # self._plt0.setYRange(-5, 30, padding = 0)
# =============================================================================


# =============================================================================
#                # updates for multiple plot y-axes
#                updateViews_multi()
#                self._plt0.vb.sigResized.connect(updateViews_multi)
# 
#                self._plt0.clear()
# 
#                # loop on the lines
#                # TODO introduce this control because I've some trouble in reset buffer ???
#                if self._ser_control > Constants.environment:
#                    for idx in range(self._overtones_number_all):
#                        # get and scale frequency axis
#                        x_sweep_axis = self.worker.get_F_Sweep_values_buffer(idx) - peaks_mag[idx]
#                        # get amplitude axis
#                        y_sweep_axis = self.worker.get_A_values_buffer(idx)
#                        # plot sweep
#                        if self.scan_selector[idx] == True and isinstance(x_sweep_axis, np.ndarray):
#                            self._plt0.plot ( x = x_sweep_axis, y = y_sweep_axis, pen = Constants.plot_color_multi[idx] )
# =============================================================================

               # AMPLITUDE
               # -------------------------------------------------------------
               # VER 0.1.6 update amplitude plot using setData without destroy the plot 
               if self._ser_control > Constants.environment:
                    for idx in range(self._overtones_number_all):
                        # get and scale frequency axis
                        x_sweep_axis = self.worker.get_F_Sweep_values_buffer(idx) - peaks_mag[idx]
                        # get amplitude axis
                        y_sweep_axis = self.worker.get_A_values_buffer(idx)
                        
                        # VER 0.1.6 reduce the array to plot
                        if isinstance(x_sweep_axis, np.ndarray):
                            x_sweep_axis_reduced = x_sweep_axis[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT]
                            y_sweep_axis_reduced = y_sweep_axis[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT] 
                        
                        
                        
                        
                        # VER 0.1.6 reduce the array to plot
# =============================================================================
#                         if isinstance(y_sweep_axis, np.ndarray):
#                             y_sweep_axis_reduced = y_sweep_axis[1:Constants.SAMPLES:Constants.FREQ_STEP_PLOT]
# =============================================================================
                        
                       
                        
                        if self.scan_selector[idx] == True and isinstance(x_sweep_axis, np.ndarray):
                            self._plt0_multiline[idx].setData(x = x_sweep_axis_reduced, 
                                                              y = y_sweep_axis_reduced, 
                                                              pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width))
# =============================================================================
#                            self._plt0_multiline[idx].setData(x = x_sweep_axis, y = y_sweep_axis, pen = pg.mkPen(color = Constants.plot_color_multi[idx]))
# =============================================================================

                        else: 
# =============================================================================
#                            print ("DEBUG: Warning sweep data set to NAN  ")
# =============================================================================
                           # VER 0.1.6 set data to nan 
                           self._plt0_multiline[idx].setData(x = self._numpy_nan_sweep, y = self._numpy_nan_sweep)
                

               # FREQUENCY and DISSIPATION
               # --------------------------------------------------------------
               # clear plot
# =============================================================================
#                self._plt2.clear()
#                self._pltD.clear()
# =============================================================================

               # loop on the lines
               for idx in range(self._overtones_number_all):
                   if self.scan_selector[idx] == True:
                       # get time axis
                       time_axis_new = self.worker.get_time_values_buffer(idx)

                       # get y frequency and dissipation axis
                       y_freq = self._nscaled(
                           idx, self.worker.get_F_values_buffer(idx))
                       y_diss = self.worker.get_D_values_buffer(idx)
                       
# =============================================================================
#                        # frequency
#                        self._plt2.plot(x = time_axis_new, y = y_freq, pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width))
#                        # dissipation
#                        self._pltD.plot(x =  time_axis_new, y = y_diss, pen = Constants.plot_color_multi[idx], width = Constants.plot_line_width)
# =============================================================================

                        
                       # VER 0.1.6 update lines using setData 
                       self._plt2_multiline[idx].setData(x = time_axis_new, y = y_freq, 
                                                         pen = pg.mkPen(color = Constants.plot_color_multi[idx], width = Constants.plot_line_width))
                       self._pltD_multiline[idx].setData(x = time_axis_new, y = y_diss, 
                                                         pen = pg.mkPen(color = Constants.plot_color_multi_diss[idx], width = Constants.plot_line_width))
            
                       

                       self._update_indicator_F (idx, y_freq)
                       self._update_indicator_D (idx, y_diss)

                   else:
                       dummy = [0]
                       self._update_indicator_F (idx, dummy)
                       self._update_indicator_D (idx, dummy)
                       
                       
                       self._legend_f.removeItem(Constants.name_legend[idx])
                       
                       # VER 0.1.6 update lines and set data to nan
                       self._plt2_multiline[idx].setData(x = self._numpy_nan_signal, y = self._numpy_nan_signal) 
                                                         
                       self._pltD_multiline[idx].setData(x = self._numpy_nan_signal, y = self._numpy_nan_signal)
                                                         


               # TEMPERATURE
               # --------------------------------------------------------------
               # VER 0.1.6 update temperature data plot using setData. round to 1 decimal  
               y_temperature = self.worker.get_d3_buffer().round(decimals = 1)
               
               # VER 0.1.6 do not set YAXIS 
# =============================================================================
#                # VER 0.1.6 get min and max 
#                y_temperature_max = np.nanmax(y_temperature)
#                y_temperature_min = np.nanmin(y_temperature)
#                # VER 0.1.6 TODO set temperature y-axis 
#                try:
#                    self._plt4.setYRange(y_temperature_min - 0.1, y_temperature_max + 0.1, padding = 0)
#                except:
#                    pass
# =============================================================================
               
               # VER 0.1.6 update temperature data plot using setData 
               self._plt4_line.setData(x = self.worker.get_t3_buffer(), y = y_temperature)
               
               # VER 0.1.6 TODO set y range temperature 
# =============================================================================               
               # get temperature min and max                 
               y_temperature_max = np.nanmax(y_temperature)               
               y_temperature_min = np.nanmin(y_temperature)
               if all(not np.isnan(val) for val in [y_temperature_min, y_temperature_max]):
                   # TODO make it a constants 
                   y_t_range = 1
                   y_t_min = y_temperature_min - y_t_range
                   y_t_max = y_temperature_max + y_t_range
                   self._set_yrange_forced(self._plt4, y_t_min, y_t_max)
               
               # VER 0.1.6  round to 1 decimal  
               label_indicator_temperature = float("{0:.1f}".format(y_temperature[0]))
               self._set_indicator_temperature(label_indicator_temperature)
# =============================================================================
#                self._plt4.clear()
#                # do not autoscale y
#                self._plt4.enableAutoRange(axis= 'y', enable = True)
#                # VER 0.1.2
#                # change the Temperature Y-range to 5 - 45 °C
#                # self._plt4.setYRange(5, 45, padding = 0)
# 
#                # get temperarre buffer
#                y_temperature = self.worker.get_d3_buffer()
# 
#                self._plt4.plot( x = self.worker.get_t3_buffer(), y = y_temperature, pen=Constants.plot_colors[4])
# 
#                # set temperature current value
#                label_indicator_temperature = float("{0:.2f}".format(y_temperature[0]))
#                self._set_indicator_temperature(label_indicator_temperature)
# =============================================================================

               # VER 0.1.6 TEC CURRENT update plot
               # -------------------------------------------------------------
               self._update_tec_current_view()
               
    # VER 0.1.4
    # update TEC status label 
    def _update_TEC_status(self, value): 
        # temperature control active, temperature is out of range, electric current is null ERROR
        if value == Constants.STATUS_CONTROL_ACTIVE_LOW_CURRENT_NULL: 
            self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("err"))
            self.ui.label_Temperature_state.setText("Error, please reset the TEC controller ")
            self.ui.pButton_TEC_Reset.setEnabled(True)
            
            if value != self._old_value:
                # TODO 0.1.3 not blocking popup 
                # BUG the QTimer update plot is still running !
                PopUp.warning_not_blocking(self, 
                                           "TEC Status Error", 
                                           "TEC status error: please press reset TEC controller button to start the temperature control again. If heatsink over heating occured, please wait for heat dissipation before starting the temperature control again" )
            
            
        # temperature control NOT active     
        if value == Constants.STATUS_CONTROL_NOT_ACTIVE: 
            self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("off"))
            self.ui.label_Temperature_state.setText("Temperature Control: Not active ")
            self.ui.pButton_TEC_Reset.setEnabled(False)
            
        # temperature control active, temperature is out of range, electric current is NOT null    
        if value == Constants.STATUS_CONTROL_ACTIVE_LOW_CURRENT_NOT_NULL:
            self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("warn"))
            self.ui.label_Temperature_state.setText("Temperature Control: Active getting setpoint ")
            self.ui.pButton_TEC_Reset.setEnabled(False)
            
        # temperature control active and temperature in range
        if value == Constants.STATUS_CONTROL_ACTIVE_HIGH:
            self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("active"))
            self.ui.label_Temperature_state.setText("Temperature Control: Status in range ")
            self.ui.pButton_TEC_Reset.setEnabled(False)

        # GUI: keep the single toggle in sync with the firmware-reported state
        # (any active state = will turn OFF/brown; not-active = will turn ON).
        _active = (value != Constants.STATUS_CONTROL_NOT_ACTIVE)
        if _active != self._tec_on:
            self._tec_on = _active
            self._update_tec_toggle()

        self._old_value = value

    # ------------------------------------------------------------------
    # The TEC controller's error register drives the temperature buttons
    # ------------------------------------------------------------------
    # While the controller reports an error nothing can be asked of it but a
    # reset (data sheet 6.3), so ON/OFF and T SET are locked and RESET is the
    # only live control. The lock follows the REGISTER, not the end of the
    # reset sequence: a reset that did not clear the error leaves the buttons
    # locked and RESET available to try again. During a measurement the
    # register rides with every temperature sample; in Standby nobody samples
    # it, so _TEC_Reset_button asks E? itself after its sequence.
    def _update_tec_error_lock(self, register):
        names = decode_error_register(register)
        locked = bool(names)
        now = time.time()
        pending = now < self._tec_reset_pending_until

        if names != self._tec_errors:
            if locked:
                text = "TEC controls locked: {} -- press RESET".format(", ".join(sorted(names)))
            else:
                text = "TEC controls released: error register clear"
                self._tec_reset_pending_until = 0.0
                pending = False
            print(TAG, text)
            Log.i(TAG, text)
            if not locked:
                # release: the toggle follows the connection, T SET the TEC switch,
                # and the pill goes back to the TEC state (the next temperature
                # sample repaints it anyway during a measurement; after a reset
                # from Standby nothing else would)
                self.ui.pButton_Tswitch_ON.setEnabled(self._serial_connected)
                self._Temperature_Setting_isEnabled(self._tec_on)
                if self._tec_on:
                    self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("warn"))
                    self.ui.label_Temperature_state.setText("Temperature Control: Active getting setpoint ")
                else:
                    self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("off"))
                    self.ui.label_Temperature_state.setText("Temperature Control: Not active ")
            self._tec_errors = set(names)

        if locked:
            self.ui.pButton_Tswitch_ON.setEnabled(False)
            self._Temperature_Setting_isEnabled(False)
            self.ui.label_Temperature_state.setStyleSheet(self._tec_state_pill("err"))
            self.ui.label_Temperature_state.setText(
                "Error: {} -- press RESET".format(", ".join(sorted(names))))
            self.ui.pButton_TEC_Reset.setEnabled(not pending)

    def _reapply_tec_error_lock(self):
        """Put the lock back after something redrew the card (STOP does)."""
        if not self._tec_errors:
            return
        self._update_tec_error_lock(
            self.worker.get_TEC_error_register() if self.worker is not None else 0)
        # RESET must be reachable from Standby while the error stands
        self.ui.pButton_TEC_Reset.setEnabled(time.time() >= self._tec_reset_pending_until)

    def _refresh_tec_error_lock_from_device(self):
        """Standby: ask E? once and set the lock from the answer."""
        register = self._read_tec_error_register()
        if register is None:
            return
        names = decode_error_register(register)
        print(TAG, "TEC error register on connect: {} ({})".format(
            register, ", ".join(sorted(names)) if names else "clear"))
        Log.i(TAG, "TEC error register on connect: {}".format(register))
        self._update_tec_error_lock(register)
        if names:
            self.ui.pButton_TEC_Reset.setEnabled(True)

    def _tec_reset_started(self):
        """RESET pressed: no second sequence until the register has been seen again."""
        self._tec_reset_pending_until = time.time() + 10.0
        self.ui.pButton_TEC_Reset.setEnabled(False)

    def _read_tec_error_register(self):
        """Standby only: ask the controller E? through the firmware.

        Returns the register as an int, or None when nothing usable came back.
        """
        if not self._can_query_device():
            return None
        reply = _first_reply_line(self._serial_query(b"E\n", wait=0.3))
        try:
            return int(reply)
        except ValueError:
            print(TAG, "E? answered '{}', not a register value".format(reply))
            return None
            
    def _TEC_Reset_button(self):
        """Clear the TEC controller's error register.

        MTD415T data sheet, 6.3: the error register is reset by the "c" command
        or by setting the Enable pin Off and On again. This is the second way,
        X0 / X1 / X0 through the firmware. The controller is NOT powered down --
        its supply pin stays high from the firmware's setup() -- so set-point,
        PID and every other parameter it holds survive the reset.

        ⚠️ Therefore nothing is written to config.txt here beyond the TEC flag
        that ON and OFF already write. Until 2026-09-09 this ended with
        `_set_PID_T_default()`, which put set-point and PID back to their
        defaults in the file and on the indicator while the controller kept
        what it had: the same divergence T SET (7a7f1b3) and TEC OFF (53487f7)
        had, and the last place from which an old PID could reach the file.
        """
        if self.worker is not None and self.worker.is_running():
            # The acquisition owns the port: the GUI's X writes would be skipped
            # and the reset would depend on the config flag being sampled at
            # the right moments (it was not, bench 2026-09-09). The process runs
            # the sequence itself between two sweeps and reports it in the log.
            # The GUI goes to OFF now, which is where the sequence ends.
            self.Temperature_Control_OFF()
            if self.worker.request_tec_reset():
                self._tec_reset_started()
                text = ("TEC reset requested: the acquisition runs X0 / X1 / X0 at "
                        "the end of the current sweep and reports it here.")
            else:
                text = "TEC reset not requested: the acquisition is not ready yet."
            print(TAG, text)
            Log.i(TAG, text)
            return

        # RESET PROCEDURE: Enable pin Off, On, Off
        self._tec_reset_started()
        self.Temperature_Control_OFF()
        # VER 0.1.5 increased the waiting time for module reset 2 seconds
        sleep(2.0)
        self.Temperature_Control_ON()
        sleep(2.0)
        # leave the TEC not active
        self.Temperature_Control_OFF()
        sleep(0.5)

        # Standby: nobody samples the register, so ask for it now. This is what
        # makes a reset from Standby verifiable, and what releases the buttons.
        register = self._read_tec_error_register()
        if register is None:
            text = "TEC reset done (X0, X1, X0); the error register could not be read back."
            self._tec_reset_pending_until = 0.0
            self.ui.pButton_TEC_Reset.setEnabled(bool(self._tec_errors))
        else:
            names = decode_error_register(register)
            text = "TEC reset done (X0, X1, X0); error register now {} ({}).".format(
                register, ", ".join(sorted(names)) if names else "clear")
            self._tec_reset_pending_until = 0.0
            self._update_tec_error_lock(register)
        print(TAG, text)
        Log.i(TAG, text)

    ###########################################################################
    # N-SCALE: every plotted frequency divided by its harmonic order
    ###########################################################################
    def _nscale_div(self, index):
        """The divisor for overtone ``index``: 1, 3, 5, 7, 9 -- or 1 when off.

        ⚠️ DISPLAY ONLY. The buffers, the datalog and the status bar carry the
        measured values; this divides what is drawn. The readout cards follow
        only because they are handed the same arrays as the curves, which is the
        point -- a card that disagrees with the line above it is the defect this
        codebase keeps producing.
        """
        if not self._nscale:
            return 1.0
        return float(2 * int(index) + 1)

    def _nscaled(self, index, values):
        """``values`` divided by the harmonic order, or untouched when off.

        Returned unchanged -- same object, same type -- while N-SCALE is off, so
        the ordinary path is exactly what it was before this control existed.
        """
        div = self._nscale_div(index)
        if div == 1.0:
            return values
        return np.asarray(values, dtype=float) / div

    def _set_nscale(self, on):
        self._nscale = bool(on)
        # the axis label has to say what it now holds
        self._plt2.setLabel(
            "left", "Resonance Frequency / n" if self._nscale
            else "Resonance Frequency", units="Hz")
        # the curves are redrawn by the plot timer; when it is not running the
        # panel would keep the old scale until the next acquisition
        timer = getattr(self, "_timer_plot", None)
        if self.worker is not None and (timer is None or not timer.isActive()):
            try:
                self._update_plot()
            except Exception:
                pass          # nothing acquired yet: the label is enough

    def _update_indicator_F (self, index, value):

        label = float("{0:.1f}".format(value[0]))

        if (index == 0):
            if (self.scan_selector[index] == True):
                self.ui.F0.setText(str(label))
            else:
                self.ui.F0.setText("nan")
        elif (index == 1):
            if (self.scan_selector[index] == True):
                self.ui.F3.setText(str(label))
            else:
                 self.ui.F3.setText("nan")
        elif (index == 2):
            if (self.scan_selector[index] == True):
                self.ui.F5.setText(str(label))
            else:
                self.ui.F5.setText("nan")
        elif (index == 3):
            if (self.scan_selector[index] == True):
                self.ui.F7.setText(str(label))
            else:
                self.ui.F7.setText("nan")
        elif (index == 4):
            if (self.scan_selector[index] == True):
                self.ui.F9.setText(str(label))
            else:
                self.ui.F9.setText("nan")


    def _update_indicator_F_single (self, index, value):

        label = float("{0:.1f}".format(value[0]))

        if (index == 0):
            self.ui.F0.setText(str(label))
        else:
            self.ui.F0.setText("nan")

        if (index == 1):
            self.ui.F3.setText(str(label))
        else:
            self.ui.F3.setText("nan")

        if (index == 2):
            self.ui.F5.setText(str(label))
        else:
            self.ui.F5.setText("nan")

        if (index == 3):
            self.ui.F7.setText(str(label))
        else:
            self.ui.F7.setText("nan")

        if (index == 4):
            self.ui.F9.setText(str(label))
        else:
            self.ui.F9.setText("nan")


    def _update_indicator_D (self, index, value):
        value_multiplied = value[0] * 1e6
        # label = float("{0:.3f}".format(value_multiplied))
        # VER 0.1.6 dissipation round to 1 decimal  
        label = float("{0:.1f}".format(value_multiplied))

        if (index == 0):
            if (self.scan_selector[index] == True):
                self.ui.D0.setText(str(label))
            else:
                self.ui.D0.setText("nan")
        elif (index == 1):
            if (self.scan_selector[index] == True):
                self.ui.D3.setText(str(label))
            else:
                self.ui.D3.setText("nan")
        elif (index == 2):
            if (self.scan_selector[index] == True):
                self.ui.D5.setText(str(label))
            else:
                self.ui.D5.setText("nan")
        elif (index == 3):
            if (self.scan_selector[index] == True):
                self.ui.D7.setText(str(label))
            else:
                self.ui.D7.setText("nan")
        elif (index == 4):
            if (self.scan_selector[index] == True):
                self.ui.D9.setText(str(label))
            else:
                self.ui.D9.setText("nan")


    def _update_indicator_D_single (self, index, value):
        value_multiplied = value[0] * 1e6
        
        #label = float("{0:.3f}".format(value_multiplied))
        # VER 0.1.6 dissipation round to 1 decimal  
        label = float("{0:.1f}".format(value_multiplied))

        if (index == 0):
            self.ui.D0.setText(str(label))
        else:
            self.ui.D0.setText("nan")

        if (index == 1):
            self.ui.D3.setText(str(label))
        else:
            self.ui.D3.setText("nan")
        if (index == 2):
            self.ui.D5.setText(str(label))
        else:
            self.ui.D5.setText("nan")

        if (index == 3):
            self.ui.D7.setText(str(label))
        else:
            self.ui.D7.setText("nan")

        if (index == 4):
            self.ui.D9.setText(str(label))
        else:
            self.ui.D9.setText("nan")



    def _update_scan_selector(self):
        self.scan_selector[0] = self.ui.radioBtn_F0.isChecked()
        self.scan_selector[1] = self.ui.radioBtn_F3.isChecked()
        self.scan_selector[2] = self.ui.radioBtn_F5.isChecked()
        self.scan_selector[3] = self.ui.radioBtn_F7.isChecked()
        self.scan_selector[4] = self.ui.radioBtn_F9.isChecked()
        # VER 0.1.6 update legend when the radio button is selected 
        self._update_legend()
    
    # VER 0.1.6 TODO update legend 
    def _update_legend(self):
        
        # VER 0.1.6 check the len of the peak file 
        pks = self.load_frequencies_file()
      
        # for idx in range (5):
        # chekc the number of frequency overtones detected    
        for idx in range (len(pks)):
            if  self.scan_selector[idx] == True:
                try: 
                    self._legend_f.removeItem(Constants.name_legend[idx])
                except:
                    print ("DEBUG: unable to remove legend item")
                    pass
                try:
                    self._legend_D.removeItem(Constants.name_legend[idx])
                except:
                    print ("DEBUG: unable to remove legend item")
                    pass
                try:
                    self._legend_f.addItem(item = self._plt2_multiline[idx], name = Constants.name_legend[idx])
                    self._legend_D.addItem(item = self._pltD_multiline[idx], name = Constants.name_legend[idx])
                except:
                    print ("DEBUG: unable to add itme to legend")
                    pass
            else: 
                try:
                    self._legend_f.removeItem(Constants.name_legend[idx])
                    self._legend_D.removeItem(Constants.name_legend[idx])
                except:
                    print ("DEBUG: unable to remove legend item")
                    pass
    
    def _update_legend_single(self):
        overtone_selected = self._overtones_number_all - self.ui.cBox_Speed.currentIndex() - 1
        self._legend_f.addItem(item = self._plt2_line, name = Constants.name_legend[overtone_selected])
        self._legend_D.addItem(item = self._pltD_line, name = Constants.name_legend[overtone_selected])
    
    # VER 0.1.6 remove legend from all plot
    # TODO will work on single and multi mode ?           
    def _remove_legend(self):
        for idx in range (5):
            self._legend_f.removeItem(Constants.name_legend[idx])
            self._legend_D.removeItem(Constants.name_legend[idx])
                
    
# =============================================================================
#     def _getLabel(self, plotItem):
#         """Return the labelItem inside the legend for a given plotItem
# 
#         The label-text can be changed via labenItem.setText
#         """
#         out = [(it, lab) for it, lab in items if it.item == plotItem]
#         try:
#             return out[0][1]
#         except IndexError:
#             return None            
# =============================================================================

    # VER 0.1.6 autoscale all plot 
    def autoscale(self):
        """Plot Controls > Autoscale: re-enable X+Y autorange on all plots."""
        self._autoscale_plot_all(True)

    def _autoscale_plot_all (self, boolean):
       
       # amplitude sweep 
       self._plt0.enableAutoRange(enable=boolean)
       # frequency 
       self._plt2.enableAutoRange(enable=boolean)
       # dissipation 
       self._pltD.enableAutoRange(enable=boolean)
       # temperature
       self._plt4.enableAutoRange(enable=boolean)

    # VER 0.1.6 apply the forced (padded) Y-range only when enabled; otherwise
    # leave the plot in autorange (see Constants.plot_force_yrange). Development
    # builds run with the flag False (tight autorange); set True and tune the
    # paddings for distribution.
    # ------------------------------------------------------------------
    # Phase 4: plot interactions — custom right-click menu, grid toggle,
    # Δ cursors on the frequency and dissipation panels. Adapted from
    # openQCM Q-1 v3.0; NEXT keeps F and D in two separate panels.
    # ------------------------------------------------------------------
    def _setup_plot_interactions(self):
        # The menu is ui/plotMenu.py's, not a copy: this window used to carry its
        # own, which is how one scene-scoping defect came to exist twice. The two
        # things only this window needs are the hooks the shared module already
        # provides -- the delta cursors as an extra item, and the phase twin's
        # grid following the amplitude plot's.
        self._plot_menu_targets = [self._plt0, self._plt4, self._plt2, self._pltD]
        self._plot_menu = PlotMenu(self, extra_actions=self._plot_menu_extras,
                                   apply_grid=self._apply_grid)
        self._plot_menu.attach(self._plot_menu_targets)
        # Δ cursors: two movable time cursors + delta readout per panel. The
        # items are parented to the ViewBox (ignoreBounds) so they survive
        # PlotItem.clear() and never drive the autorange.
        self._plot_cursors = {}
        for plot, kind in ((self._plt2, "F"), (self._pltD, "D")):
            c1 = pg.InfiniteLine(angle=90, movable=True,
                                 pen=pg.mkPen("#f4b400", width=2))
            c2 = pg.InfiniteLine(angle=90, movable=True,
                                 pen=pg.mkPen("#2e9e5b", width=2))
            txt = pg.TextItem("", anchor=(0, 0), color="#888888")
            vb = plot.getViewBox()
            for item in (c1, c2, txt):
                item.setVisible(False)
                vb.addItem(item, ignoreBounds=True)
            c1.sigPositionChanged.connect(
                lambda _l, p=plot: self._update_cursor_delta(p))
            c2.sigPositionChanged.connect(
                lambda _l, p=plot: self._update_cursor_delta(p))
            self._plot_cursors[plot] = {"c1": c1, "c2": c2,
                                        "text": txt, "kind": kind}

    def _plot_menu_extras(self, menu, plot):
        """The Δ-cursor item, added to the two panels that carry cursors."""
        if plot in self._plot_cursors:
            visible = self._plot_cursors[plot]["c1"].isVisible()
            menu.addAction("Hide Δ cursors" if visible else "Show Δ cursors",
                           lambda: self._toggle_cursors_for(plot))

    def _apply_grid(self, plot, on):
        plot.showGrid(x=on, y=on, alpha=0.3)
        # the phase twin overlays the amplitude plot: keep the grids together
        if plot is self._plt0 and getattr(self, "_plt1", None) is not None:
            self._plt1.showGrid(x=on, y=on, alpha=0.3)

    def _toggle_all_grids(self, on):
        """View > Grid: same state on every plot panel."""
        menu = getattr(self, "_plot_menu", None)
        if menu is not None:
            menu.set_grid_all(bool(on))

    def _set_grid(self, plot, on):
        self._plot_menu.set_grid(plot, on)

    def _toggle_cursors_for(self, plot, on=None):
        info = self._plot_cursors[plot]
        show = (not info["c1"].isVisible()) if on is None else on
        if show:
            x0, x1 = plot.getViewBox().viewRange()[0]
            info["c1"].setValue(x0 + 0.30 * (x1 - x0))
            info["c2"].setValue(x0 + 0.70 * (x1 - x0))
        for item in (info["c1"], info["c2"], info["text"]):
            item.setVisible(show)
        if show:
            self._update_cursor_delta(plot)
        # keep the View > Δ Cursors checkbox in sync (checked = any visible)
        act = getattr(self, "_act_cursors", None)
        if act is not None:
            any_on = any(i["c1"].isVisible()
                         for i in self._plot_cursors.values())
            act.blockSignals(True)
            act.setChecked(any_on)
            act.blockSignals(False)

    def _toggle_all_cursors(self, checked):
        for plot in self._plot_cursors:
            self._toggle_cursors_for(plot, on=checked)

    def _cursor_series(self, kind):
        # Data behind the cursor Δy: multiscan → fundamental buffers (same
        # convention as the status bar); single mode → the measured overtone.
        if self._get_source() == SourceType.multiscan:
            index = 0
            t = self.worker.get_time_values_buffer(0)
            y = (self.worker.get_F_values_buffer(0) if kind == "F"
                 else self.worker.get_D_values_buffer(0))
        else:
            index = (self._overtones_number_all
                     - self.ui.cBox_Speed.currentIndex() - 1)
            t = (self.worker.get_t1_buffer() if kind == "F"
                 else self.worker.get_t2_buffer())
            y = (self.worker.get_d1_buffer() if kind == "F"
                 else self.worker.get_d2_buffer())
        # the cursors read the buffers directly, so N-SCALE has to be applied
        # here too or ΔF would print unscaled hertz under a scaled curve
        if kind == "F":
            y = self._nscaled(index, y)
        return np.asarray(t, dtype=float), np.asarray(y, dtype=float)

    def _update_cursor_delta(self, plot):
        info = self._plot_cursors.get(plot)
        if info is None or not info["c1"].isVisible():
            return
        x1, x2 = sorted((info["c1"].value(), info["c2"].value()))
        # the time axis carries epoch microseconds (see Constants.ElapsedTimeAxis)
        text = "Δt: {:.1f} s".format((x2 - x1) / 1e6)
        try:
            t, y = self._cursor_series(info["kind"])
            ok = np.isfinite(t) & np.isfinite(y)
            t, y = t[ok], y[ok]
            if t.size:
                y1 = y[np.argmin(np.abs(t - x1))]
                y2 = y[np.argmin(np.abs(t - x2))]
                if info["kind"] == "F":
                    text += "   ΔF: {:+.1f} Hz".format(y2 - y1)
                else:
                    text += "   ΔD: {:+.2f} ppm".format((y2 - y1) * 1e6)
        except Exception:
            pass
        xr, yr = plot.getViewBox().viewRange()
        info["text"].setPos(xr[0] + 0.02 * (xr[1] - xr[0]), yr[1])
        info["text"].setText(text)

    def _set_yrange_forced(self, plot, y_min, y_max):
        if Constants.plot_force_yrange:
            plot.setYRange(y_min, y_max)
        else:
            plot.enableAutoRange(axis='y', enable=True)
        


###########################################################################
    # Updates the source and depending boxes on change
    ###########################################################################
    def _source_changed(self):

        # It is connected to the indexValueChanged signal of the Source ComboBox.

        # single frequency measurement
        if self._get_source() == SourceType.serial:
           print(TAG, "Operation mode: {}".format(Constants.app_sources[1]))  # self._get_source().name
           Log.i(TAG, "Operation mode: {}".format(Constants.app_sources[1]))

           # show - hide overtone radio button selector
           self._Overtone_radioBtn_isEnabled(False)
           
           # VER 0.1.4 disable datalog sampling time 
           self.ui.cBox_sampling_time.setEnabled(False)
           
           # VER 0.1.6 enable frequency selector inly in single mode
           self.ui.cBox_Speed.setEnabled(True)
           # frequency dropdown is only meaningful in Single Measurement
           self.ui.cBox_Speed.setVisible(True)

           # Phase 3b: reflect the current combo selection on the quick-select row
           self._sync_overtone_buttons_from_speed()

        # calibration
        elif self._get_source() == SourceType.calibration:
           print(TAG, "Operation mode:  {}".format(Constants.app_sources[0]))  # self._get_source().name
           Log.i(TAG, "Operation mode:  {}".format(Constants.app_sources[0]))

           # show - hide overtone radio button selector
           self._Overtone_radioBtn_isEnabled(False)
           
           # VER 0.1.4 disable datalog sampling time 
           self.ui.cBox_sampling_time.setEnabled(False)
           
           # VER 0.1.6 NOT enable frequency selector in peak detection
           self.ui.cBox_Speed.setEnabled(False)
           # hidden outside Single Measurement
           self.ui.cBox_Speed.setVisible(False)


        # multi frequency measurement
        elif self._get_source() == SourceType.multiscan:
            print(TAG, "Operation mode:  {}".format(Constants.app_sources[2]))  # self._get_source().name
            Log.i(TAG, "Operation mode:  {}".format(Constants.app_sources[2]))

            # show - hide overtone radio button selector
            self._Overtone_radioBtn_isEnabled(True)
            
            # VER 0.1.4 enable datalog sampling time 
            self.ui.cBox_sampling_time.setEnabled(True)


            # init radio button
            self.ui.radioBtn_F0.setChecked(True)
            self.ui.radioBtn_F3.setChecked(True)
            self.ui.radioBtn_F5.setChecked(True)
            self.ui.radioBtn_F7.setChecked(True)
            self.ui.radioBtn_F9.setChecked(True)

            # Phase 3b: mirror the all-checked default on the quick-select row
            self._sync_overtone_buttons_from_radios()

            # VER 0.1.6_TEST NOT enable frequency selector in multi
            self.ui.cBox_Speed.setEnabled(False)
            # hidden outside Single Measurement
            self.ui.cBox_Speed.setVisible(False)
            
            # VER 0.1.6 do not update scan selector here 
# =============================================================================
#             self._update_scan_selector()
# =============================================================================

        '''
        # Clears boxes before adding new
        self.ControlsWin.ui1.cBox_Port.clear()
        self.ControlsWin.ui1.cBox_Speed.clear()
        '''
        '''
        TODO 2m
        '''
        # Clears boxes before adding new
        self.ui.cBox_Port.clear()
        self.ui.cBox_Speed.clear()


        # Gets the current source type
        source = self._get_source()
        ports = self.worker.get_source_ports(source)
        speeds = self.worker.get_source_speeds(source)
        
        '''
        if ports is not None:
            self.ControlsWin.ui1.cBox_Port.addItems(ports)
        if speeds is not None:
            self.ControlsWin.ui1.cBox_Speed.addItems(speeds)
        if self._get_source() == SourceType.serial:
            self.ControlsWin.ui1.cBox_Speed.setCurrentIndex(len(speeds) - 1)
        '''
        '''
        TODO 2m
        '''
        # set COM port
        if ports is not None:
            self.ui.cBox_Port.addItems(ports)
            
        # VER 0.1.6_TEST do not populate the freq drop-down in peak detection and multi
# =============================================================================
#         if speeds is not None:
#             self.ui.cBox_Speed.addItems(speeds)
# =============================================================================

        # populates the drop-down menu with detected freqeuencies
        if self._get_source() == SourceType.serial:
            self.ui.cBox_Speed.addItems(speeds)
            self.ui.cBox_Speed.setCurrentIndex(len(speeds) - 1)


    ###########################################################################
    # Gets the current source type
    ###########################################################################
    def _get_source(self):

        '''
        #:rtype: SourceType.
        return SourceType(self.ControlsWin.ui1.cBox_Source.currentIndex())
        '''
        '''
        TODO 2m
        '''
        return SourceType(self.ui.cBox_Source.currentIndex())

    # LOAD FREQUENCENCIES FILE
    @staticmethod
    def load_frequencies_file():
        data  = loadtxt(Constants.cvs_peakfrequencies_path)
        peaks_mag = data[:,0]
        #peaks_phase = data[:,1] #unused at the moment
        return peaks_mag

    # VER 0.1.6 method just clear plot without making a call to the line 
    def clear_all_plot(self):   
        support = self.worker.get_d1_buffer()
        if support.any:
            if str(support[0])!='nan':
                self._plt2.clear()
                self._pltD.clear()
                self._plt4.clear()
                self._plt0.clear()

###########################################################################
    # Cleans history plot
    ###########################################################################
    def clear(self):
        support = self.worker.get_d1_buffer()
        if support.any:
            if str(support[0])!='nan':
                print(TAG, "All Plots Cleared!", end='\r')
                self._update_sample_size()
                self._plt2.clear()
                self._pltD.clear()
                self._plt4.clear()
                # VER 0.1.6
                self._plt0.clear()
                
                if self._get_source() == SourceType.serial:
                    # VER 0.1.6 after clear the plt create the reference to the lines again 
                    overtone_selected = self._overtones_number_all - self.ui.cBox_Speed.currentIndex() - 1
                    # reference to the line object frequency   
                    self._plt2_line = self._plt2.plot(pen = pg.mkPen(color = Constants.plot_color_multi[overtone_selected], 
                                                                     width = Constants.plot_line_width))
                    # reference to the line object dissipation 
                    self._pltD_line = self._pltD.plot(pen = pg.mkPen(color = Constants.plot_color_multi_diss[overtone_selected], 
                                                                     width = Constants.plot_line_width))
                
                    # VER 0.1.6 after clear the plt create the reference to the ampli lines again 
                    self._plt0_line = self._plt0.plot(pen=self._curve_color(), width = Constants.plot_line_width)
                
                # VER 0.1.6 after clear the plt create the reference to the lines again 
                elif self._get_source() == SourceType.multiscan:
                    # VER 0.1.6 create the multilines
                    # legend
                    for idx in range(self._overtones_number_all):
                        
                        # frequency multilines 
                        self._plt2_multiline[idx] = self._plt2.plot(pen = pg.mkPen(color = Constants.plot_color_multi[idx], 
                                                                                   width = Constants.plot_line_width))
                        # dissipation multilines 
                        self._pltD_multiline[idx] = self._pltD.plot(pen = pg.mkPen(color = Constants.plot_color_multi_diss[idx], 
                                                                                   width = Constants.plot_line_width))
                        
                        # amplitude plot replot multiline
                        self._plt0_multiline[idx] = self._plt0.plot(pen = Constants.plot_color_multi[idx])
                        
# =============================================================================
#                 # reference to the line object temperature 
#                 self._plt4_line = self._plt4.plot(pen=Constants.plot_colors[4])
# =============================================================================
                # VER 0.1.6 reference to the line object temperature                 
                # 
                self._plt4_line = self._plt4.plot(pen=self._curve_color())
                
                # VER 0.1.6 do not autoscale here 
                # enable autoragne here 
# =============================================================================
#                 self._plt4.enableAutoRange(axis= 'y', enable = True)
# =============================================================================
                # VER 0.1.6 autoscale all plot here 
                self._autoscale_plot_all(boolean = True)
                
                if (self._get_source() == SourceType.multiscan):
                    # VER 0.1.6 update legend
                    self._update_legend()
                
                elif (self._get_source() == SourceType.serial):
                    # VER 0.1.5.a add legend in single mode 
                    self._update_legend_single()

                # VER 0.1.2
                # clear amplitude and phase sweep plot
                # VER 0.1.6 do not clear here 
# =============================================================================
#                 self._plt0.clear()
# =============================================================================


    ###########################################################################
    # Reference set/reset
    ###########################################################################
# =============================================================================
#     def reference(self):
#         import numpy as np
#         #import sys
#         support=self.worker.get_d1_buffer()
#         if support.any:
#             if str(support[0])!='nan':
#                 ref_vector1 = [c for c in self.worker.get_d1_buffer() if ~np.isnan(c)]
#                 ref_vector2 = [c for c in self.worker.get_d2_buffer() if ~np.isnan(c)]
#                 self._reference_value_frequency = ref_vector1[0]
#                 self._reference_value_dissipation = ref_vector2[0]
#                 #sys.stdout.write("\033[K") #clear line
#                 if self._reference_flag:
#                     self._reference_flag = False
#                     print(TAG, "Reference reset!   ", end='\r')
#                     self._labelref1 = "not set"
#                     self._labelref2 = "not set"
#                 else:
#                     self._reference_flag = True
#                     d1=float("{0:.2f}".format(self._reference_value_frequency))
#                     d2=float("{0:.4f}".format(self._reference_value_dissipation*1e6))
#                     self._labelref1 = str(d1)+ "Hz"
#                     self._labelref2 = str(d2)+ "e-06"
#                     print(TAG, "Reference set!     ", end='\r')
#                     # TODO minor changes: it calculates (in a unelegant way) the frequency y - range axis
#                     self._vector_reference_frequency[:] = [s - self._reference_value_frequency for s in self._readFREQ]
#                     # TODO minor changes: it calculates (in a unelegant way) the dissipation y - range axis
#                     xs = np.array(np.linspace(0, ((self._readFREQ[-1]-self._readFREQ[0])/self._readFREQ[0]), len(self._readFREQ)))
#                     self._vector_reference_dissipation = xs-self._reference_value_dissipation
# =============================================================================

    ###########################################################################
    # Set reference
    ###########################################################################
    def _toggle_reference(self):
        # Single Set/Clear Reference toggle. reference() may decline to set (no
        # valid data yet), so reflect the actual _reference_flag on the label.
        if self._reference_flag:
            self.reference_not()
        else:
            self.reference()
        self._update_reference_button()

    def _update_reference_button(self):
        self.ui.pButton_Reference.setText(
            "UNSET REF" if self._reference_flag else "SET REF")

    def reference(self):
        import numpy as np

        # SINGLE
        # ---------------------------------------------------------------------
        if self._get_source() == SourceType.serial:
            support = self.worker.get_d1_buffer()
            if support.any:
                if str(support[0])!='nan':
                    ref_vector1 = [c for c in self.worker.get_d1_buffer() if ~np.isnan(c)]
                    ref_vector2 = [c for c in self.worker.get_d2_buffer() if ~np.isnan(c)]

                    # get frequency reference value
                    self._reference_value_frequency = ref_vector1[0]
                    # get dissipation reference value
                    self._reference_value_dissipation = ref_vector2[0]

# =============================================================================
#                     if self._reference_flag:
#                         self._reference_flag = False
#                         print(TAG, "Reference reset!   ", end='\r')
#                         self._labelref1 = "not set"
#                         self._labelref2 = "not set"
#
#                         # clear all
#                         self.clear()
# =============================================================================


                    # VER 0.1.2
                    # changed the function set reference in single mode

                    # set flag reference true
                    self._reference_flag = True

                    # get frequency and dissipation reference value
                    d1=float("{0:.2f}".format(self._reference_value_frequency))
                    d2=float("{0:.4f}".format(self._reference_value_dissipation*1e6))

                    self._labelref1 = str(d1)+ "Hz"
                    self._labelref2 = str(d2)+ "e-06"

                    print(TAG, "Reference set!     ", end='\r')
                    # TODO minor changes: it calculates (in a unelegant way) the frequency y - range axis
                    self._vector_reference_frequency[:] = [s - self._reference_value_frequency for s in self._readFREQ]
                    # TODO minor changes: it calculates (in a unelegant way) the dissipation y - range axis
                    xs = np.array(np.linspace(0, ((self._readFREQ[-1]-self._readFREQ[0])/self._readFREQ[0]), len(self._readFREQ)))
                    self._vector_reference_dissipation = xs-self._reference_value_dissipation

                    # clear all
                    # self.clear()
        # MULTI
        # ---------------------------------------------------------------------
        elif self._get_source() == SourceType.multiscan:

# =============================================================================
#             if self._reference_flag:
#                 print(TAG, "Reference reset!   ", end='\r')
#                 self._reference_flag = False
#                 # clear all
#                 self.clear()
# =============================================================================

            # VER 0.1.2
            # changed the function set reference in multiscan mode

            print(TAG, "Reference set!     ", end='\r')

            # set flag reference true
            self._reference_flag = True

            # get current frequencies overtone array
            for idx in range(self._overtones_number_all):
                frequency_reference = self.worker.get_F_values_buffer(idx)
                self._reference_value_frequency_array[idx] = frequency_reference[0]

            # get current dissipation overtone array
            for idx in range(self._overtones_number_all):
                dissipation_reference = self.worker.get_D_values_buffer(idx)
                self._reference_value_dissipation_array[idx] = dissipation_reference[0]

    ###########################################################################
    # Reset reference
    ###########################################################################
    # VER 0.1.2
    # add reset reference button / function
    def reference_not (self):
        """Unset the reference: the curves go back to absolute values.

        ⚠️ **It used to call clear(), and that was hiding a defect rather than
        undoing anything.** The four `_reference_value_*` holders were never
        reset here, and all four draw sites subtract them **unconditionally** --
        none of them tests `_reference_flag`. So unsetting lowered the flag,
        wiped the panels, and redrew exactly the same offset curves from the
        same buffers. What looked like a reset was the wipe.

        ⚠️ And clearing is not what the operator asked for: the run is still
        going and the history on screen is the measurement. `reference()` has
        had its own `clear()` commented out for that reason; this makes the
        pair symmetric.
        """
        print(TAG, "Reference reset!   ", end='\r')
        self._reference_flag = False

        # what actually unsets the reference. Same values and same shapes as
        # start() uses, so a run that never had a reference and one that had it
        # removed are in the same state.
        self._reference_value_frequency = 0
        self._reference_value_dissipation = 0
        self._reference_value_frequency_array = [0, 0, 0, 0, 0]
        self._reference_value_dissipation_array = [0, 0, 0, 0, 0]

        # the info window prints these next to "Ref. Frequency"/"Ref. Dissipation"
        self._labelref1 = "not set"
        self._labelref2 = "not set"

        # VER 0.1.6 do not set autorange here 
# =============================================================================
#         self._plt2.enableAutoRange(axis= 'y', enable = True)
#         self._pltD.enableAutoRange(axis= 'y', enable = True)
# =============================================================================

    ###########################################################################
    # Checking internet connection
    ###########################################################################
    def internet_on(self):
       from urllib.request import urlopen
       try:
           # VER 0.1.4
           url = "https://openqcm.com/"
           # VER 0.1.4 change timeout on internet connection 
           urlopen(url, timeout = 2)
           return True
       except:
           return False

    ########################################################################################################
    # Gets information from openQCM webpage and enables download button if new version software is available
    ########################################################################################################
    def get_web_info(self, autoMode):
        
        # VER 0.1.4 UPDATE SOFTWARE
        # ---------------------------------------------------------------------
        
        # webpage with release information in form of HTML table
        html_address_next_version = 'https://openqcm.com/shared/next/openqcm_next_software_version.html'
        
        import pandas as pd
        # check if an Internet connection is active
        self._internet_connected = self.internet_on()
        
        # internet connection 
        if self._internet_connected:
            
            labelweb2 = 'ONLINE'
            print (TAG,'Checking your internet connection {} '.format(labelweb2))
            
            # read the html table webpage 
            data_frame_table = pd.read_html(html_address_next_version)
            
# =============================================================================
#             
#             print (len(data_frame_table))
#             print (data_frame_table[0])
# =============================================================================
            
            software_version = data_frame_table[0].iloc[1][0]
            firmware_version = data_frame_table[0].iloc[1][1]
            
# =============================================================================
#             print (software_version)
#             print (firmware_version)
# =============================================================================
            
            # CHECK VERSION AND UPDATE 
            if (software_version != Constants.app_version): 
                
                print ("SOFTWARE UPDATE")
                PopUp.info_not_blocking_rtf(self, "UPDATE SOFTWARE",
                                            "Update Software new version " + str(software_version) + "<br>" + "<br>" + 
                                            "Please visit the openQCM Webpage and download the latest version of the opeQCM python software" + "<br>" + "<br>" + 
                                            "<a href='https://openqcm.com/openqcm-next-software/'>openQCM NEXT Software webpage</a>")
                                                                                
            elif (software_version == Constants.app_version): 
                if (autoMode == True):
                    print ("openQCM Next python software version " + str(Constants.app_version))
                else: 
                    print ("openQCM Next python software version " + str(Constants.app_version))
                    PopUp.info_not_blocking_rtf(self, "Software Information", 
                                                "Software Version " +  str(Constants.app_version) + "<br>"
                                                "openQCM Next most recent software. " + "<br>"  + "<br>"
                                                "For more info please visit " + "<br>" 
                                                "<a href='https://openqcm.com/openqcm-next-software/'>openQCM NEXT Software webpage</a>"
                                                )
        
                
        # no internet connection alert    
        else:
            labelweb2 = 'OFFLINE'
            labelweb3 = 'Offline, unable to check'
            print (TAG,'Checking your internet connection {} '.format(labelweb2))
            # TODO set a pop up alert if noyt connected to internet 
            
        
# =============================================================================
#         # Get latest info from openQCM webpage
#         c_types = {
#                    '1': '1',
#                    '2': '2',
#                    '3': '3',}
#         r_types = {
#                    '1': 'A',
#                    '2': 'B',
#                    '3': 'C',}
#         if self._internet_connected:
#            color = '#00c600'
#            labelweb2 = 'ONLINE'
#            print (TAG,'Checking your internet connection {} '.format(labelweb2))
#            tables = pd.read_html('https://openqcm.com/shared/news.html', index_col=0, header=0, match='1')
#            
#            # VER 0.1.4 TODO check version   
#            df = tables[0]
#            print (df)
#            # create empty list of string
#            self._webinfo = ["" for x in range(len(df.columns)*len(df.index))] #len(df.columns)*len(df.index)=9
#            # row acess mode to Pandas dataframe
#            k=0
#            for j in [1,2,3]:
#               for i in [1,2,3]:
#                   self._webinfo[k]= str(df.loc[r_types[str(j)], c_types[str(i)]])
#                   k+=1
#             # check for update
#            if self._webinfo[0] == Constants.app_version:
#               labelweb3 = 'last version installed!'
#            else:
#               labelweb3 = 'version {} available!'.format(self._webinfo[0])
#               '''
#               self.InfoWin.ui3.pButton_Download.setEnabled(True)
#               '''
#               '''
#               TODO 2m set enabled infowin buton download
#               '''
#         else:
#            color = '#ff0000'
#            labelweb2 = 'OFFLINE'
#            labelweb3 = 'Offline, unable to check'
#            print (TAG,'Checking your internet connection {} '.format(labelweb2))
# =============================================================================

        '''
        self.InfoWin.ui3.lweb2.setText("<font color=#0000ff > Checking your internet connection &nbsp;&nbsp;&nbsp;&nbsp;</font><font size=4 color={}>{}</font>".format(color,labelweb2))
        self.InfoWin.ui3.lweb3.setText("<font color=#0000ff > Software update status </font>" + labelweb3)
        '''
        '''
        TODO 2m set infowin internet connection adn software update
        '''

    ###########################################################################
    # Opens webpage for download
    ###########################################################################
    def start_download(self):
        import webbrowser
        url_download = 'https://openqcm.com/shared/q-1/openQCM_Q-1_py_v{}.zip '.format(self._webinfo[0])
        webbrowser.open(url_download)
        
    def dummy(self): 
        print ("THIS IS DUMMY")

    # VER 0.1.6 open a second window for TEC current monitoring   
    # ------------------------------------------------------------------
    # Tools > Tec Current: the TEC drive current, live (ui/tecCurrentView.py)
    # ------------------------------------------------------------------
    def _open_tec_current_view(self):
        from openQCM.ui.tecCurrentView import TecCurrentDialog

        if self._tec_current_view is not None:
            self._tec_current_view.raise_()
            self._tec_current_view.activateWindow()
            return
        dialog = TecCurrentDialog(theme_name=self._theme, parent=self)
        dialog.destroyed.connect(self._forget_tec_current_view)
        self._tec_current_view = dialog
        dialog.show()

    def _forget_tec_current_view(self, *_args):
        self._tec_current_view = None

    def _close_tec_current_view(self):
        dialog = self._tec_current_view
        self._tec_current_view = None
        if dialog is None:
            return
        try:
            dialog.close()
        except RuntimeError:
            pass

    def _update_tec_current_view(self):
        """Hand the window the TEC-current buffers; called from _update_plot."""
        dialog = self._tec_current_view
        if dialog is None:
            return
        try:
            dialog.update_plot(self.worker.get_t3_buffer(),
                               self.worker.get_data_current_tec_buffer(),
                               start_time=self.start_time)
        except (AttributeError, RuntimeError) as e:
            Log.d(TAG, "Tec Current view not updated: {}".format(e))