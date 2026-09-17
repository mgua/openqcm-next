from multiprocessing import Queue

from openQCM.core.constants import Constants, SourceType
from openQCM.processors.Parser import ParserProcess
from openQCM.processors.Serial import SerialProcess
from openQCM.processors.SocketClient import SocketProcess
from openQCM.processors.Calibration import CalibrationProcess
from openQCM.processors.Multiscan import MultiscanProcess
from openQCM.common.fileStorage import FileStorage
from openQCM.common.logger import Logger as Log
from openQCM.core.ringBuffer import RingBuffer
import numpy as np
from time import time
from numpy import loadtxt
import datetime

# VER 0.1.2
from time import strftime, localtime

# VER 0.1.2
from time import sleep

#import pywt

TAG = ""#"[Worker]"

###############################################################################
# Service that creates and concentrates all processes to run the application
###############################################################################
class Worker:

    ###########################################################################
    # Creates all processes involved in data acquisition and processing
    ###########################################################################
    def __init__(self,QCS_on = None,
                      port = None,
                      speed = Constants.serial_default_overtone,
                      samples = Constants.argument_default_samples,
                      source = SourceType.serial,
                      export_enabled = False, 
                      sampling_time = None):
        """
        :param port: Port to open on start :type port: str.
        :param speed: Speed for the specified port :type speed: float.
        :param samples: Number of samples :type samples: int.
        :param source: Source type :type source: SourceType.
        :param export_enabled: If true, data will be stored or exported in a file :type export_enabled: bool.
        :param export_path: If specified, defines where the data will be exported :type export_path: str.
        """
        # data queues 
        self._queue1 = Queue()
        self._queue2 = Queue()
        self._queue3 = Queue()
        self._queue4 = Queue()
        self._queue5 = Queue()
        
        # VER 0.1.6 init TEC current queue
        self._queueCurrentTec = Queue()
       
        
        self._queue6 = Queue()
        
        self._queue_F_multi = Queue()
        self._queue_D_multi = Queue()
        
        # TODO AMPLI init the queue for amplitude sweep 
        self._queue_A_multi = Queue()
        self._queue_P_multi = Queue()
        self._queue_F_SWEEP_multi = Queue()
        # lines the acquisition process wants the operator to read
        self._queue_message = Queue()
        # the controller's PID as read by the acquisition process on request
        self._queue_pid = Queue()
        self._pid_reported = None
        
        # TODO AMPLI init the list of array for amplitude sweep
        self._A_multi = None 
        self._P_multi = None 
        
# =============================================================================
#         array_zero = self._zerolistmaker(Constants.SAMPLES)
#         self._A_multi_buffer = [ array_zero, array_zero, array_zero, array_zero, array_zero ]

#        self._F_Sweep_multi_buffer = [ array_zero, array_zero, array_zero, array_zero, array_zero]
# =============================================================================
        
        self._A_multi_buffer = None
        self._P_multi_buffer = None
        self._F_Sweep_multi_buffer = None
        
        # data buffers
        self._data1_buffer = None # amplitude 
        self._data2_buffer = None # phase 
        self._d1_buffer = None  # Frequency     type RingBuffer
        self._d2_buffer = None  # Dissipation   type RingBuffer
        self._d3_buffer = None  # Temperature   type RingBuffer
        
        # VER 0.1.6 init the variable for TEC current 
        self._data_current_tec_buffer = None # TEC current  type RingBuffer
        
        self._t1_buffer = None  # time (frequency) type RingBuffer
        self._t2_buffer = None  # time (dissipation) type RingBuffer
        self._t3_buffer = None  # time (temperature) type RingBuffer
        self._ser_error1 = 0
        self._ser_error2 = 0
        self._ser_err_usb= 0
        self._control_k = 0
        
        self._F_multi_buffer = None
        self._D_multi_buffer = None
        
        self._F_store = None 
        self._D_store = None 
        self._time_buffer = None
        self._time_store = None
        
        # current overtone number 
        self._overtone_number = 0
        # the datalog clock (multiscan): which overtone the last temperature
        # message belonged to, and whether it closed a cycle -- read from THAT
        # message, never from another queue (see _queue_data5, store_data)
        self._cycle_overtone = 0
        self._cycle_end = False
        self._cycle_F = None
        self._cycle_D = None
        # total number of overtone 
        self._number_of_peaks = 0
        
        # VER 0.1.4
        # TEC status var
        self._TEC_status = 0
        # the MTD415T error register as the last temperature sample carried it
        self._TEC_error_register = 0
        
        # instances of the processes
        self._acquisition_process = None
        self._parser_process = None

        # VER 0.1.6 peak-detection (calibration) user-cancellation flag, latched
        # from the -1 sentinel that CalibrationProcess emits on parser5 when the
        # user presses Stop mid-sweep. Read by the GUI via is_calibration_cancelled().
        self._calibration_cancelled = False

        # others
        self._QCS_on = QCS_on # QCS installed on device (unused now)
        self._port = port     # serial port 
        # overtones (str) if 'serial' is called
        # QCS (str) if 'calibration' is called 
        self._speed = speed 
        self._samples = samples
        self._source = source
        self._export = export_enabled
        
        # Supporting variables
        self._d1_store = None # data storing
        self._d2_store = None # data storing
        
        # SINGLE 
        self._readFREQ = None # frequency range
        self._fStep    = None # sample rate
        self._overtone_name  = None # fundamental/overtones name (str)
        self._overtone_value = None # fundamental/overtones value(float)
        
        # MULTI 
        self._readFREQ_array = None 
        
        self._count = 0 # sweep counter
        self._flag = True
        self._timestart = 0
        
        # VER 0.1.2
        # init log file name 
        self._csv_filename = ""
        
        # VER 0.1.4
        self._sampling_time = sampling_time
        self.time_elapsed = 0

        # VER 0.1.6 wall-clock start of the run, in SECONDS.
        # ⚠️ Deliberately not _timestart, which is seconds in single mode and
        # epoch microseconds in multiscan -- the same unit split HANDOFF warns
        # about for start_time. A readout that must work in both modes cannot
        # be built on a value whose unit depends on the mode, and unifying
        # _timestart would move the datalog's relative-time column in both
        # processors. One private, unambiguous reference instead.
        self._run_started = None

        # VER 0.1.6 when the previous datalog row was written, in SECONDS, for
        # the single-mode sampling interval. Multiscan keeps its own time_pre
        # in epoch microseconds; the two are not interchangeable.
        self._last_datalog_write = None
        # init a ring buffer of corresponding size 
        # VER 0.1.4 TODO checkthe default smapling time 
        SAMPLING_TIME_DEFAULT = 7
        self.ring_buffer_len =  1
        
        # init a list of ring buffer 
        self._F_store_buffer = None 
        self._D_store_buffer = None 
        self._T_store_buffer = None
        
        self._F_store_buffer_averaging = None 
        self._D_store_buffer_averaging = None
        self._T_store_buffer_averaging = None
        
    ###########################################################################
    # Starts all processes, based on configuration given in constructor.
    ###########################################################################
    def start(self):
        
        
# =============================================================================
#         print ("WORKER SAMPLING TIME = ", self._sampling_time)
# =============================================================================
        
        # GET SAMPLES
        # ---------------------------------------------------------------------
        # single frequency measurement 
        if self._source == SourceType.serial:
           self._samples = Constants.argument_default_samples
        # calibration 
        elif self._source == SourceType.calibration:
           self._samples = Constants.calibration_default_samples
           self._readFREQ = Constants.calibration_readFREQ  
        # multi frequency measurement 
        elif self._source == SourceType.multiscan: 
            self._samples = Constants.argument_default_samples   
            
        # Setup/reset the internal buffers
        self.reset_buffers(self._samples)

        # VER 0.1.6 clear any stale peak-detection cancellation flag before a new run
        self._calibration_cancelled = False

        # Instantiates process
# =============================================================================
#         self._parser_process = ParserProcess(self._queue1, self._queue2, self._queue3, self._queue4, self._queue5, self._queue6, 
#                                              self._queue_F_multi, self._queue_D_multi, self._queue_A_multi, self._queue_P_multi)
# =============================================================================
        self._parser_process = ParserProcess(self._queue1, self._queue2, self._queue3, self._queue4, self._queue5, self._queueCurrentTec, self._queue6, 
                                             self._queue_F_multi, self._queue_D_multi, self._queue_A_multi, self._queue_P_multi,
                                             self._queue_message, self._queue_pid)
        
        
        # GET and SET SOURCE TYPE 
        # ---------------------------------------------------------------------
        # Checks the type of source
        # single frequency measurement 
        if self._source == SourceType.serial:
            self._acquisition_process = SerialProcess(self._parser_process)
        # calibration
        elif self._source == SourceType.calibration:
            self._acquisition_process = CalibrationProcess(self._parser_process)
        # multi frequency measurement 
        elif self._source == SourceType.multiscan:
            self._acquisition_process = MultiscanProcess(self._parser_process)
            
        # OPEN PROCESS 
        # ---------------------------------------------------------------------    
        if self._acquisition_process.open(port=self._port, speed=self._speed):
            
            # SINGLE 
            # -----------------------------------------------------------------
            if self._source == SourceType.serial:
               (self._overtone_name,
                self._overtone_value, 
                self._fStep, 
                self._readFREQ, 
                SG_window_size, 
                spline_points, 
                spline_factor) = self._acquisition_process.get_frequencies(self._samples)
               
# =============================================================================
#                
#                #print(TAG, "Quartz Crystal Sensor installed: {}".format(self._QCS_on))
#                print("")
#                print(TAG, "DATA MAIN INFORMATION")
#                print(TAG, "Selected frequency: {} - {}Hz".format(self._overtone_name,self._overtone_value))
#                print(TAG, "Frequency start: {}Hz".format(self._readFREQ[0]))
#                print(TAG, "Frequency stop:  {}Hz".format(self._readFREQ[-1]))
#                print(TAG, "Frequency range: {}Hz".format(self._readFREQ[-1]-self._readFREQ[0]))
#                print(TAG, "Number of samples: {}".format(self._samples-1))
#                print(TAG, "Sample rate: {}Hz".format(self._fStep))
#                print(TAG, "History buffer size: 180 min\n")
#                print(TAG, "MAIN PROCESSING INFORMATION")
#                print(TAG, "Method for baseline estimation and correction:")
#                print(TAG, "Least Squares Polynomial Fit (LSP)")
#                #print(TAG, "Degree of the fitting polynomial: 8")
#                print(TAG, "Savitzky-Golay Filtering")
#                print(TAG, "Order of the polynomial fit: {}".format(Constants.SG_order))
#                print(TAG, "Size of data window (in samples): {}".format(SG_window_size))
#                print(TAG, "Oversampling using spline interpolation")
#                print(TAG, "Spline points (in samples): {}".format(spline_points-1))
#                print(TAG, "Resolution after oversampling: {}Hz".format((self._readFREQ[-1]-self._readFREQ[0])/(spline_points-1)))
# =============================================================================
               
            # CALIBRATION
            elif self._source == SourceType.calibration:
# =============================================================================
#                print("")
#                print(TAG, "MAIN CALIBRATION INFORMATION")
#                print(TAG, "Calibration frequency start:  {}Hz".format(Constants.calibration_frequency_start))
#                print(TAG, "Calibration frequency stop:  {}Hz".format(Constants.calibration_frequency_stop))
#                print(TAG, "Frequency range: {}Hz".format(Constants.calibration_frequency_stop-Constants.calibration_frequency_start))
#                print(TAG, "Number of samples: {}".format(Constants.calibration_default_samples-1))
#                print(TAG, "Sample rate: {}Hz".format(Constants.calibration_fStep))
# =============================================================================

                # VER 0.1.6 just change peak detection not calibration !
                print("")
                print(TAG, "Peak Detection Parameters")
                print(TAG, "Peak Detection frequency start:  {}Hz".format(Constants.calibration_frequency_start))
                print(TAG, "Peak Detection frequency stop:  {}Hz".format(Constants.calibration_frequency_stop))
                print(TAG, "Frequency range: {}Hz".format(Constants.calibration_frequency_stop-Constants.calibration_frequency_start))
                print(TAG, "Number of samples: {}".format(Constants.calibration_default_samples-1))
                print(TAG, "Sample rate: {}Hz".format(Constants.calibration_fStep))
               
               
            # START MULTI SCAN FREQUENCY PROCESS 
            elif self._source == SourceType.multiscan: 
                # self._readFREQ = self._acquisition_process.get_readFREQ(self._samples)
                # get the number of total peaks in PeakFrequencies.txt
                data  = loadtxt(Constants.cvs_peakfrequencies_path)
                peaks_mag = data[:,0]
                self._number_of_peaks = len(peaks_mag) - 1
            
            # START PROCESSES ACQUISITION and PARSER 
            # -----------------------------------------------------------------
            self._acquisition_process.start()
            self._parser_process.start()
            
            # VER 0.1.2
            # format the log data file: one fresh timestamp per START press.
            # The format lives in Constants; a local copy of it here is how the
            # two drift apart without anything on screen saying so.
            self._csv_filename = strftime(Constants.csv_default_prefix, localtime())

            # VER 0.1.6 and one fresh elapsed-time origin with it. Measured
            # from START, not from the first datum: the warm-up is 3 sweeps in
            # development and 10 in production, and a readout frozen at 0 for
            # the first 15-20 s of a run looks broken rather than warming up.
            self._run_started = time()
            self._last_datalog_write = None

            return True
        
        else:
            print(TAG, 'Warning: port is not available')
            Log.i(TAG, "Warning: Port is not available")
            return False


    ###########################################################################
    # Stops all running processes
    ###########################################################################    
    def stop(self):
        
        # VER 0.1.2
        # consume all queues 
        self.consume_queue1()
        self.consume_queue2()
        self.consume_queue3()
        self.consume_queue4()
        # ⚠️ F and D BEFORE the temperature queue: the temperature message of an
        # overtone is posted after its F and D and is what triggers the datalog
        # row (store_data), so the row must find this overtone's values already
        # in the stores. Queue order is the only ordering there is between
        # separate multiprocessing queues.
        self.consume_queue_F_multi()
        self.consume_queue_D_multi()
        self.consume_queue5() 
        self.consume_queue6() 
        self.consume_queue_A_multi()
        self.consume_queue_P_multi()
        # the last lines the process wrote before it was told to stop
        self.consume_queue_message()
        self.consume_queue_pid()
        
        # VER 0.1.2
# =============================================================================
#         self._acquisition_process.stop()
#         self._parser_process.stop()
# =============================================================================

        # VER 0.1.2
        # worker processes are still running when you press stop button on main gui 
        # when stop is called, terminate the processes alive in the worker 

        if self._acquisition_process is not None and self._acquisition_process.is_alive():
            # Signal the process to stop (sets its _exit event).
            self._acquisition_process.stop()

            if self._source == SourceType.calibration:
                # VER 0.1.6 graceful shutdown for peak detection (ported from
                # openQCM Q-1 v3.0): the responsive sweep loop returns within
                # ~0.1 s of _exit being set, releasing the serial port cleanly.
                # Wait for it to exit on its own and only force terminate() as a
                # fallback, so a mid-sweep Stop does not hard-kill the process
                # and leave the serial port in a bad state.
                self._acquisition_process.join(3.0)
                if self._acquisition_process.is_alive():
                    print(TAG, "Peak detection process did not exit, forcing terminate...")
                    Log.w(TAG, "Peak detection process did not exit, forcing terminate...")
                    self._acquisition_process.terminate()
                    self._acquisition_process.join(2.0)
            else:
                # Measurement modes (serial / multiscan): terminate directly —
                # unchanged behaviour, their read loops are not exit-polled.
                # https://docs.python.org/3/library/multiprocessing.html#multiprocessing.Process.terminate
                self._acquisition_process.terminate()
                # wait for a while
                sleep(1)

        # TODO check if it is necessary to terminate parser
        self._parser_process.stop()
        
        print(TAG, 'Running processes stopped...')
        print(TAG, 'Processes finished')
        Log.i(TAG, "Running processes stopped...")
        Log.i(TAG, "Processes finished")
        
    
    # TODO DELETE TEMPERATURE FUNCTION 
    def get_Temperature_set_Worker(self, value):
         print ("SET TEMPERATURE WORKER")
         self._acquisition_process.get_Temperature_set_Serial(value)
        
    # TODO DELETE TEMPERATURE FUNCTION 
    def my_stop(self):
        self._acquisition_process.serial_close()
    
    # TODO DELETE TEMPERATURE FUNCTION 
    def serial_write(self, port, message):
        # self._acquisition_process.open(port)
        self._acquisition_process.write(port, message.encode())
                    
    ###########################################################################
    # Empties the internal queues, updating data to consumers
    ###########################################################################    
    def consume_queue1(self):
        # queue1 for serial data: amplitude
        while not self._queue1.empty():
            self._queue_data1(self._queue1.get(False))
    
    def consume_queue2(self):
        # queue2 for serial data: phase
        while not self._queue2.empty():
            self._queue_data2(self._queue2.get(False))

    # FREQUENCY 
    def consume_queue3(self):
        # queue3 for elaborated data: resonance frequency
        while not self._queue3.empty():
            self._queue_data3(self._queue3.get(False))
            
    def consume_queue4(self):
        # queue3 for elaborated data: Q-factor/Dissipation
        while not self._queue4.empty():
            self._queue_data4(self._queue4.get(False))    
           
    def consume_queue5(self):
        # queue3 for elaborated data: Temperature
        while not self._queue5.empty():
            self._queue_data5(self._queue5.get(False)) 
            
    # VER 0.1.6 consume TEC current date queue        
    def consume_queueCurrentTec(self): 
        # queue3 for elaborated data: current TEC
        while not self._queueCurrentTec.empty():
            self._queue_data_CurrentTec(self._queueCurrentTec.get(False))        
    
    def consume_queue6(self):
        # queue3 for elaborated data: errors
        while not self._queue6.empty():
            self._queue_data6(self._queue6.get(False))

    def consume_queue_pid(self):
        # the answer to a Read PID the acquisition process was asked to make
        while not self._queue_pid.empty():
            self._pid_reported = tuple(self._queue_pid.get(False))

    def pop_pid_reported(self):
        """The last answer, once; None until the process has answered."""
        reported, self._pid_reported = self._pid_reported, None
        return reported

    def request_pid_read(self):
        """Ask the running acquisition to read the PID between two sweeps."""
        parser = getattr(self, "_parser_process", None)
        if parser is None:
            return False
        parser.request_pid_read()
        return True

    def request_tec_reset(self):
        """Ask the running acquisition to reset the TEC error register
        (X0 / X1 / X0) between two sweeps, on the port it owns."""
        parser = getattr(self, "_parser_process", None)
        if parser is None:
            return False
        parser.request_tec_reset()
        return True

    def consume_queue_message(self):
        # text from the acquisition process, printed HERE, in the GUI process:
        # that is what puts it in the System Log tab and not only in the console
        while not self._queue_message.empty():
            text = self._queue_message.get(False)
            print(text)
            Log.i(TAG, text)
            
    def consume_queue_F_multi(self): 
        # consume the parser queue until is empty
        while not self._queue_F_multi.empty():
            # get the data from the parser queue and put it in the circular buffer
            self._queue_data_F_multi(self._queue_F_multi.get(False))
        
    def consume_queue_D_multi(self):   
        while not self._queue_D_multi.empty():
            self._queue_data_D_multi(self._queue_D_multi.get(False))
        
    def _queue_data_F_multi(self, data):
        # Add values
        self._store_signal_values(data[1])
        self._store_signal_values_time (data[0])
        
    def _store_signal_values(self, values):
        # detect how many data are present to plot
        size = len(values)
        # store the data in respective buffers
        for idx in range(size):
            self._F_multi_buffer[idx].append(values[idx])
            # store the current array of frequency data 
            self._F_store[idx] = values[idx]
       
    def get_F_values_buffer(self, idx=0):
        """
        Gets the complete buffer for a line data, depending on specified index.
        :param idx: Index of the line data to get.
        :type idx: int.
        :return: float list.
        """
        return self._F_multi_buffer[idx].get_all()
    
    def _store_signal_values_time (self, values): 
        size = len(values)
        for idx in range(size):
            # append current time values
            self._time_buffer[idx].append(values[idx])
            # store the current array of time data
            self._time_store[idx] = values[idx]
# =============================================================================
#             print("TIME ....")
#             print (self._time_buffer[0])
#             print (self._time_buffer[1])
#             print (self._time_buffer[2])
#             print (self._time_buffer[3])
#             print (self._time_buffer[4])
#             print("---------------------------")
# =============================================================================
            
    def get_time_values_buffer(self, idx = 0):
        # get all time buffer 
        return self._time_buffer[idx].get_all()
    
    def _queue_data_D_multi(self, data):
        # Add values
        self._store_signal_values_D(data[1])
        
    def _store_signal_values_D(self, values):
        # detect how many data are present to plot
        size = len(values)
        # store the data in respective buffers
        for idx in range(size):
            self._D_multi_buffer[idx].append(values[idx])
            # store the current array of dissipation  data 
            self._D_store[idx] = values[idx]
    
    def get_D_values_buffer(self, idx=0):
        """
        Gets the complete buffer for a line data, depending on specified index.
        :param idx: Index of the line data to get.
        :type idx: int.
        :return: float list.
        """
        return self._D_multi_buffer[idx].get_all()
    
    
    def consume_queue_A_multi(self):
        while not self._queue_A_multi.empty():
            self._queue_data_A_multi(self._queue_A_multi.get(False))

    # The phase sweep travels on its own queue. Until this existed the queue was
    # filled by MultiscanProcess on every sweep and drained by nobody, so it
    # grew without bound for the whole life of the process.
    def consume_queue_P_multi(self):
        while not self._queue_P_multi.empty():
            self._queue_data_P_multi(self._queue_P_multi.get(False))

    def _queue_data_A_multi(self, data):
        # Add values
        self._store_signal_values_A (data[1])
        self._store_signal_values_F_sweep (data[0])

    def _queue_data_P_multi(self, data):
        # data[0] is the same frequency axis the amplitude queue carries, so it
        # is not stored a second time
        self._store_signal_values_P (data[1])

    
    def _store_signal_values_A (self, values):
        # detect how many data are present 
        size = len(values)
        # store the data in respective buffers
        for idx in range(size):
            self._A_multi_buffer[idx] = values[idx]
    
    def _store_signal_values_P (self, values):
        # detect how many data are present 
        size = len(values)
        # store the data in respective buffers
        for idx in range(size):
            self._P_multi_buffer[idx] = values[idx]

    def _store_signal_values_F_sweep (self, values):
        # detect how many data are present 
        size = len(values)
        # store the data in respective buffers
        for idx in range(size):
            self._F_Sweep_multi_buffer[idx] = values[idx]
            
            
    def get_A_values_buffer(self, idx=0): 
        return self._A_multi_buffer[idx]

    def get_P_values_buffer(self, idx=0):
        return self._P_multi_buffer[idx]
        
    
    def get_F_Sweep_values_buffer(self, idx = 0):
        
        return self._F_Sweep_multi_buffer[idx]
        # print (self._F_Sweep_multi_buffer[idx])
       
       
    ###########################################################################
    # Adds data to internal buffers.
    ###########################################################################    
    def _queue_data1(self,data):
        #:param data: values to add for serial data: amplitude :type data: float.
        self._data1_buffer = data
    
    #####    
    def _queue_data2(self,data):
        #:param data: values to add for serial data phase :type data: float.
        self._data2_buffer = data
        # Additional function: exports calibration data in a file if export box is checked.
        '''
        self.store_data_calibration()
        '''
    
    # FREQUENCY 
    def _queue_data3(self,data):
        #:param data: values to add for Resonance frequency :type data: float.
        self._t1_store = data[0] # time (unused)
        self._d1_store = data[1] # data
        self._t1_buffer.append(data[0])
        self._d1_buffer.append(data[1])
        
    # DISSIPATION 
    def _queue_data4(self,data):
        # Additional function: exports processed data in a file if export box is checked.
        #:param data: values to add for Q-factor/dissipation :type data: float.
        self._t2_store = data[0] # time (unused)
        self._d2_store = data[1] # data
        self._t2_buffer.append(data[0])
        self._d2_buffer.append(data[1])
    
    # TEMPERATURE
    def _queue_data5(self,data):
        # Additional function: exports processed data in a file if export box is checked.
        #:param data: values to add for temperature :type data: float.
        # VER 0.1.6 a -1 on the time field is the peak-detection cancellation
        # sentinel emitted by CalibrationProcess when the user presses Stop.
        if data[0] == -1:
            self._calibration_cancelled = True
        self._t3_store = data[0] # time (unused)
        self._d3_store = data[1] # data
        # multiscan since 2026-09-17: fields 2-3 are the overtone this message
        # belongs to and the end-of-cycle flag (Multiscan.elaborate_multi). A
        # two-element message (Serial, Calibration, an older process) flags no
        # cycle end and therefore writes no multiscan row.
        self._cycle_overtone = int(data[2]) if len(data) > 2 else self._overtone_number
        self._cycle_end = bool(data[3]) if len(data) > 3 else False
        # fields 4-5: the cycle's own F and D, so a row drained behind a backlog
        # carries its cycle's values; without them the stores are used
        self._cycle_F = list(data[4]) if len(data) > 5 else None
        self._cycle_D = list(data[5]) if len(data) > 5 else None
        
        
        
        self._t3_buffer.append(data[0])
        self._d3_buffer.append(data[1])
        
        # TODO datalog the time is now 
        # for storing relative time 
        if  self._flag and ~np.isnan(self._d3_store):
            # SINGLE 
            if self._source == SourceType.serial:
                self._timestart = time()
                
            # MULTI 
            elif self._source == SourceType.multiscan:
                epoch= datetime.datetime(1970, 1, 1, 0, 0) #offset-naive datetime
                ts_mult=1e6
                self._timestart = (int((datetime.datetime.now() - epoch).total_seconds()*ts_mult))
                
                # VER 0.1.3
                self.time_pre =  self._timestart
            
            self._flag = False
            
            # print("DATALOG TIME START = ")
            # print (self._timestart )
        
        # Data Storage in csv and/or txt file 
        self.store_data()
        
    # VER 0.1.6 TEC CURRENT queue data define  
    def _queue_data_CurrentTec(self, data):
        # append new TEC current data to the ring buffer 
        self._data_current_tec = data[1]
        self._data_current_tec_buffer.append(data[1])
    
        #####
    def _queue_data6(self,data):
        #:param data: values to add for serial error :type data: float.
        self._ser_error1 = data[0]
        self._ser_error2 = data[1]
        self._control_k = data[2]
        self._ser_err_usb = data[3]
        self._overtone_number = data[4]
        
        # VER 0.2 
        # get TEC status 
        self._TEC_status = data[5]
        # the error register rides along since 2026-09-10 (Multiscan, Serial;
        # Calibration sends no such field)
        if len(data) > 6 and data[6] is not None:
            self._TEC_error_register = data[6]
        
    ###########################################################################
    # Gets data buffers for plot (Amplitude,Phase,Frequency and Dissipation) 
    ###########################################################################        
    def get_value1_buffer(self):
        #:return: float list.
        return self._data1_buffer
    
    #####
    def get_value2_buffer(self):
        #:return: float list.
        return self._data2_buffer

    # Frequency: get all frequency buffer 
    def get_d1_buffer(self):
        #:return: float list.
        return self._d1_buffer.get_all()
        
    ##### Gets time buffers
    def get_t1_buffer(self):
        #:return: float list.
        return self._t1_buffer.get_all()
    
    #####
    def get_d2_buffer(self):
        #:return: float list.
        return self._d2_buffer.get_all()
    
    ##### Gets time buffers
    def get_t2_buffer(self):
        #:return: float list.
        return self._t2_buffer.get_all()
    
    #####
    def get_d3_buffer(self):
        #:return: float list.
        return self._d3_buffer.get_all()
    
    # VER 0.1.6 TEC current get all value of ring buffer 
    def get_data_current_tec_buffer(self):
        return self._data_current_tec_buffer.get_all()
    
    ##### Gets time buffers
    def get_t3_buffer(self):
        #:return: float list.
        return self._t3_buffer.get_all()
    
    ##### Gets serial error
    def get_ser_error(self):
        #:return: float list.
        return self._ser_error1, self._ser_error2, self._control_k, self._ser_err_usb, self._overtone_number
    
    # VER 0.1.3
    # get TEC status and pass the value to the main 
    def get_TEC_status(self): 
        return self._TEC_status

    def get_TEC_error_register(self):
        return self._TEC_error_register
    

    ###########################################################################
    # Exports data in csv and/or txt file if export box is checked
    ###########################################################################
    def store_data(self): 
        # Checks the type of source
        
        # SINGLE
        # ---------------------------------------------------------------------
        if self._source == SourceType.serial:
          # Checks the state of the export box
          #if self._export:
          
          # Storing calculated data with the format: timestamp,resonance frequency,dissipation
          
          # VER 0.1.2 
          # init the new datalog file in single mode: <ts>_F<n>.csv
          filenameCSV = "{}_{}".format(self._csv_filename, self._overtone_name)
          
          # VER 0.1.6 the sampling interval, which this branch never computed.
          # ⚠️ Only the multiscan branch below touched time_elapsed, so the
          # readout -- the status bar's "S:" -- sat at 0 for the whole of every
          # single-frequency run, and looked like a broken field rather than an
          # unimplemented one. In this mode a row is written on every call (the
          # time-controlled sampling of multiscan is still a TODO here), so the
          # interval is just the time since the previous write. The first write
          # has no predecessor and leaves the value alone.
          _now = time()
          if self._last_datalog_write is not None:
              self.time_elapsed = _now - self._last_datalog_write
          self._last_datalog_write = _now

          FileStorage.CSVsave(filenameCSV, Constants.csv_export_path, time() - self._timestart, self._d3_store, self._d1_store, self._d2_store)

          if self._export:   
              # Storing acquired sweeps
              filename = "{}_{}_{}".format(Constants.csv_sweeps_filename, self._overtone_name,self._count)
              #filename = "{}_{}".format(Constants.csv_sweeps_filename,self._count)
              # the run's own timestamp, not the one the module was imported at
              sweep_export_path = "{}{}{}".format(Constants.csv_export_path,
                                                  Constants.slash, self._csv_filename)
              path = "{}_{}".format(sweep_export_path, self._overtone_name) 
              #FileStorage.CSV_sweeps_save(filename, path, self._readFREQ, self._data1_buffer, self._data2_buffer)
              FileStorage.TXT_sweeps_save(filename, path, self._readFREQ, self._data1_buffer, self._data2_buffer)
          self._count+=1
           
        # MULTI
        # ---------------------------------------------------------------------
        elif  self._source == SourceType.multiscan:
           
            # LOG MULTI DATA FILE 
            
            # VER 0.1.2
            # init the new datalog file in multi mode: <ts>_multi.csv
            filenameCSV = "{}_{}".format(self._csv_filename, "multi")

            # TODO change the way the file is logged , there are duplicate in the data file 
            # FileStorage.CSVsave_Multi(filenameCSV, Constants.csv_export_path, time() - self._timestart, self._d3_store, self._F_store, self._D_store)
            
            # LOG data file only if current overtone number is equal to total numer of peaks
            #  TODO 
            # if (self._overtone_number == self._number_of_peaks):
            index_store = 0
            _millisec = 1e6
            
            # VER 0.1.4
            SAMPLING_TIME_INTERVAL = self._sampling_time
            
            # VER 0.1.2
            # [SOLVED] Bug: first line in datalog file missing frequency and dissipation data array
            
            # VER 0.1.4
# =============================================================================
#             if (self._overtone_number == index_store) and ((self._time_store[index_store] - self._timestart)/_millisec > 0): 
# =============================================================================
            # VER 0.1.4 check if time elapsed is greater than zero 
            if  ( (self._time_store[index_store] - self._timestart)/_millisec > 0 ):
                
                # get current time 
                epoch= datetime.datetime(1970, 1, 1, 0, 0) #offset-naive datetime
                ts_mult=1e6
                time_current = (int((datetime.datetime.now() - epoch).total_seconds()*ts_mult))
                
                # ⚠️ Not int(): the GUI formats this with "{0:.1f}", which is
                # only meaningful for a float, and truncating a 1.8 s interval
                # to 1 misreports it by 45%. Display-only value -- the datalog's
                # own relative-time column is computed separately below.
                self.time_elapsed = (time_current - self.time_pre)/_millisec
                
                # VER 0.1.4
                # default / maximum sampling rate 
                if (SAMPLING_TIME_INTERVAL == -1): 
                    # one row per cycle, on the temperature message that closed
                    # it. The old gate compared the STATUS queue's overtone
                    # number, consumed after this queue, so every temperature
                    # message pending in one drain was judged against a stale
                    # value: 0, 1 or 5 identical rows per cycle (measured
                    # 2026-09-17: 96 duplicate rows in 486, 19 s gaps).
                    if self._cycle_end:
                        FileStorage.CSVsave_Multi(filenameCSV, Constants.csv_export_path, 
                                                  int((time_current - self._timestart))/_millisec, 
                                                  self._d3_store,
                                                  self._F_store if self._cycle_F is None else self._cycle_F,
                                                  self._D_store if self._cycle_D is None else self._cycle_D)
                        # VER 0.1.4 store the current time for the next loop 
                        self.time_pre = time_current
                
                # VER 0.1.4
                # time controlled sampling time 
                else: 
# =============================================================================
#                     print ((time_current - self.time_pre)/_millisec)
# =============================================================================
                    
# =============================================================================
#                     print ("CURRENT VALUE OVERTONE NUMBER = ", self._overtone_number)    
# =============================================================================


                    # VER 0.1.4 create a circular buffer of size corresponding to the length of the datalog sampling time
                    # init the new data in circular buffer 
                    # the overtone THIS message belongs to, not the status queue's
                    self._F_store_buffer[self._cycle_overtone].append(self._F_store[self._cycle_overtone])
                    self._D_store_buffer[self._cycle_overtone].append(self._D_store[self._cycle_overtone])
                    self._T_store_buffer[self._cycle_overtone].append(self._d3_store)
                    
                    # averaging 
                    for idx in range(len(Constants.overtone_dummy)):
                        self._F_store_buffer_averaging[idx] = np.average( self._F_store_buffer[idx].get_all())
                        self._D_store_buffer_averaging[idx] = np.average( self._D_store_buffer[idx].get_all() )
                        self._T_store_buffer_averaging[idx] = np.average( self._T_store_buffer[idx].get_all() )
                    
                    
# =============================================================================
#                     print (self._F_store_buffer[0].get_all())
# =============================================================================
                    
                    # VER 0.1.4
                    # check the sampling time 
                    # a whole cycle in every row here too: the interval is checked
                    # only when a cycle has just closed
                    if self._cycle_end and ( ((time_current - self.time_pre)/_millisec) >  SAMPLING_TIME_INTERVAL ):
                        FileStorage.CSVsave_Multi(filenameCSV, Constants.csv_export_path, 
                                                  int((time_current - self._timestart)/_millisec), 
                                                  self._d3_store, self._F_store_buffer_averaging, self._D_store_buffer_averaging)
                    
                        # VER 0.1.4 store the current time for the next loop 
                        self.time_pre = time_current

# =============================================================================
#                 FileStorage.CSVsave_Multi(filenameCSV, Constants.csv_export_path, 
#                                           (self._time_store[index_store] - self._timestart)/_millisec, 
#                                           self._d3_store, self._F_store, self._D_store)
# =============================================================================
                    # this lines code works, but introduced random relative time error 
# =============================================================================
#                 FileStorage.CSVsave_Multi(filenameCSV, Constants.csv_export_path, 
#                                           time() - self._timestart, 
#                                           self._d3_store, self._F_store, self._D_store)
# =============================================================================

                # ---------------------------------------------------------------------  
                # TODO SAVE SINGLE SWEEP FILE   
                # elif self._source == SourceType.multiscan: 
                    # print("__TODO__ multiscan save file")
                # ---------------------------------------------------------------------
                
                # DEV RAWDATA save single raw date here should work also here 
                RAWDATA = False
                if (RAWDATA):
                    print (" save single sweep raw data here: TODO" )
                    # the code line blow works 
                    print (self.get_A_values_buffer(0))
    
    
    
    # VER 0.1.4
    def get_time_elapsed (self):
        # ⚠️ This is the SAMPLING INTERVAL -- seconds between two datalog
        # writes -- and not how long the run has been going. The name is
        # historical; the status bar's "S:" is the honest label for it. For the
        # run's elapsed time use get_run_elapsed() below.
        # print ("HELLO WORLD")
        return (self.time_elapsed)

    # VER 0.1.6
    def get_run_elapsed(self):
        """Seconds since START, or 0.0 before a run has begun.

        Kept apart from get_time_elapsed() on purpose. The sidebar says "Time
        elapsed" and was showing the sampling interval, which in single mode is
        never computed at all -- so that readout sat at 0 for the whole run.
        """
        if self._run_started is None:
            return 0.0
        return time() - self._run_started
    
    
    ###########################################################################
    # Returns the datalog CSV filename of the current acquisition
    ###########################################################################
    def get_csv_filename(self):
        # Phase 3d: mirrors the names composed in the storing loop below
        # (serial: "<ts>_F<n>", multiscan: "<ts>_multi"); calibration
        # writes no datalog, so it reports an empty string.
        if not self._csv_filename:
            return ""
        if self._source == SourceType.serial and self._overtone_name is not None:
            return "{}_{}.{}".format(self._csv_filename, self._overtone_name,
                                     Constants.csv_extension)
        if self._source == SourceType.multiscan:
            return "{}_{}.{}".format(self._csv_filename, "multi",
                                     Constants.csv_extension)
        return ""

    ###########################################################################
    # Checks if processes are running
    ###########################################################################
    def is_running(self):
        return self._acquisition_process is not None and self._acquisition_process.is_alive()

    ###########################################################################
    # Release what this worker holds: the two processes, the queues' pipes and
    # semaphores, and the process objects. ~100 file descriptors per worker
    # (lsof: 65 PSXSEM + 35 PIPE). Called by the GUI before a new worker is
    # built, so that two never coexist. Idempotent.
    #
    # ⚠️ The processes must be JOINED first. stop() signals the parser and
    # terminates the acquisition without waiting; until they are seen to have
    # exited, multiprocessing keeps their Process objects in its children list,
    # and those hold the parser, which holds every queue, which holds the
    # semaphores. Measured (2026-09-10): closing the queues alone left 75 of
    # 93 descriptors and one child kept; join + close + active_children() +
    # gc.collect() left 6, the process's base.
    ###########################################################################
    def close(self, join_timeout=3.0):
        import gc
        import multiprocessing
        from multiprocessing.queues import Queue as _MPQueue

        for proc in (self._acquisition_process, self._parser_process):
            if proc is None:
                continue
            try:
                if proc.is_alive():
                    proc.join(join_timeout)
                    if proc.is_alive():
                        proc.terminate()
                        proc.join(1.0)
            except (OSError, ValueError, AssertionError):
                pass

        names = [name for name, value in vars(self).items()
                 if isinstance(value, _MPQueue)]
        for name in names:
            q = getattr(self, name)
            try:
                # never wait for a feeder thread nobody is reading from
                q.cancel_join_thread()
                q.close()
            except (OSError, ValueError):
                pass
            setattr(self, name, None)
        # the process objects hold the parser, and the parser the queues too
        self._acquisition_process = None
        self._parser_process = None
        # forget the exited children and collect what only they still held
        try:
            multiprocessing.active_children()
        except Exception:
            pass
        gc.collect()
        return len(names)

    ###########################################################################
    # Returns True if the running peak detection was cancelled by the user.
    ###########################################################################
    def is_calibration_cancelled(self):
        # VER 0.1.6 latched from the -1 sentinel in _queue_data5; the GUI polls
        # this in the calibration branch of _update_plot to tear down cleanly.
        return self._calibration_cancelled


    ###########################################################################
    # Gets the available ports for specified source
    ###########################################################################
    @staticmethod
    def get_source_ports(source):
        
        """
        :param source: Source to get available ports :type source: SourceType.
        :return: List of available ports :rtype: str list.
        """
        
        # TODO what port ??? type of measurement 
        
        # SINGLE
        if source == SourceType.serial:
            print(TAG,'Port connected:',SerialProcess.get_ports())
            return SerialProcess.get_ports()
        # CALIBRATION
        elif source == SourceType.calibration:
            print(TAG,'Port connected:',CalibrationProcess.get_ports())
            return CalibrationProcess.get_ports()
        # MULTI 
        elif source == SourceType.multiscan:
            # TODO check get multiscan process serial port connected  
            # print (" WORKER get type of meas ")
            print(TAG,'Port connected:',MultiscanProcess.get_ports())
            return MultiscanProcess.get_ports()
        else:
            print(TAG,'Warning: unknown source selected')
            Log.w(TAG,"Unknown source selected")
            return None
        
        
    ###########################################################################
    # Gets the available speeds for specified source
    ###########################################################################
    @staticmethod
    def get_source_speeds(source):
        
        """
        :param source: Source to get available speeds :type source: SourceType.
        :return: List of available speeds :rtype: str list.
        """
        if source == SourceType.serial:
            return SerialProcess.get_speeds()
        
        elif source == SourceType.calibration:
            return CalibrationProcess.get_speeds()
        
        # multi 
        elif source == SourceType.multiscan:
            return MultiscanProcess.get_speeds()
        else:
            print(TAG,'Unknown source selected')
            Log.w(TAG, "Unknown source selected")
            return None
        
    
    ###########################################################################
    # Setup/Clear the internal buffers
    ###########################################################################
    def reset_buffers(self, samples):
        #:param samples: Number of samples for the buffers :type samples: int.
        
        # Initialises data buffers
        self._data1_buffer = np.zeros(samples) # amplitude
        self._data2_buffer = np.zeros(samples) # phase
        #self._d1_buffer = []  # Resonance frequency 
        #self._d2_buffer = []  # Dissipation
        #self._d3_buffer = []  # temperature
        #self._t1_buffer = []  # time (Resonance frequency)
        #self._t2_buffer = []  # time (Dissipation)
        #self._t3_buffer = []  # time (temperature)

        # Initialises supporting variables
        self._d1_store = 0
        self._d2_store = 0
        self._d3_store = 0
        
        # VER 0.1.6 init current value 
        self._data_current_tec = 0
        
        self._t1_store = 0
        self._t2_store = 0
        self._t3_store = 0
        self._ser_error1 = 0
        self._ser_error2 = 0
        self._ser_err_usb= 0
        #self._control_k = 0
        
        self._d1_buffer = RingBuffer(Constants.ring_buffer_samples)  # Resonance frequency 
        self._d2_buffer = RingBuffer(Constants.ring_buffer_samples)  # Dissipation
        self._d3_buffer = RingBuffer(Constants.ring_buffer_samples)  # temperature
        
        # VER 0.1.6 init TEC current ring buffer
        self._data_current_tec_buffer = RingBuffer(Constants.ring_buffer_samples) # current TEC 
        
        self._t1_buffer = RingBuffer(Constants.ring_buffer_samples)  # time (Resonance frequency)
        self._t2_buffer = RingBuffer(Constants.ring_buffer_samples)  # time (Dissipation)
        self._t3_buffer = RingBuffer(Constants.ring_buffer_samples)  # time (temperature)
        #print(TAG,'Buffers cleared')
        #Log.i(TAG, "Buffers cleared") 
        
        # init frequency and dissipation array of ring buffer 
        self._F_multi_buffer = []
        self._D_multi_buffer = []
        self._time_buffer = []
        
        self._A_multi_buffer = []
        self._P_multi_buffer = []
        self._F_Sweep_multi_buffer = []
        
        peaks = self._load_frequencies_file()
        peaks_number = len(peaks)
        
        # TODO IMPORTANT chenge the ninitialization of list of ring buffer 
        # append ring buffer
        for tmp in Constants.overtone_dummy:
            self._F_multi_buffer.append(RingBuffer(Constants.ring_buffer_samples))
            self._D_multi_buffer.append(RingBuffer(Constants.ring_buffer_samples))
            self._time_buffer.append(RingBuffer(Constants.ring_buffer_samples))
             
# =============================================================================
#         for nn in Constants.overtone_dummy:
#             self._A_multi_buffer[nn] = self._zerolistmaker(Constants.SAMPLES)
#             self._F_Sweep_multi_buffer[nn] = self._zerolistmaker(Constants.SAMPLES)
# =============================================================================

        self._A_multi_buffer = self._zerolistmaker(len(Constants.overtone_dummy))
        self._P_multi_buffer = self._zerolistmaker(len(Constants.overtone_dummy))
        self._F_Sweep_multi_buffer = self._zerolistmaker(len(Constants.overtone_dummy))
        
        # INIT self._F_store and self._D_store list 
        # TODO IMPORTANT self._F_store and self._D_store same legth of self._F_multi_buffer and self._D_multi_buffer
        self._F_store = self._zerolistmaker(len(Constants.overtone_dummy))
        self._D_store = self._zerolistmaker(len(Constants.overtone_dummy))
        self._time_store = self._zerolistmaker(len(Constants.overtone_dummy))
        # self._time_buffer = self._zerolistmaker(len(Constants.overtone_dummy))
        
        # init a ring buffer of corresponding size 
        SAMPLING_TIME_DEFAULT = 7
        self.ring_buffer_len =  int(self._sampling_time/SAMPLING_TIME_DEFAULT)
        
        # VER 0.1.4
        # init the list of storedata averaging 
        self._F_store_buffer_averaging = self._zerolistmaker(len(Constants.overtone_dummy)) 
        self._D_store_buffer_averaging = self._zerolistmaker(len(Constants.overtone_dummy))
        self._T_store_buffer_averaging = self._zerolistmaker(len(Constants.overtone_dummy))
        
        # init frequency dissipation and temperature array of ring buffer 
        self._F_store_buffer = [] 
        self._D_store_buffer = [] 
        self._T_store_buffer = []
        for tmp in Constants.overtone_dummy:
            self._F_store_buffer.append(RingBuffer(self.ring_buffer_len))
            self._D_store_buffer.append(RingBuffer(self.ring_buffer_len))
            self._T_store_buffer.append(RingBuffer(self.ring_buffer_len))

    ############################################################################
    # Gets frequency range
    ############################################################################
    
    def get_frequency_range(self):
        
        """
        :param samples: Number of samples for the buffers :type samples: int.
        :return: overtone :type overtone: float.
        :return: frequency range :type readFREQ: float list.
        """
        if self._source == SourceType.serial:
# =============================================================================
#             return self._readFREQ
# =============================================================================
            # VER 0.1.6 TODO return current frequency range and pass to main 
            freq_range_RT = self._acquisition_process.get_freq_range_RT()
            return freq_range_RT
            
        
        elif self._source == SourceType.multiscan:
            return self._readFREQ
    
    def get_frequency_range_multi(self, samples, overtone):
        if self._source == SourceType.multiscan:
            readFREQ_out = self._acquisition_process.get_readFREQ(samples, overtone)
        return readFREQ_out
    
    ############################################################################
    # Gets overtones name, value and frequency step
    ############################################################################
    
    def get_overtone(self):
        
        """
        :param samples: Number of samples for the buffers :type samples: int.
        :return: overtone :type overtone: float.
        :return: frequency range :type readFREQ: float list.
        """
        return self._overtone_name,self._overtone_value, self._fStep
    
    def _load_frequencies_file(self):
            data  = loadtxt(Constants.cvs_peakfrequencies_path)
            peaks_mag = data[:,0]
            #peaks_phase = data[:,1] #unused at the moment
            return peaks_mag
        
    def _zerolistmaker(self, n):
        listofzeros = [0] * n
        return listofzeros
    
