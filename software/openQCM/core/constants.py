from enum import Enum
import numpy as np
from pyqtgraph import AxisItem

from openQCM.common.architecture import Architecture,OSType

###############################################################################    
# Enum for the types of sources. Indices MUST match app_sources constant
###############################################################################
class SourceType(Enum):
    # TODO the magic redefine the source type order 
    serial = 1
    calibration = 0
    multiscan = 2
    

###############################################################################
# Specifies the minimal Python version required
###############################################################################
class MinimalPython:
    major = 3
    minor = 2
    release = 0    
 
  
###############################################################################    
# Common constants and parameters for the application.
###############################################################################
class Constants:
    
    ##########################
    # Application Parameters #
    ##########################
    app_title = "openQCM Next Python SW"
    # VER 0.1.5
    # app version is the string checked for software update 
    app_version = '0.1.5'
    app_sources = ["Peak Detection", "Single Measurement", "Multiscan Measurement"]#, "Socket Client"]
    app_encoding = "utf-8"
    
    # VER 0.1.5 Firmware version compatible with the current application
    # check for more information the arduino source code attached
    FW_VERSION = '0.1.5c'

    # VER 0.1.5c the board sweeps once per command and reads serial only at the
    # top of its loop, so a sweep runs to completion whatever the host does.
    # Measured on this instrument: about 1.8 s per overtone, acquisition and
    # processing together. Before asking the board anything the GUI waits for
    # the line to fall silent for serial_quiet_ms, giving up after
    # serial_quiet_timeout_s -- generous against 1.8 s, and short enough that a
    # genuinely stuck board is reported as busy rather than waited on.
    serial_quiet_ms = 250
    serial_quiet_timeout_s = 6.0
    # 'Q' ends a sweep in progress (firmware 0.1.5c and later)
    serial_stop_sweep = b'Q\n'

    ##########################################################################
    # ⚠️ DEV ONLY -- SET accept_test_firmware = False BEFORE A PRODUCTION     #
    # BUILD. The no-TEC prototype board runs the TEST firmware, which reports #
    # '<FW_VERSION>-TEST'. The version check is exact string equality, so     #
    # without this the prototype raises the firmware-update warning on every  #
    # connect. The variant answers every command the production firmware      #
    # does -- the suffix says which board is on the bench, not that the       #
    # protocol is older. A shipped instrument must not accept it silently.    #
    ##########################################################################
    FW_VERSION_TEST_SUFFIX = '-TEST'
    accept_test_firmware = True
    
    ###################
    # PLOT parameters #
    ###################
    
    # TODO DEV SWEEP1HZ change the plot update to 200 mss at least
    
# =============================================================================
#     plot_update_ms = 100
# =============================================================================
    
    # VER 0.1.4
    # change plot update time to 250 ms general improvement of overall software timing
# =============================================================================
#     plot_update_ms = 250
# =============================================================================
    
    # VER 0.1.6 # define the frequency step size fo the sweep plot 
    FREQ_STEP_PLOT = 10
    
    # VER 0.1.6_TEST TODO check the update clock to 50 msec
    # decrease update plot to 50 msec 
    plot_update_ms = 50 # 50

    # VER 0.1.6 development: keep the observable plots (frequency, dissipation,
    # temperature) in autorange. When False, the per-update forced (padded)
    # Y-range is skipped so PyQtGraph autoscales tight to the data; set True and
    # tune the paddings (y_f_range / y_d_range / y_t_range in ui/mainWindow.py)
    # for distribution builds, where a wider fixed range avoids over-emphasising
    # small signal variations.
    plot_force_yrange = False
    
    # VER 0.1.6 set the color to white (unused)
    # plot_colors = ['#ff0000', '#0072bd', '#00ffff', '#edb120', '#000000', '#77ac30', '#4dbeee', '#a2142f'] 
    plot_colors = [(255, 255, 255)]
    
    
    plot_max_lines = len(plot_colors)
    
# =============================================================================
#     plot_line_width = 1.2
# =============================================================================
    # VER 0.1.6_TEST change the line width, you can set width > 1 px withot slowing down the GUI
    # 
    plot_line_width = 2
    
    # #ffffff
    # plot_title_color = 'default'
    # VER 0.1.6 set the color of the axis labels to white whne using a dark background
    # In pyqtgraph, the default text color for the axis labels might be set based on the overall theme or style of the plots. 
    # using a dark background, like (25, 25, 25), the default axis label color might be blending with the background, 
    # making it appear as if it's not visible or appearing dark.
    # explicitly set the color of the axis labels
    plot_title_color = 'w'
    
    # VER 0.1.6 change the temperature color plot to white 
    plot_color_temperature = 'w'
    
    # plot_color_multi = ['r', 'g', 'b']
    # TODO 5M 
    #plot_color_multi = ['r', 'g', 'b', 'y', 'k'] 
    # ['#dc9c00','#d16f2c','#c94923', '#c32b18', '#830913']
    # ['#DF0101','#FFBF00','#01DF01', '#01A9DB', '#7401DF'] 
    
    # VER 0.1.6 change the multiplot colour a "kind of blue" in RGB 
    
    # plot_color_multi = ['#DF0101','#3C3C3C','#01DF01', '#01A9DB', '#7401DF']
    
    
    # plot_color_multi = [(0, 0, 255), (70, 130, 255), (135, 206, 250), (173, 216, 230), (240, 248, 255)]
    
    # plot_color_multi = [(0, 0, 255), (70, 99, 255), (122, 160, 255), (173, 182, 255), (255, 228, 255)]
    
    # Frequency curves. The first three are the identity blues and are untouched;
    # the last two were pulled down in luminance (205 -> 184, 241 -> 211) because
    # the light plot panel is the interface grey at 244 and #BFFFFF sat 3 points
    # from it: F9 read by its cyan tint alone, and on the instrument it was barely
    # there. 211 is the same ceiling the dissipation ramp uses, so both series now
    # clear the panel by 33.
    plot_color_multi = [
    (0, 0, 255),      # Blu puro                      Y= 18
    (0, 127, 255),    # Blu medio-azzurro             Y=109
    (0, 191, 255),    # Azzurro brillante             Y=155
    (96, 204, 239),   # #60CCEF, azzurro chiaro       Y=184
    (146, 228, 235)   # #92E4EB, ciano chiaro         Y=211
    ]
                         
    # Dissipation curves: the brown family of the interface, on a ramp built to
    # be *read*, not to mirror the blue one.
    #
    # The first attempt reused the blues' fractions of the way to white. It
    # failed on the instrument: brown starts light (luminance 156 against pure
    # blue's 18), so the five ended up inside a 58-point band with steps of
    # 10-13 and the middle overtones were not separable by eye.
    #
    # This ramp is specified in luminance instead: hue locked to the interface
    # brown's 18.4 deg, saturation falling 0.85 -> 0.26, and V solved per entry so
    # that Rec. 709 luminance lands on 70, 105, 140, 176, 211 -- steps of 35, near
    # three times the old ones. The ends are bounded by the two plot backgrounds
    # they have to survive: 70 stays above the dark panel (43), and 211 stays
    # below the light panel, which is why that one is a grey and not white
    # (see theme.PLOT).
    plot_color_multi_diss = [
    (135, 56, 20),    # #873814
    (174, 90, 52),    # #AE5A34
    (206, 126, 91),   # #CE7E5B, the interface brown's neighbour
    (229, 164, 135),  # #E5A487
    (247, 203, 183)   # #F7CBB7
    ]

    # plot-legend text per overtone. The fundamental is the FIRST harmonic;
    # it read "0th" until 2026-07-29. Read from here everywhere, including
    # the removeItem calls that take the legend entry by name, so the value
    # can change but must stay a single source.
    name_legend = ["1st", "3rd", "5th", "7th", "9th"]                        
    
    overtone_dummy = [0, 1, 2, 3, 4]
    
    # VER 0.1.6 change the background plot color
    # white 
    # plot_background_color = "w"
    # black
    # plot_background_color = "k"
    
    # VER 0.1.6_TEST chage the background color to dark 
    plot_background_color = (25, 25, 25)
    
    # samples of data ring buffer 
    # VER 0.1.4 reduce ring buffer size to 10 samples
# =============================================================================
#     environment = 50
# =============================================================================
    
    # VER 0.1.6 temporary 4 samples for saving time in dev mode
# =============================================================================
#     environment = 10 # 4 samples in developemtn mode just for saving time chenage
# =============================================================================

    # ##################################################################### #
    # PRODUCTION VALUE: environment = 8 (Marco, 2026-10-01).                #
    # ##################################################################### #
    # The length of the averaging ring buffer and of the warm-up: how many
    # sweeps go into each logged point, and how many cycles pass before the
    # first one is logged. Lowered to 3 during development (2026-07-29) so a
    # test run left warm-up almost immediately; set to 8 on 2026-10-01. If the
    # warm-up proves too long in practice it may be lowered again -- the cost
    # is purely metrological.
    #
    # It used to be more than that: with scipy's trim_mean, which cuts
    # int(proportiontocut * N) samples per tail, any N below ten cut nothing and
    # the outlier rejection silently became a plain arithmetic mean. That
    # dependency is gone -- core/averaging.py keeps a floor of one sample per
    # tail at every buffer size -- so shortening the buffer no longer costs
    # robustness. Measured on the replay with one 40 Hz bad sweep: at N=3 the old
    # average was 12 Hz off, the new one lands on the median.
    environment = 8
    
    # VER 0.1.6 reduce the real-time chart history length to 8192 samples 
    ring_buffer_samples = 8192 # 16384
    
    PID_default_settings = ["Default #0 (Factory)", "Default #1"]
    
    # default factory #0 and default openQCM #1 list element
    cycling_time_setting  = [50, 50]
    P_share_setting  = [1000, 500]
    I_share_setting  = [200, 50]
    D_share_setting  = [100, 300]
    
    PID_Setting_default_index = 1
    
    # set temperature default parameter
    Temperature_Set_Value = 25.00
    # set PID default parameter 
    cycling_time_default = cycling_time_setting[1]
    P_share_default = P_share_setting[1]
    I_share_default = I_share_setting[1]
    D_share_default = D_share_setting[1]
    # boolean variable temperature setting 
    PID_boolean_default = 0 
    # boolean control temperature setting 
    CTRL_boolean_default = 0
    
    # VER 0.1.4 init the sampling time list
    SAMPLING_TIME_LIST = ["Default", "10", "30", "60"]
    SAMPLING_TIME_LIST_DEFAULT_INDEX = 0
    
    # VER 0.1.4
    # define and init TEC status control variable
    # -------------------------------------------
    # temperature control active, temperature is out of range, electric current is null
    STATUS_CONTROL_ACTIVE_LOW_CURRENT_NULL = -1
    
    # temperature control NOT active 
    STATUS_CONTROL_NOT_ACTIVE = 0
    
    # temperature control active, temperature is out of range, electric current is NOT null
    STATUS_CONTROL_ACTIVE_LOW_CURRENT_NOT_NULL = 1
    
    # temperature control active and temperature in range
    STATUS_CONTROL_ACTIVE_HIGH = 2
    
    # VER 0.1.5
    # init MTD415T error register list, 
    # as in paragraph 6.3 Error Register and Safety Bitmask, MTD415T Data Sheet Rev. 1.2
    # ⚠️ One name per bit, 16 entries, bit 13 = "Value out of range" and
    # bit 14 = "Invalid command" as in the data sheet. A missing comma used to
    # glue two entries together, leaving 15 names with bits 13 and 14 wrongly
    # labelled (fixed 2026-09-09). Decoded in common/tecStatus.py.
    ERROR_REG_EVENT = ["Enable pin not set",              # bit 0
                       "Internal temperature too high",   # bit 1
                       "Thermal Latch-Up",                # bit 2
                       "Cycling time too small",          # bit 3
                       "No Sensor detected",              # bit 4
                       "No TEC detected",                 # bit 5
                       "TEC mispoled",                    # bit 6
                       "Not used", "Not used", "Not used",            # bits 7-9
                       "Not used", "Not used", "Not used",            # bits 10-12
                       "Value out of range",              # bit 13
                       "Invalid command",                 # bit 14
                       "Not used"]                        # bit 15
    
    
     
    ####################
    #  SAMPLES NUMBER  #
    ####################
    
    # VER 0.1.4
    # change the sweep parameters to 12 KHz left range and 6 KHz right range 
    # for a total range fo frequency sweep = 18 KHz
    LEFT = 12000
# =============================================================================
#     RIGHT = 6000
# =============================================================================
    # VER 0.1.4 increase sweep right range, because the sweep box is now center on the peak of the resonance curve     
    RIGHT = 6000
    
    # VER 0.1.3 
    # change the spline factor for a better smoothing of the raw amplitude signal 
    # SPLINE_FACTOR = 0.1     # VER 0.1.3 TODO spline factor depends on the number of sample SAMPLES = int((LEFT + RIGHT)/FREQUENCY_STEP)

    # VER 0.1.4 increase spline factor for smoothing with 1 Hz sampling frequency   
    SPLINE_FACTOR = 1
    # VER 0.1.4 find the best spline factor 
        
# =============================================================================
#     argument_default_samples = 501#1001
#     SAMPLES = 500 
# =============================================================================
        
    # VER 0.2 BETA TODO
    # change the number of data points so that you have a frequency sweep step of 1 HZ 
# =============================================================================
#     argument_default_samples = int((LEFT + RIGHT)/1 + 1)
#     SAMPLES = int((LEFT + RIGHT)/1)
# =============================================================================
    
    # VER 0.1.3 change the number of data points so that you have a frequency sweep step of 50 Hz
    # FREQUENCY_STEP = 50 
    
    # VER 0.1.4 decrease the frequency sampling rate to 1 Hz  
    # change frequency step to change the frequency sampling rate and the sweep data points accordingly
    FREQUENCY_STEP = 1
    argument_default_samples = int((LEFT + RIGHT)/FREQUENCY_STEP + 1)
    SAMPLES = int((LEFT + RIGHT)/FREQUENCY_STEP)
    
    # VER 0.1.4 define the threshold in dB for the bandwidth calculation 
    THRESHOLD_DB = 0.3
    
    ###########################
    # Ring Buffers Parameters #
    ###########################
   
    
    # TODO MAXIMUM NUMBER OF OVERTONES 
    overtone_maximum_number = 4
    
    ####################################
    # FILTERING and FITTING parameters #
    ####################################
    # Notes:
    # left and right frequencies in the area of the resonance frequency
    # Savitzky-Golay size of the data window 
    # Savitzky-Golay order of the polynomial fit
    # Number of spline points: same as the frequency band +1 (es.5001)
    # Spline smoothing factor
    
    # Savitzky-Golay order of the polynomial fit (common for all)
    SG_order = 3

    # Order of the least-squares polynomial that estimates the baseline of the
    # full-span calibration sweep, subtracted before anything looks for a peak.
    # It was written as a literal 8 in seven places -- both baseline_coeffs, both
    # channels of the peak detection, and the offline viewer -- which is how a
    # viewer ends up correcting a baseline the instrument did not. Anything that
    # reproduces the measurement has to read it from here.
    BASELINE_POLY_ORDER = 8
    
    # VER 0.1.4 TODO
    # Savitzky-Golay window size definition 
    SG_WINDOW_SIZE = 51
    
# =============================================================================
#     #--------------
#     # 5MHz 
#     #--------------
#     # left and right frequencies
#     L5_fundamental = 18000
#     R5_fundamental = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size5_fundamental = 9
#     # Spline smoothing factor
#     Spline_factor5_fundamental = 0.05
#     
#     # left and right frequencies
#     L5_3th_overtone = 18000
#     R5_3th_overtone = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size5_3th_overtone = 11
#     # Spline smoothing factor
#     Spline_factor5_3th_overtone = 0.01
#     
#     # left and right frequencies
#     L5_5th_overtone = 18000
#     R5_5th_overtone = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size5_5th_overtone = 11
#     # Spline smoothing factor
#     Spline_factor5_5th_overtone = 0.01
#     
#     # VER 0.1.2
#     # change the sweep range same sweep range for all overtones
#     
#     # left and right frequencies
# # =============================================================================
# #     L5_7th_overtone = 50000
# #     R5_7th_overtone = 7000
# #     # Savitzky-Golay size of the data window 
# #     SG_window_size5_7th_overtone = 33
# #     # Spline smoothing factor
# #     Spline_factor5_7th_overtone = 0.01
# # =============================================================================
#     L5_7th_overtone = 18000
#     R5_7th_overtone = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size5_7th_overtone = 11
#     # Spline smoothing factor
#     Spline_factor5_7th_overtone = 0.01
#     
#     
#     
#     # TODO
# # =============================================================================
# #     # left and right frequencies 
# #     L5_9th_overtone = 50000
# #     R5_9th_overtone = 7000
# #     # Savitzky Golay size of the data window 
# #     SG_window_size5_9th_overtone = 5
# #     # Spline smoothing factor
# #     Spline_factor5_9th_overtone = 0.5
# # =============================================================================
#     # left and right frequencies 
#     L5_9th_overtone = 18000
#     R5_9th_overtone = 7000
#     # Savitzky Golay size of the data window 
#     SG_window_size5_9th_overtone = 11
#     # Spline smoothing factor
#     Spline_factor5_9th_overtone = 0.5
# =============================================================================
    
    # VER 0.1.4
    # change 5 MHz sweep parameters, start, stop, Savitzky Golay and spline filter parameters 
    #--------------
    # 5MHz 
    #--------------
    # left and right frequencies
    L5_fundamental = LEFT
    R5_fundamental = RIGHT
    # Savitzky-Golay size of the data window 
    SG_window_size5_fundamental = SG_WINDOW_SIZE
    # Spline smoothing factor
    Spline_factor5_fundamental = SPLINE_FACTOR
    
    # left and right frequencies
    L5_3th_overtone = LEFT
    R5_3th_overtone = RIGHT
    # Savitzky-Golay size of the data window 
    SG_window_size5_3th_overtone = SG_WINDOW_SIZE
    # Spline smoothing factor
    Spline_factor5_3th_overtone = SPLINE_FACTOR
    
    # left and right frequencies
    L5_5th_overtone = LEFT
    R5_5th_overtone = RIGHT
    # Savitzky-Golay size of the data window 
    SG_window_size5_5th_overtone = SG_WINDOW_SIZE
    # Spline smoothing factor
    Spline_factor5_5th_overtone = SPLINE_FACTOR
    
    # VER 0.1.2
    # change the sweep range same sweep range for all overtones
    
    # left and right frequencies
# =============================================================================
#     L5_7th_overtone = 50000
#     R5_7th_overtone = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size5_7th_overtone = 33
#     # Spline smoothing factor
#     Spline_factor5_7th_overtone = 0.01
# =============================================================================
    L5_7th_overtone = LEFT
    R5_7th_overtone = RIGHT
    # Savitzky-Golay size of the data window 
    SG_window_size5_7th_overtone = SG_WINDOW_SIZE
    # Spline smoothing factor
    Spline_factor5_7th_overtone = SPLINE_FACTOR
    
    # left and right frequencies 
    L5_9th_overtone = LEFT
    R5_9th_overtone = RIGHT
    # Savitzky Golay size of the data window 
    SG_window_size5_9th_overtone = SG_WINDOW_SIZE
    # Spline smoothing factor
    Spline_factor5_9th_overtone = SPLINE_FACTOR

    #--------------
    # 10MHz 
    #--------------
    # VER 0.1.4
    # change 10 MHz sweep parameters
    
# =============================================================================
#     # left and right frequencies
#     L10_fundamental = 18000
#     R10_fundamental = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size10_fundamental = 11
#     # Spline smoothing factor
#     Spline_factor10_fundamental = 0.01
#     
#     # left and right frequencies
#     L10_3th_overtone = 18000
#     R10_3th_overtone = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size10_3th_overtone = 11    
#     # Spline smoothing factor
#     Spline_factor10_3th_overtone = 0.01
# =============================================================================
    # VER 0.1.4    
    # left and right frequencies fundamental 
    L10_fundamental = LEFT
    R10_fundamental = RIGHT
    # Savitzky-Golay size of the data window 
    SG_window_size10_fundamental = SG_WINDOW_SIZE
    # Spline smoothing factor
    Spline_factor10_fundamental = SPLINE_FACTOR
     
    # left and right frequencies 3rd overtone
    L10_3th_overtone = LEFT
    R10_3th_overtone = RIGHT
    # Savitzky-Golay size of the data window 
    SG_window_size10_3th_overtone = SG_WINDOW_SIZE    
    # Spline smoothing factor
    Spline_factor10_3th_overtone = SPLINE_FACTOR
    
    # left and right frequencies 5th overtone
    L10_5th_overtone = LEFT
    R10_5th_overtone = RIGHT
    # Savitzky-Golay size of the data window 
    SG_window_size10_5th_overtone = SG_WINDOW_SIZE
    # Spline smoothing factor
    Spline_factor10_5th_overtone = SPLINE_FACTOR
     
# =============================================================================
#     # left and right frequencies
#     # TODO check 5th overtone
#     L10_5th_overtone = 25000
#     R10_5th_overtone = 5000
#     # Savitzky-Golay size of the data window 
#     SG_window_size10_5th_overtone = 19
#     # Spline smoothing factor
#     Spline_factor10_5th_overtone = 0.01
# =============================================================================
    
# =============================================================================
#     # VER 0.1.2
#     # change the sweep range same sweep range for all overtones
#     # left and right frequencies
#     # TODO check 5th overtone
#     L10_5th_overtone = 18000
#     R10_5th_overtone = 7000
#     # Savitzky-Golay size of the data window 
#     SG_window_size10_5th_overtone = 11
#     # Spline smoothing factor
#     Spline_factor10_5th_overtone = 0.01
# =============================================================================
  
    ##########################
    # SERIAL PORT Parameters #
    ##########################
    serial_default_speed = 115200
    serial_default_overtone = None
    serial_default_QCS = "@10MHz"
    
# =============================================================================
#     serial_writetimeout_ms = 1
#     serial_timeout_ms = None#0.01
# =============================================================================
    
    # DEBUG_0.1.1a
# =============================================================================
#     serial_writetimeout_ms = 0.5
#     serial_timeout_ms = 0.5
# =============================================================================
    
    # VER 0.1.4
    # change / increased serial timeout parameters to improve the serial communication 
    serial_writetimeout_ms = 4.0
    serial_timeout_ms = 4.0
    
    null_string = ""
    
    # insert timeout in while acquisition loop 
    # to prevent infinite blocking loop default value 0.5 sec
# =============================================================================
#     TIME_ELAPSED_TIMEOUT = 0.5 
# =============================================================================
    
    # VER 0.1.4
    # change / increased serial time elasped timeout to improve the serial communication 
    TIME_ELAPSED_TIMEOUT = 4.0
    
    WRITE_SERIAL_WAIT = 0.1 
    
    
    # VER 0.1.4
    # TIME WAITING CONSTANTS 
    SLEEP_EOM_MULTISCAN = 0.05
    SLEEP_EOM_SINGLE    = 0.2
    
    ######################
    # Process parameters #
    ######################
    # VER 0.1.4
    # change / increased the process join timeout
    process_join_timeout_ms = 4000
    simulator_default_speed = 0.1 # not used
    parser_timeout_ms = 0.005
    
    
    ##################
    # Log parameters #
    ##################
    log_export_path = "logged_data"
    log_filename = "{}.log".format(app_title)
    log_max_bytes = 5120
    log_default_level = 1
    log_default_console_log = False
    

    ######################################
    # File parameters for exporting data #
    ######################################
    # sets the slash depending on the OS types
# =============================================================================
#     if Architecture.get_os() is (OSType.macosx or OSType.linux):
#        slash="/"
#     else:
#        slash="\\"
# =============================================================================
    
    # VER 0.1.2 
    # set directory slash, solving bug for macOS Big Sur
    # sets the slash depending on the OS types
    # if Architecture.get_os() is (OSType.linux or OSType.macosx):
    
    # VER 0.1.6 linux bug fixing for path separator
    if Architecture.get_os() in {OSType.macosx, OSType.linux}:    
        # print ("MAC_OS_X")
        slash = "/"

    elif Architecture.get_os() is OSType.windows:
        # print("WINDOWS")
        slash = "\\"
    else:
        # print ("OTHER_OS")
        slash = "/"
       
    csv_delimiter = "," # for splitting data of the serial port and CSV file storage
    csv_default_prefix = "%Y-%m-%d_%H-%M-%S" # datalog timestamp: YYYY-MM-DD_hh-mm-ss
    csv_extension = "csv"
    txt_extension = "txt"
    csv_export_path = "logged_data"
    
    # DEV RAWDATA
    sweep_export_path = "sweep_data"

    # Raw sweep dump to sweep_export_path: a development tool, off in release.
    # Nothing reads these files except the older "Raw Data (from sweep files)"
    # viewer, which is hidden while this is off; the live Raw Data View works
    # from memory and is unaffected. Override for one session without editing
    # anything: OPENQCM_SWEEP_DUMP=1 python3 run.py
    dev_sweep_dump = False
    
    # No datalog name is composed here: a name built in the class body carries
    # the time the module was imported, not the time START was pressed. The
    # acquisition composes it in Worker.start() from csv_default_prefix.
    csv_sweeps_filename = "sweep"
    
    # Calibration: scan (WRITE for @5MHz and @10MHz QCS) path: 'common\'
    csv_calibration_filename    = "Calibration_5MHz"
    csv_calibration_filename10  = "Calibration_10MHz"
    csv_calibration_export_path = "openQCM" #"common"
    
    ################## 
    # Calibration: baseline correction (READ for @5MHz and @10MHz QCS) path: 'common\'
    csv_calibration_path   = "{}{}{}.{}".format(csv_calibration_export_path,slash,csv_calibration_filename,txt_extension)
    csv_calibration_path10 = "{}{}{}.{}".format(csv_calibration_export_path,slash,csv_calibration_filename10,txt_extension)
    
    # Frequencies: Fundamental and overtones (READ and WRITE for @5MHz and @10MHz QCS)
    csv_peakfrequencies_filename   = "PeakFrequencies"
    #csv_peakfrequencies_filename   = "PeakFrequencies_5MHz"
    #csv_peakfrequencies_filename10 = "PeakFrequencies_10MHz"
    cvs_peakfrequencies_path    = "{}{}{}.{}".format(csv_calibration_export_path,slash,csv_peakfrequencies_filename,txt_extension)
    #cvs_peakfrequencies_path10 = "{}{}{}.{}".format(csv_calibration_export_path,slash,csv_peakfrequencies_filename10,txt_extension)    
    
    
    # VER 0.1.4
    # add a new peak freqencies file storing the current value of resonance frequencies 
    csv_peakfrequencies_RT_filename   = "PeakFrequenciesRT"
    cvs_peakfrequencies_RT_path    = "{}{}{}.{}".format(csv_calibration_export_path, slash, csv_peakfrequencies_RT_filename, txt_extension)
    
    
    #########################    
    '''
    # Calibration: baseline correction (READ for @5MHz and @10MHz QCS) path: 'common\'
    csv_calibration_path   = "{}\{}.{}".format(csv_calibration_export_path,csv_calibration_filename,txt_extension)
    csv_calibration_path10 = "{}\{}.{}".format(csv_calibration_export_path,csv_calibration_filename10,txt_extension)
    
    # Frequencies: Fundamental and overtones (READ and WRITE for @5MHz and @10MHz QCS)
    csv_peakfrequencies_filename   = "PeakFrequencies"
    #csv_peakfrequencies_filename   = "PeakFrequencies_5MHz"
    #csv_peakfrequencies_filename10 = "PeakFrequencies_10MHz"
    cvs_peakfrequencies_path    = "{}\{}.{}".format(csv_calibration_export_path,csv_peakfrequencies_filename,txt_extension)
    #cvs_peakfrequencies_path10 = "{}\{}.{}".format(csv_calibration_export_path,csv_peakfrequencies_filename10,txt_extension)
    '''
    
    # TODO freuqwency start and stop file path
    manual_frequencies_filename = "config"
    manual_frequencies_path = "{}{}{}.{}".format(csv_calibration_export_path,slash,manual_frequencies_filename,txt_extension)
    
    sweep_file = "sweep"
    sweep_file_path = "{}{}{}.{}".format(csv_calibration_export_path, slash, sweep_file , txt_extension)
    
# =============================================================================
#     #  DEBUG_0.1.1a
#     debug_file = "debug"
#     debug_file_path = "{}{}{}.{}".format(csv_calibration_export_path, slash, debug_file , txt_extension)
# =============================================================================
    
    ##########################
    # CALIBRATION PARAMETERS #
    ##########################
    
    # Peak Detection - distance in samples between neighbouring peaks
# =============================================================================
#     dist5  =  8000 # for @5MHz
#     dist10 =  10000 # for @10MHz
# =============================================================================
# =============================================================================
#     calibration_default_samples = 50001
# =============================================================================
    calibration_frequency_start =  1000000
    calibration_frequency_stop  = 51000000 
# =============================================================================
#     calibration_fStep = (calibration_frequency_stop - calibration_frequency_start) / (calibration_default_samples-1)
# =============================================================================
# =============================================================================
#     calibration_readFREQ  = np.arange(calibration_default_samples) * (calibration_fStep) + calibration_frequency_start
# =============================================================================
    #-------------------
    
    
# =============================================================================
#     calib_fStep = 1000
#     calib_fRange = 5000000 #
#     calib_samples = 5001
#     calib_sections = 10
# =============================================================================

    # VER 0.1.4a Change the calibration frequency step to increase the resolution 
    # calibration frequewncy range for each section 
    calib_fRange = 5000000 
    # calibration frequency section 
    calib_sections = 10
    
    # VER 0.1.4a CHANGE CALIBRATION  FREQUENCY STEP to 500 Hz 
    calib_fStep = 500
    calibration_fStep = calib_fStep
    
    # number of samples in a calibration section 
    calib_samples = int((calib_fRange / calib_fStep) + 1)
    
    # VER 0.1.4a calibration total frequency array 
    calibration_default_samples = int( (calib_samples - 1) * calib_sections) + 1
    calibration_readFREQ  = np.arange(calibration_default_samples) * (calib_fStep) + calibration_frequency_start
    

    # VER 0.1.4a change the peak detection distance in accordance with the frequency step
    # Peak Detection - distance in samples between neighbouring peaks
    # 5 MHz sensor minimum frequency distance between successive peaks = 8 MHz
    dist5MHz = 8000000
    # 5 MHz sensor minimum frequency distance between successive peaks = 10 MHz
    dist10MHz = 10000000 
    # 5 MHz minimum distance in terms of samples
    dist5  =  int(dist5MHz/calib_fStep) 
    # 10 MHz minimum distance in terms of samples
    dist10 =  int(dist10MHz/calib_fStep)
     
    
    ##############################
    # Parameters for the average #
    ##############################  
   
    SG_order_environment = 1
    SG_window_environment = 3

    # VER 0.1.6 anti-outlier robust averaging of the raw circular buffer, which
    # replaced the old Savitzky-Golay + np.average, a linear filter with no
    # outlier rejection.
    # Consumed by core/averaging.py, not by scipy.stats.trim_mean: the proportion
    # governs how much is cut per tail on a large buffer, but with a floor of one
    # sample and a ceiling of (N-1)//2. scipy's int(proportiontocut * N) is zero
    # for any N below ten, which made the rejection an accident of
    # `environment == 10` rather than a property of the average. The name is kept
    # because it is read in six places and the value is unchanged.
    trim_mean_proportiontocut = 0.10
    
    ###################
    class SocketClient: #unused
        timeout = 0.01
        host_default = "localhost"
        port_default = [5555, 8080, 9090]
        buffer_recv_size = 1024
    ###################  



###############################################################################
#  Provides an elapsed-time axis
###############################################################################

def format_elapsed_seconds(t):
    """Elapsed seconds as SS / M:SS / H:MM:SS. Negative values clamp to zero.

    The one definition of the format. Datalog View reads it too: it holds the
    same run in relative seconds, and a reader who has just seen 5:00 on the
    instrument should not have to translate 0:05:00 there.
    """
    if t < 0:
        t = 0
    if t >= 3600:
        return "{}:{:02d}:{:02d}".format(int(t // 3600), int((t % 3600) // 60), int(t % 60))
    if t >= 60:
        return "{}:{:02d}".format(int(t // 60), int(t % 60))
    return "{}".format(int(t))


# VER 0.1.6 ported from openQCM Q-1 v3.0, which replaced the seconds axis with
# this one. The plotted x values stay epoch microseconds; only the tick labels
# are relative, so nothing about the buffers or the datalog moves.
class ElapsedTimeAxis(AxisItem):
    """
    Format elapsed time relative to a start reference as SS / M:SS / H:MM:SS.

    The reference is latched once with `set_start_time(value)`, in the same
    unit as the plotted values (epoch microseconds), and cleared with
    `reset_start_time()` when a new acquisition starts. While it is unset the
    axis draws **empty** labels: the alternative is to print the epoch, which
    is what the previous seconds axis did for the whole warm-up.
    """

    TS_MULT_us = 1e6

    def __init__(self, *args, **kwargs):
        super(ElapsedTimeAxis, self).__init__(*args, **kwargs)
        self._start_time = None

    def tickStrings(self, values, scale, spacing):
        try:
            if not len(values):
                return []
            if self._start_time is None:
                return [''] * len(values)

            return [format_elapsed_seconds(
                        (float(v) - float(self._start_time)) / self.TS_MULT_us)
                    for v in values]
        except Exception:
            return [''] * len(values)

    def set_start_time(self, start_time):
        """Latch the reference once, ignoring None and NaN."""
        if self._start_time is None and start_time is not None:
            try:
                val = float(start_time)
                if not np.isnan(val):
                    self._start_time = val
            except (ValueError, TypeError):
                pass

    def reset_start_time(self):
        """Clear the reference so the next acquisition latches its own."""
        self._start_time = None


###############################################################################
#  Provides a non scientific axis notation
###############################################################################  
class NonScientificAxis(AxisItem):
    def __init__(self, *args, **kwargs):
        super(NonScientificAxis, self).__init__(*args, **kwargs)

    def tickStrings(self, values, scale, spacing):
        return [int(value*1) for value in values] 
