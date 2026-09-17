import multiprocessing
from openQCM.core.ringBuffer import RingBuffer
from openQCM.core.constants import Constants
from openQCM.core import resonance
from openQCM.common.fileStorage import FileStorage
from openQCM.common import sweepDump as SweepDump
from openQCM.common.pidQuery import read_pid
from openQCM.common.tecReset import reset_sequence
from openQCM.common.tecStatus import decode_error_register, report_error_changes
from openQCM.common.logger import Logger as Log
from openQCM.common.switcher import Overtone_Switcher_5MHz, Overtone_Switcher_10MHz
from time import time
import serial
from serial.tools import list_ports
import numpy as np
from numpy import loadtxt
from openQCM.core.averaging import robust_mean

from progressbar import Bar, Percentage, ProgressBar, RotatingMarker,Timer

from openQCM.util.ReadLine import ReadLine as rl

from time import sleep

from numpy import loadtxt

# DEV RAWDATA
from openQCM.common.architecture import Architecture,OSType

TAG = ""#"[Multiscan]"


class MultiscanProcess(multiprocessing.Process):

    # BASELINE CORRECTION
    def baseline_correction(self,x,y,poly_order):
        
        # Estimate Baseline with Least Squares Polynomial Fit (LSP)
        coeffs = np.polyfit(x,y,poly_order)
        # Evaluate a polynomial at specific values
        poly_fitted = np.polyval(coeffs,x) 
        return poly_fitted,coeffs    

    # BASELINE COEFFICIENTS   
    def baseline_coeffs(self):
        
        # initializations
        self.polyfitted_all = None
        self.coeffs_all = None
        self.polyfitted_all_phase = None
        self.coeffs_all_phase = None
        
        # loads Calibration (baseline correction) from file
        (self.freq_all,self.mag_all,self.phase_all) = self.load_calibration_file()
        
        # Baseline correction: input signal Amplitude (sweep all frequencies)
        (self.polyfitted_all,self.coeffs_all)=self.baseline_correction(self.freq_all,self.mag_all,Constants.BASELINE_POLY_ORDER)
        self.mag_beseline_corrected_all= self.mag_all-self.polyfitted_all
        
        # Baseline correction: input signal Phase (sweep all frequencies)
        (self.polyfitted_all_phase,self.coeffs_all_phase)=self.baseline_correction(self.freq_all,self.phase_all,Constants.BASELINE_POLY_ORDER)
        self.phase_beseline_corrected_all= self.phase_all-self.polyfitted_all_phase 
        return self.coeffs_all


    
    # ELABORATE SIGNAL 
    # -------------------------------------------------------------------------
    # TODO elaborate multi signal     
    def elaborate_multi(self, k, overtone_number, coeffs_all, readFREQ, samples, 
                  Xm, Xp, temperature, SG_window_size, Spline_points, Spline_factor, timestamp):
        
        # Number of spline points
        points = Spline_points
        # sweep counter
        self._k= k
        # current overtones number 
        self._overtone_number = overtone_number
        # evaluated polynomial coefficients
        self._coeffs_all = coeffs_all
        # frequency range, samples number
        self._readFREQ = readFREQ
        self._samples = samples
        # support vectors
        self._Xm = Xm
        self._Xp = Xp
        self._filtered_mag = np.zeros(samples)
        # save current data 
        mag   = self._Xm
        phase = self._Xp 

        # Initializations of support vectors for later storage
        self._Xm = np.linspace(0,0,self._samples)
        self._Xp = np.linspace(0,0,self._samples)
        
        # Evaluate a polynomial at specific values based on the coefficients and frequency range
        self._polyfitted = np.polyval(self._coeffs_all, self._readFREQ)
        
        # BASELINE CORRECTION ROI (raw data)
        mag_beseline_corrected = mag-self._polyfitted
        
        # FILTERING - Savitzky-Golay
        filtered_mag = resonance.savitzky_golay(mag_beseline_corrected, window_size = SG_window_size, order = Constants.SG_order)

        # peak, index e frequency of max detection baseline corrected (filtering optional)
        #self._vector_max_baseline_corrected.append(max(mag_beseline_corrected))   #Z axis (max)
        #self._index_max_baseline_corrected.append(np.argmax(mag_beseline_corrected, axis=0)) # X axis (max position)
        #h=self._index_max_baseline_corrected.append(np.argmax(mag_beseline_corrected, axis=0))
        #self._freq_max_baseline_corrected.append(readFREQ[int(h)])

        # FITTING/INTERPOLATING - SPLINE
        freq_range, mag_result_fit = resonance.spline_fit(self._readFREQ, filtered_mag, Spline_factor, points)

        # PARAMETERS FINDER
        # VER 0.1.4 chenge the bandwith threshold value to the constant value THRESHOLD_DB = 0.3
        # The band walk now lives in core/resonance.py, so the viewers can draw
        # exactly what is measured here instead of re-deriving it.
        band = resonance.find_peak_and_band(freq_range, mag_result_fit, Constants.THRESHOLD_DB)
        index_peak_fit = band.peak_index
        frequency_resonance = band.peak_frequency
        # Qfac has been an alias for the bandwidth since VER 0.1.4; the
        # dissipation below is the bandwidth in MHz, not the inverse of a Q.
        Qfac_fit = band.bandwidth

        # The two flags are sticky: they are cleared only once run() has pushed
        # them to parser6, so they report every overtone of the current cycle.
        if band.err_left:
            print(TAG, 'WARNING: Left value not found')
            self._err1 = 1
        if band.err_right:
            print(TAG, 'WARNING: Right value not found')
            self._err2 = 1

        # self._my_list_f[overtone_number].append( freq_range[int(index_peak_fit)] )
        # VER 0.1.4
        # change the dissipation calculation as the inverse of the bandwidth defined above in parameter finder
        self._my_list_f[overtone_number].append( frequency_resonance )
        self._my_list_d[overtone_number].append( (Qfac_fit/1000000) )
        
        #self._temperature_buffer.append(temperature)
        self._temperature_buffer_0.append(temperature)
       
        if self._k >= self._environment:
           # FREQUENCY
           # VER 0.1.6 robust average of the raw circular buffer. Replaces
           # the Savitzky-Golay + np.average: SG(window=3, order=1) was a
           # linear 3-point moving average with NO outlier rejection, so a
           # single bad sweep leaked almost entirely into the logged value
           # (and was even amplified at the buffer edges by the reflective
           # padding). robust_mean drops the lowest/highest samples before
           # averaging, without the staircase artifact of a plain median.
           # It is core/averaging.py and not scipy's trim_mean because that one
           # cuts int(proportion*N) per tail, which is ZERO for any N below ten:
           # the rejection held only while Constants.environment was exactly 10,
           # and any resizing of the buffer switched it off in silence.
           self._freq_range_mean [overtone_number] = robust_mean(
               self._my_list_f[overtone_number].get_all(), Constants.trim_mean_proportiontocut)

           # DISSIPATION (same robust trimmed-mean; resolves the former
           # "TODO insert a median" that used to sit on this averaging line)
           self._diss_mean [overtone_number] = robust_mean(
               self._my_list_d[overtone_number].get_all(), Constants.trim_mean_proportiontocut)

           # TEMPERATURE
           if overtone_number == 0:
               self._temperature_mean = robust_mean(
                   self._temperature_buffer_0.get_all(), Constants.trim_mean_proportiontocut)
               
        
        #  VER 0.2 BETA 
        # set the current value of resonance frequecy at specific overtone 
        if self._k <= self._environment:
            # current value is raw
            self.freq_res_current_array [overtone_number] = freq_range[int(index_peak_fit)]
        else:
            # current value as average 
            self.freq_res_current_array [overtone_number] = int( self._freq_range_mean [overtone_number])
        
# =============================================================================
#         else:
#              # TODO necessary to avoid exception when calling elaborate_multi() when k < Constants.environment
#              self._freq_range_mean [overtone_number] = 0
#              self._diss_mean [overtone_number] = 0
#              self._temperature_mean = 0
# =============================================================================
             
        # TIME EPOCH TODO 
        # ---------------------------------------------------------------------
        import datetime
        epoch = datetime.datetime(1970, 1, 1, 0, 0) #offset-naive datetime
        ts_mult = 1e6
        
        # TODO the Time is now and it is hard 
        if overtone_number == 0:
            self._my_time = (int((datetime.datetime.now() - epoch).total_seconds()*ts_mult)) #datetime.datetime.utcnow()
        # ---------------------------------------------------------------------
        
        # time array for each harmonic
        self._my_time_array[overtone_number] = (int((datetime.datetime.now() - epoch).total_seconds()*ts_mult))
        
        # TODO ADD BUFFER MEASUREMENT DATA TO THE PARSER QUEUE
        # ------------------------------------------------------
        # AMPLITUDE 
        self._parser1.add1(filtered_mag) 
        # PHASE 
        self._parser2.add2(phase)        
        
       
        # TODO just dummy 
        # Adds "fake" frequency, dissipation and temperature meaan to parser queues
        self._parser3.add3([self._my_time,0]) 
        self._parser4.add4([self._my_time,0]) 
        
        # VER 0.1.6 add TEC current value to the parser queue
        self._parser_current_tec.addCurrentTec([self._my_time, self._current_tec])
        
        # add multi overtone average date to parser queue
# =============================================================================
#         self._parser_F_multi.add_F_multi( [ self._my_time, self._freq_range_mean] )
#         self._parser_D_multi.add_D_multi( [ self._my_time, self._diss_mean] )
# =============================================================================
        
        # add multi overtone frequency - dissipation and correpsonding time array to the parser queues
        self._parser_F_multi.add_F_multi( [ self._my_time_array, self._freq_range_mean] )
        self._parser_D_multi.add_D_multi( [ self._my_time_array, self._diss_mean] )

        # The temperature message is also the DATALOG CLOCK: it carries which
        # overtone this is and whether it is the last of the cycle, and it is
        # posted AFTER the F and D messages of the same overtone so that, when
        # the worker reads the end-of-cycle flag, this overtone's values are
        # already in its stores (the worker drains F and D before this queue).
        # Before 2026-09-17 the worker decided when to write a row from the
        # overtone number of the STATUS queue, consumed after this one: a stale
        # value, so a drain wrote 0, 1 or up to 5 identical rows per cycle
        # (96 duplicates in 486 rows on 2026-09-11, and 19 s gaps).
        self._parser5.add5([self._my_time, self._temperature_mean, overtone_number,
                            overtone_number == self._overtones_in_cycle - 1])
        
        # TODO single sweeep data log 
       
    def elaborate_ampli_phase_multi(self, overtone_index, poly_coeff, freq_sweep, amp_sweep, phase_sweep):
# =============================================================================
#         # init variable TODO filtering - Savitzky-Golay
#         amp_filtered = np.zeros(Constants.SAMPLES) # unused 
#         
#         freq_np = np.linspace(0,0,self._samples)
#         amp_np = np.linspace(0,0,self._samples)
#         phase_np = np.linspace(0,0,self._samples)
# =============================================================================
        
        # calculate polynomial at frequency sweep points
        amp_baseline = np.polyval(poly_coeff, freq_sweep)
        
        self._my_list_amp [overtone_index] = (amp_sweep - amp_baseline).tolist()
        
        self._my_list_phase [overtone_index] = phase_sweep.tolist()
        self._my_list_freq [overtone_index ] = freq_sweep.tolist()
     
        # add to new parser 
        self._parser_A_multi.add_A_multi([ self._my_list_freq, self._my_list_amp ])
        self._parser_P_multi.add_P_multi([ self._my_list_freq, self._my_list_phase ] )

    # INIT PROCESS 
    # -------------------------------------------------------------------------
    def __init__(self, parser_process):
        """
        :param parser_process: Reference to a ParserProcess instance.
        :type parser_process: ParserProcess.
        """
        multiprocessing.Process.__init__(self)
        self._exit = multiprocessing.Event()
        
        # Instantiate a ParserProcess class for each communication channels
        self._parser1 = parser_process
        self._parser2 = parser_process
        self._parser3 = parser_process
        self._parser4 = parser_process
        self._parser5 = parser_process
        # overtones per cycle, set by run() from the frequencies file; until then
        # the last overtone cannot be told apart and no datalog row is flagged
        self._overtones_in_cycle = 0
        # parser process for sweep info nd utility error
        self._parser6 = parser_process
        
        # VER 0.1.6 Instantiate a ParserProcess class for TEC current
        self._parser_current_tec = parser_process
        
        self._dummy = True
        
        self.temperature_set_old = 0
        self.cycling_time_set_old = 0
        self.P_share_set_old = 0
        self.I_share_set_old = 0
        self.D_share_set_old = 0
        
        # self.Temperature_Pid_default = [0, 0, 0, 0, 0]
        self.Temperature_Pid_default = [self.temperature_set_old, 
                                        self.cycling_time_set_old, 
                                        self.P_share_set_old, 
                                        self.I_share_set_old, 
                                        self.D_share_set_old]
        # self.temperature_set_old = loadtxt(Constants.manual_frequencies_path)
        self.Temperature_Pid_default = loadtxt(Constants.manual_frequencies_path)
        
        #DEV 
        # control temperature switch default value 
        self.ctrl_bool_pre = 0
        
        # TODO INIT PARSER PROCESS for MULTISCAN
        # Frequency 
        self._parser_F_multi = parser_process
        # Dissipation 
        self._parser_D_multi = parser_process
        # Amplitude 
        self._parser_A_multi = parser_process
        # Phase 
        self._parser_P_multi = parser_process

        # serial process 
        self._serial = serial.Serial()
        
        # self.temperature_set_old = loadtxt(Constants.manual_frequencies_path)
        
        # init ring buffer for each harmonic
        self._environment = Constants.environment
        self._frequency_buffer_0   = RingBuffer(self._environment)
        self._dissipation_buffer_0 = RingBuffer(self._environment)
        self._temperature_buffer_0 = RingBuffer(self._environment)
        self._frequency_buffer_1   = RingBuffer(self._environment)
        self._dissipation_buffer_1 = RingBuffer(self._environment)
        self._temperature_buffer_1 = RingBuffer(self._environment)
        self._frequency_buffer_2   = RingBuffer(self._environment)
        self._dissipation_buffer_2 = RingBuffer(self._environment)
        self._temperature_buffer_2 = RingBuffer(self._environment)
        self._frequency_buffer_3   = RingBuffer(self._environment)
        self._dissipation_buffer_3 = RingBuffer(self._environment)
        self._temperature_buffer_3 = RingBuffer(self._environment)
        # TODO 5M
        self._frequency_buffer_4   = RingBuffer(self._environment)
        self._dissipation_buffer_4 = RingBuffer(self._environment)
        self._temperature_buffer_4 = RingBuffer(self._environment)
        
        self._frequency_buffer_0_a   = RingBuffer(self._environment)
        self._frequency_buffer_1_a  = RingBuffer(self._environment)
        self._frequency_buffer_2_a = RingBuffer(self._environment)
        self._frequency_buffer_3_a = RingBuffer(self._environment)
        self._frequency_buffer_4_a   = RingBuffer(self._environment)
        
        # init frequency dissipation list of ring buffer 
        self._my_list_f = [self._frequency_buffer_0, self._frequency_buffer_1, self._frequency_buffer_2, self._frequency_buffer_3, self._frequency_buffer_4]
        # VER 0.1.4
        self._my_list_f_a = [self._frequency_buffer_0_a, self._frequency_buffer_1_a, self._frequency_buffer_2_a, self._frequency_buffer_3_a, self._frequency_buffer_4_a]
        
        self._my_list_d = [self._dissipation_buffer_0, self._dissipation_buffer_1, self._dissipation_buffer_2, self._dissipation_buffer_3, self._dissipation_buffer_4]

        # TODO IMPORTANT chenge the init of array 
        # TODO 5M modified the number of items in the array below
        
        # init array for frequency, dissipation and temperature
        self._freq_range_mean = [0,0,0,0,0]
        
        self._diss_mean = [0,0,0,0,0]
        
        self._my_time = 0
        self._my_time_array = [0,0,0,0,0]
        
        # init amplitude, phase frequency sweep buffer for each harmonic
        # fundamental 
        self._amp_sweep_0 = None
        self._phase_sweep_0 = None
        self._freq_sweep_0 = None
        # 3rd overtone 
        self._amp_sweep_1 = None
        self._phase_sweep_1 = None
        self._freq_sweep_1 = None
        # 5th overtone 
        self._amp_sweep_2 = None
        self._phase_sweep_2 = None
        self._freq_sweep_2 = None
        # 7th ovetone 
        self._amp_sweep_3 = None
        self._phase_sweep_3 = None
        self._freq_sweep_3 = None
        # 9th overtone 
        self._amp_sweep_4 = None
        self._phase_sweep_4 = None
        self._freq_sweep_4 = None
        
        # init amplitude, phase and frequency list of buffer
        self._my_list_amp = [ self._amp_sweep_0 ,  self._amp_sweep_1 ,  self._amp_sweep_2,  self._amp_sweep_3,  self._amp_sweep_4 ]
        self._my_list_phase = [ self._phase_sweep_0, self._phase_sweep_1 , self._phase_sweep_2 , self._phase_sweep_3 , self._phase_sweep_4]
        self._my_list_freq = [ self._freq_sweep_0, self._freq_sweep_1 , self._freq_sweep_2 , self._freq_sweep_3 , self._freq_sweep_4]
        
        # DEBUG_0.1.1a
        # byte available at port
        self.byte_at_port = 0
        # DEBUG_0.1.1a
        # a boolean variable to check timeout at serial port and brek the for 
        self.TIME_OUT = 0
        
        # VER 0.1.4
        # init TEC controller status variable 
        self._data_status = 0
        
        # VER 0.1.5 
        # init TEC error register bit 
        self._error_register_bit = 0
        
        # VER 0.1.4
        # current values of resonance frequency array 
        self.freq_res_current_array = [None, None, None, None, None]
        # just another dummy counter
        self._just_another_counter = 0
        
        # VER 0.1.6 TEC electrical current value 
        self._current_tec = 0 
        
        
    # SERIAL PORT OPEN and general setting   
    # -------------------------------------------------------------------------
    def open(self, port,  speed = Constants.serial_default_overtone, 
             timeout = Constants.serial_timeout_ms, writeTimeout = Constants.serial_writetimeout_ms):
        """
        :param port: Serial port name :type port: str.
        :param speed: Overtone selected for the analysis :type speed: str.
        :param timeout: Sets current read timeout :type timeout: float (seconds).
        :param writetTimeout: Sets current write timeout :type writeTimeout: float (seconds).
        :return: True if the port is available :rtype: bool.
        """
    
        self._serial.port = port
        self._serial.baudrate = Constants.serial_default_speed 
        self._serial.stopbits = serial.STOPBITS_ONE
        self._serial.bytesize = serial.EIGHTBITS
        self._serial.timeout = timeout
        self._serial.writetimeout = writeTimeout

        #self._overtone = float(speed)
        
        # TODO check peaks mag vector here !!!
        # Loads frequencies from file
        peaks_mag = self.load_frequencies_file()
        
# =============================================================================
#         Log.i(TAG, "OPEN SERIAL PORT")
#         print("OPEN SERIAL PORT")
# =============================================================================
        
       
        # TODO SOLVED
        # ---------------------------------------------------------------------
        # GET the SELECTED FREQUENCY OVERTONE from the MAIN WINDOW  
        try:
           self._overtone = float(speed)
        except:   
           # print(TAG, "Warning: wrong frequency selection, set default to {} Hz Fundamental".format(peaks_mag[0]))
           self._overtone = peaks_mag[0]
    
        # get the index of the overtones 
        self._overtone_int = None
        for i in range(len(peaks_mag)):
            if self._overtone == peaks_mag[i]:
               self._overtone_int = i
# =============================================================================
#                print("self._overtone_int ")
#                print(self._overtone_int)
# =============================================================================
               
        # Checks for correct frequency selection
        if self._overtone_int == None:
           # print(TAG, "Warning: wrong frequency selection, set default to {} Hz Fundamental".format(peaks_mag[0])) 
           self._overtone_int = 0
        # ---------------------------------------------------------------------
        
        return self._is_port_available(self._serial.port)

    # RUN PROCESS
    # -------------------------------------------------------------------------
    def run(self):
        """
        The expected format is a buffer (sweep) and a new buffer as a new sweep. 
        The method parses data, converts each value to float and adds to a queue. 
        If incoming data can't be converted to float,the data will be discarded.
        """  
        
        # init error and flag parameters
        self._flag_error = 0
        self._flag_error_usb = 0
        self._err1 = 0
        self._err2 = 0
        
        # init frequency sweep and data process param
        startF = []
        stopF = []
        stepF = []
        readF = []
        sg_window_size = []
        spline_factor = []
        spline_points= []

        # get baseline coefficient 
        coeffs_all = self.baseline_coeffs()

        # init readline object 
        # line = rl(self._serial)
        
        frequencies_file_length = 0
        
        # set initial values of sweep buffer 
# =============================================================================
#         self._amp_sweep_0 = self._zerolistmaker(Constants.SAMPLES)
#         self._phase_sweep_0 = self._zerolistmaker(Constants.SAMPLES)
# =============================================================================
        for nn in Constants.overtone_dummy:
            self._my_list_amp[nn] = self._zerolistmaker(Constants.SAMPLES)
            self._my_list_phase[nn] = self._zerolistmaker(Constants.SAMPLES)
            self._my_list_freq[nn] = self._zerolistmaker(Constants.SAMPLES)
        
        # Checks if the serial port is currently connected
        if self._is_port_available(self._serial.port):
            
            # get the number of samples 
            samples = Constants.argument_default_samples 
            
            # TODO get the number of overtones in the peak frequencies file 
            frequencies_file = self.load_frequencies_file() 
            # how many overtones make one cycle: the datalog writes one row per
            # cycle, on the temperature message of the last one (elaborate_multi)
            self._overtones_in_cycle = len(frequencies_file)
            frequencies_file_length = len(frequencies_file)
            
            # Get array sweep paramaters 
            (startF, stopF, stepF, readF, 
             sg_window_size, spline_factor, spline_points) = self.get_frequencies(samples)
        
            # Gets the state of the serial port
            if not self._serial.isOpen(): 
                
                # open the serial port
                # -------------------------------------------------------------
                self._serial.open() 
                
                # Initializes the sweep counter
                k = 0 
                print(TAG,' Buffering and processing early raw data...')
                
                # creates a timestamp
                timestamp = time()
                
                # init frequency, dissipation and temperature ring buffer 
                self._environment = Constants.environment
                self._frequency_buffer   = RingBuffer(self._environment)
                self._dissipation_buffer = RingBuffer(self._environment)
                self._temperature_buffer = RingBuffer(self._environment)
                
                # Initializes the progress bar  
                # bar = ProgressBar(widgets=[TAG,' ', Bar(marker='>'),' ',Percentage(),' ', Timer()], maxval=self._environment).start() #
                
                # ACQUISITION LOOP
                # -------------------------------------------------------------
                while not self._exit.is_set():
                    
                    
                    # VER 0.1.4
                    # get resonance frequencies in acquisition loop. 
                    # get and set sweep start, stop and set frequencies sweep parameters, as function of the number of samples
                    if (k < Constants.environment):
                        # Get array sweep paramaters from frequency peaks file 
                        (startF, stopF, stepF, readF, 
                         sg_window_size, spline_factor, spline_points) = self.get_frequencies(samples)
                    
                    else:
                        # Get array sweep paramaters from the real time frequency peaks file 
                        (startF, stopF, stepF, readF, 
                         sg_window_size, spline_factor, spline_points) = self.get_frequencies_RT(samples)
                    
                    # data reset for new sweep 
                    data_mag = np.linspace(0,0,samples)   
                    data_ph  = np.linspace(0,0,samples)
                    
                    # DEV RAWDATA SAVE RAW SWEEP DATA 
                    # init frequency sweep raw array 
                    data_f = np.linspace(0,0,samples)
                    
                    overtone_index = 0
                    self._boolean_buffer_length = 0
                    
                    # cycle on all overtones 
                    for overtone_index in range(len(frequencies_file)):
                        
                        # DEBUG_0.1.1a
                        # print( "for loop overtone index and param= ", overtone_index, startF[overtone_index], stopF[overtone_index], int(stepF[overtone_index]) )
                       
                        try:
                            # amplitude/phase convert bit to dB/Deg parameters
                            vmax = 3.3
                            bitmax = 4096 
                            ADCtoVolt = vmax / bitmax
                            VCP = 0.9
                            
                            # DEBUG_0.1.1a
                            # get swepp time start 
                            timeStart = time()
                            
                            # -------------------------------------------------
                            # START SWEEP 
                            
                            # WRITE SWEEP COMMAND MESSAGE TO SERIAL PORT
                            # -------------------------------------------------
                            cmd = str(startF[overtone_index]) + ';' + str(stopF[overtone_index]) + ';' + str(int(stepF[overtone_index])) + '\n'
                            self._serial.write(cmd.encode())
                            
                            # DEBUG_0.1.1a
                            # added a short sleep before read serial
                            sleep(Constants.WRITE_SERIAL_WAIT)
                            
                            # Initializes buffer and strs record
                            buffer = ''
                            strs = ["" for x in range(samples + 2)]
                        
                        except:
                            print(TAG, "Info: exception serial write fail", end='\n')
                            Log.i(TAG, "Info: exception serial write fail")
                            self._flag_error_usb = 1
                            
                        if self._flag_error_usb == 0:
                            try:
                                
                                # READ SWEEP DATA AT SERIAL PORT
                                # -------------------------------------------------
                                while 1:
                                    # append string read at serial port to buffer 
                                    
                                    # DEBUG_0.1.1a
                                    self.byte_at_port = self._serial.inWaiting()
                                    buffer += self._serial.read(self.byte_at_port).decode(Constants.app_encoding)
                                    
                                    # check the time elapsed in serial read loop
                                    _time_elapsed = time() - timeStart
                                    
                                    # print ("acquiring buffer", _time_elapsed, overtone_index, "\n" )
                                    
# =============================================================================
#                                     nlines = buffer.count('\n')
# =============================================================================
                                
                                    # TODO use read line to decrease sampling time 
                                    # buffer += line.readline().decode() 
                                    
                                    # check for EOM character 
                                    if 's' in buffer:
                                        # print (_time_elapsed)
# =============================================================================
#                                         # reset input output buffer
#                                         self._serial.reset_input_buffer()
#                                         self._serial.reset_output_buffer()
#                                         sleep(0.1)
# =============================================================================
                                        # DEBUG_0.1.1a
                                        # print ("find EOM ovetone number = ", overtone_index)
                                        # DEBUG_0.1.1a
                                        #print(TAG, "EOM: byte at port = ", self.byte_at_port, end='\n')
                                        
                                        # VER 0.1.4
                                        # add a little delay at the end of the sweep 
                                        sleep(Constants.SLEEP_EOM_MULTISCAN)
                                        
                                        break
                                    
                                    # DEBUG_0.1.1a
                                    # insert a timeout in while acquisition loop to prevent freezing
                                    if  _time_elapsed > Constants.TIME_ELAPSED_TIMEOUT: 
                                        # DEBUG_0.1.1a
                                        print(TAG, "Info: timeout at overtone index = ", overtone_index , end='\n')
                                        self._flag_error_usb = 1
                                        self.TIME_OUT = 1
                                        # exit the while loop
                                        break   
                                    
                                if (self.TIME_OUT == 1):
                                    # DEBUG_0.1.1a
                                    # break the for ?
                                    self.TIME_OUT = 0
                                    sleep(0.5)
                                    # reset serial input/output buffer
                                    self._serial.reset_input_buffer()
                                    self._serial.reset_output_buffer()
                                    sleep(0.5)
                                    self._flag_error_usb = 1
                                    # print(TAG, "INFO: current overtone index = ", overtone_index , end='\n')
                                    
                                    # exit the for loop to prevent overtone mixing
                                    break
# =============================================================================
#                                     if nlines > Constants.argument_default_samples + 1:
#                                         print("EXCEPTION: exceed number of lines at serial port")
#                                         Log.i(TAG, "EXCEPTION: exceed number of lines at serial port")
#                                         
#                                         # reset input output buffer
#                                         self._serial.reset_input_buffer()
#                                         self._serial.reset_output_buffer()
#                                         
#                                         print("OVERTONE INDEX = ")
#                                         print (overtone_index)
#                                         
#                                         print(buffer)
#                                         
#                                         # self._flag_error_usb = 1
#                                         self._boolean_buffer_length = 1
#                                         break
# =============================================================================
                                   
     
                                # STOP SWEEP 
                                # -----------------------------------------
                                
                                if ( self._flag_error_usb == 0 ):
                                    # meaure time elapsed 
                                    # print ("Time elapsed for sweep")
                                    # print (time() - timestamp)
                                    
                                    # split each line
                                    data_raw = buffer.split('\n')
                                    length = len(data_raw)
                                    
                                    #  check the length of the serial read buffer if exceed the number of samples = 500
                                    if length > Constants.argument_default_samples + 2:
                                        print (TAG, "Info: exceed read buffer length = ", length, end='\n')
                                        self._flag_error_usb = 1
                                        data_mag = np.linspace(0,0,samples)   
                                        data_ph  = np.linspace(0,0,samples)
                                        # reset data raw
                                        data_raw = ""
                                        # reset buffer
                                        buffer = ""
                                        
                                        # reset serial input/output buffer
                                        sleep(0.5)
                                        self._serial.reset_input_buffer()
                                        self._serial.reset_output_buffer()
                                        sleep(0.5)
                                        self._flag_error_usb = 1
                                        print(TAG, "Info: current overtone index = ", overtone_index , end='\n')
                                        # break
                                        
                                    elif length < Constants.argument_default_samples + 2:
                                        # split data via semicolon ";"
                                        for i in range (length):
                                            strs[i] = data_raw[i].split(';')
                                            
                                        # TODO check the number of lines to read
                                        
                                        # converts data values to gain and phase 
                                        for i in range (length - 1):
                                            data_mag[i] = float(strs[i][0]) * ADCtoVolt / 2
                                            data_mag[i] = (data_mag[i]-VCP) / 0.03
                                            data_ph[i] = float(strs[i][1]) * ADCtoVolt / 1.5
                                            data_ph[i] = (data_ph[i]-VCP) / 0.01
                                            
                                        
                                        # --------------------------------------------------------------------------
                                        # DEV RAWDATA  SAVE RAW SWEEP DATA
                                        # Development tool, off by default and confined to common/sweepDump.py.
                                        # The live Raw Data View does not read these files, so this block can
                                        # be deleted outright without touching it.
                                        # --------------------------------------------------------------------------
                                        if SweepDump.is_enabled():
                                            # build the frequency data array
                                            for i in range (length - 1):
                                                data_f[i] = startF[overtone_index] + i * stepF[overtone_index]

                                            SweepDump.save_sweep(overtone_index, data_f, data_mag, data_ph)


# =============================================================================
#                             if (overtone_index == 0):
#                                 self._amp_sweep_0 = data_mag.tolist()
#                                 self._phase_sweep_0 = data_ph.tolist()
#                                 
#                                 _sweep_path = Constants.sweep_file_path
#                                 np.savetxt( _sweep_path, np.row_stack(self._amp_sweep_0) )
# =============================================================================
                                
# =============================================================================
#                             self._my_list_amp [overtone_index] = data_mag.tolist()
#                             self._my_list_phase [overtone_index] = data_ph.tolist()
#                             self._my_list_freq [overtone_index] = readF [overtone_index]
#                             
#                             # SAVE DATA FILE TO DEBUG 
#                             if overtone_index == 0:
#                                 _sweep_path = Constants.sweep_file_path
#                                 np.savetxt( _sweep_path, np.row_stack(self._my_list_freq [overtone_index]) )
# =============================================================================

                                        # get the temperature value from the buffer 
                                        data_temp = float((strs[length - 1][0]))
                                        
                                        # VER 0.1.4
                                        # read STATUS TEC BOOL 
                                        self._data_status = float((strs[length -1][1]))
                                        
                                        # VER 0.1.5 
                                        # read MTD415T Error Register 
                                        self._error_register_bit = int((strs[length -1][2]))
                                        # print ("DEBUG: error register string = ", self._error_register_bit )
                                        
                                        # decode the register and report the CHANGES to the GUI
                                        # (System Log): one line when an error appears, one when it
                                        # clears. It used to print every bit on every sweep, to
                                        # the console only. See common/tecStatus.py.
                                        self._tec_errors_pre = report_error_changes(
                                            decode_error_register(self._error_register_bit),
                                            getattr(self, "_tec_errors_pre", None),
                                            self._parser6.add_message)
                                                    
                                                    
# =============================================================================
#                                     
#                                         # DEBUG_0.1.1a
#                                         # ==================================================================================
#                                         # SAVE DATA FILE TO DEBUG 
#                                         _debug_path = Constants.debug_file_path
#                                         self._my_list_amp [overtone_index] = data_mag.tolist()
#                                         self._my_list_phase [overtone_index] = data_ph.tolist()
#                                         self._my_list_freq [overtone_index] = readF [overtone_index]
#                                         np.savetxt( _debug_path, np.column_stack([self._my_list_freq [overtone_index],
#                                                                                self._my_list_amp [overtone_index], 
#                                                                                self._my_list_phase [overtone_index] ]) )
#                                         # ==================================================================================
# =============================================================================
                                    
                                
                                # DEBUG_0.1.1a 
# =============================================================================
#                                     
#                                 # SET TEMPERATURE and PID PARAMETERS
#                                 # ------------------------------------------------- 
#                                 self._Temperature_PID_control()
# =============================================================================
                            
                            except:
                                 print(TAG, "Info: exception at serial port read process, overtone =", overtone_index, end='\n')
                                 Log.i(TAG, "Info: exception at serial port read process")
                                 
                                 # DEBUG_0.1.1a
                                 # reset buffer 
                                 data_mag = np.linspace(0,0,samples)   
                                 data_ph  = np.linspace(0,0,samples)
                                 
                                 # reset data raw
                                 data_raw = ""
                                 # reset buffer
                                 buffer = ""
                                 
                                 self._flag_error_usb = 1
                            
                            # VER 0.1.6 Read the actual TEC current 
                            # -----------------------------------------------------
                            # Command: "A?" 
                            # Response: Reads the actual TEC current, [x<LF>][mA], x < 0: Heating; x > 0: Cooling   
                            
                            try:
                                sleep(0.1)
                                self._serial.reset_input_buffer()
                                self._serial.reset_output_buffer()
                                # VER 0.1.5 send read TEC current command 
                                in_message = 'A' + '\n'
                                # sleep(0.2)
                                self._serial.write(in_message.encode())
                                sleep(0.1)
                                byte_at_port = self._serial.inWaiting()
                                out_message = ''
                                out_message = self._serial.read(byte_at_port).decode(Constants.app_encoding)
                                out_message = out_message.rstrip('\n')
                                
                                # VER 0.1.6 store the value of current only at fundamantal 
                                if (overtone_index == 0):
                                    self._current_tec = float(out_message)
                                
                            except:
                                print ("Unable to read TEC current ")
                                # VER 0.1.6 TODO set te current value of current to nan 
                            
                            # Read PID asked from the window while this process owns the
                            # port: answered here, between sweeps, the only moment the
                            # board is listening. Costs ~0.8 s once, on request only.
                            try:
                                if self._parser6.take_pid_read_request():
                                    self._parser6.add_pid(read_pid(self._serial))
                            except Exception as e:
                                print(TAG, "Warning: PID read failed: {}".format(e))
                            
                            # TEC Reset asked while this process owns the port: X0 / X1 / X0
                            # with the standard pauses, run here between two sweeps. Through
                            # the config flag alone the 0 / 1 / 0 could reach the controller as
                            # a single X0 (bench, 2026-09-09). Costs ~4.5 s once, on request.
                            try:
                                if self._parser6.take_tec_reset_request():
                                    _sent = reset_sequence(self._serial)
                                    # the sequence ends with the TEC off, as the flag the GUI wrote
                                    self.ctrl_bool_pre = 0
                                    self._parser6.add_message("TEC reset done by the acquisition: {} "
                                                              "(Enable pin Off/On/Off, error register cleared)".format(", ".join(_sent)))
                            except Exception as e:
                                print(TAG, "Warning: TEC reset failed: {}".format(e))
                            
                            # DEBUG_0.1.1a
                            try: 
                                # SET TEMPERATURE and PID PARAMETERS
                                self._Temperature_PID_control()
                                
                            except:
                                print(TAG, "Info: set temperature control failed", end='\n')
                                # Log.i(TAG, "EXCEPTION: exception at serial port read process")
                                self._flag_error_usb = 1
                            
# =============================================================================
#                                  # =================================================
#                                  # WHAT HAPPEN ?
#                                  print ("BUFFER = ")
#                                  print(buffer)
#                                  print(buffer)
#                                  print("DATA RAW ")
#                                  print(data_raw)
# =============================================================================
                                 
# =============================================================================
#                         # specify handlers for different exceptions        
#                         except ValueError:
#                             print(TAG, "WARNING (ValueError): convert raw to float failed", end='\n')
#                             #Log.w(TAG, "Warning (ValueError): convert Raw to float failed")
#                         except:
#                             #if self._flag_error_usb == 1:
#                             print(TAG, "WARNING: general exception at serial port read process", end='\n')
#                             self._flag_error_usb += 1
#                             
#                             # =================================================
#                             # WHAT HAPPEN ?
#                             print ("BUFFER = ")
#                             print(buffer)
#                             print("DATA RAW ")
#                             print(data_raw)
#                             # =================================================
#                             
#                             # close and open the serial port 
#                             # close serial port
#                             self._serial.close()
#                             sleep(0.1) 
#                             # open the serial port 
#                             self._serial.open() 
# =============================================================================
                            
# =============================================================================
#                             # TODO something is occured at the serial port 
#                             # blocking the program 
#                             self._serial.flushInput()
#                             self._serial.flushOutput()
#                             self._serial.close()
#                             self._serial.open() 
# =============================================================================
                            #Log.w(TAG, "Warning (ValueError): convert Raw to float failed")
                            
                        # -----------------------------------------------------
                        # DO THE DATA_PROCESSING PROCESS HERE !!!!!!!!!!!!!!!!!
                        # TODO add new serial data to parser queue
                        #self._parser1.add1(data_mag)
                        #self._parser2.add2(data_ph)
                        # -----------------------------------------------------
                        
                        # DATA PROCESSING 
                        # -----------------------------------------------------
                        # TODO if an exception is encountered before do not elaborate 
                        
                        if self._flag_error_usb == 0:
                            
                            # VER 0.1.4
                            # set the current values of resonance frequencies in file 
                            self.set_frequencies_RT( overtone_index, self.freq_res_current_array[overtone_index])
                            
                            try:
                                self.elaborate_multi(k, overtone_index,coeffs_all, readF[overtone_index], 
                                               samples, data_mag, data_ph, data_temp, sg_window_size[overtone_index], spline_points[overtone_index], 
                                               spline_factor[overtone_index], timestamp) 
                                
                                self.elaborate_ampli_phase_multi(overtone_index, coeffs_all, readF[overtone_index], data_mag, data_ph)
                            
                            except ValueError:
                                self._flag_error = 1
                                #if k > self._environment:
                                #   print(TAG, "WARNING (ValueError): miscalculation")
                                # self._flag_error_usb = 1
                                print(TAG, "Info: value error elaborate data", end='\n')
                                Log.i(TAG, "Info: value error elaborate data")

                                
                            except:
                                self._flag_error = 1
                                #if k > self._environment:
                                #   print(TAG, "WARNING (ValueError): miscalculation")
                                # self._flag_error_usb = 1
                                if (k > Constants.environment):
                                    print(TAG, "Info: exception general error elaborate data", end='\n')
                                    Log.i(TAG, "Info: exception general error elaborate data")
                        
# =============================================================================
#                         # DEBUG_0.1.1a    
#                         elif self._flag_error_usb == 1:
#                             # DEBUG_0.1.1a
#                             data_mag = np.linspace(0,0,samples)   
#                             data_ph  = np.linspace(0,0,samples)
#                             data_temp = 0
#                             self.elaborate_multi(k, overtone_index,coeffs_all, readF[overtone_index], 
#                                                samples, data_mag, data_ph, data_temp, sg_window_size[overtone_index], spline_points[overtone_index], 
#                                                spline_factor[overtone_index], timestamp) 
#                             self.elaborate_ampli_phase_multi(overtone_index, coeffs_all, readF[overtone_index], data_mag, data_ph)
# =============================================================================
                        
# =============================================================================
#                         # add data to the "strange" parameter queue
#                         self._parser6.add6([self._err1, self._err2, k, self._flag_error_usb, overtone_index])
# =============================================================================
                        
                        # VER 0.1.4
                        # add a new element to the error / status parser for the TEC STATUS variable 

                        self._parser6.add6([self._err1, self._err2, k, self._flag_error_usb, overtone_index, self._data_status,
                                                            self._error_register_bit])  # the GUI locks the TEC buttons on it
    
                        # DEBUG_0.1.1a
# =============================================================================
#                         if (self._flag_error_usb == 1):
#                             print(" a general error occured on overtone", overtone_index)
# =============================================================================
    
    
                        # refreshes error variables at each single overtone sweep
                        self._err1 = 0
                        self._err2 = 0
                        self._flag_error_usb = 0
                        self._boolean_buffer_length = 0 
                    
                    
                    # Increases sweep counter 
                    k += 1    
# =============================================================================
#                 if k == self._environment:
#                    bar.finish()
#                    print ("bar finished")
# =============================================================================
                
                # END ACQUISITION LOOP
                # -------------------------------------------------------------
                
                self._serial.close()
    
    def get_Temperature_set_Serial(self, value_T_set):
        return value_T_set
    
    def _TempCtrl(self):
        param = loadtxt(Constants.manual_frequencies_path)
        temperature_set = param[0]
        temperature_msg = 'T' + str(int(temperature_set)) + '\n'
        self._serial.write(temperature_msg.encode())
    
    def _Temperature_PID_control(self): 
        param = loadtxt(Constants.manual_frequencies_path)
        temperature_set = param[0]
        cycling_time_set = param[1]
        P_share_set= param[2]
        I_share_set = param[3]
        D_share_set = param[4]
        _var_bool = param[5]
        _ctrl_bool = param[6]
        
        if temperature_set != self.temperature_set_old:
            temperature_msg = 'T' + str(int(temperature_set)) + '\n'
            self._serial.write(temperature_msg.encode())  
            self.temperature_set_old = temperature_set
        
        if cycling_time_set != self.cycling_time_set_old:
            cycling_time_msg = 'C' + str(int(cycling_time_set)) + '\n'
            # wait for a while before complete the communication
            sleep(0.1)
            self._serial.write(cycling_time_msg.encode())  
            sleep(0.1)
            self.cycling_time_set_old = cycling_time_set
            # the only trace that a PID parameter really left this process;
            # routed to the GUI so that the System Log shows it too
            self._parser6.add_message("PID sent to the controller: {}".format(cycling_time_msg.strip()))
            
        if P_share_set != self.P_share_set_old: 
            P_Share_msg = 'P' + str(int(P_share_set)) + '\n'
            # wait for a while before complete the communication
            sleep(0.1)
            self._serial.write(P_Share_msg.encode())
            sleep(0.1)
            self.P_share_set_old = P_share_set
            # the only trace that a PID parameter really left this process;
            # routed to the GUI so that the System Log shows it too
            self._parser6.add_message("PID sent to the controller: {}".format(P_Share_msg.strip()))
            
        if I_share_set != self.I_share_set_old: 
            I_Share_msg = 'I' + str(int(I_share_set)) + '\n'
            # wait for a while before complete the communication
            sleep(0.1)
            self._serial.write(I_Share_msg.encode())
            sleep(0.1)
            self.I_share_set_old = I_share_set
            # the only trace that a PID parameter really left this process;
            # routed to the GUI so that the System Log shows it too
            self._parser6.add_message("PID sent to the controller: {}".format(I_Share_msg.strip()))
            
        if D_share_set != self.D_share_set_old: 
            D_Share_msg = 'D' + str(int(D_share_set)) + '\n'
            # wait for a while before complete the communication
            sleep(0.1)
            self._serial.write(D_Share_msg.encode())
            sleep(0.1)
            self.D_share_set_old = D_share_set
            # the only trace that a PID parameter really left this process;
            # routed to the GUI so that the System Log shows it too
            self._parser6.add_message("PID sent to the controller: {}".format(D_Share_msg.strip()))
        
        #DEV    
        # check if temperature control is enabled 
        if (_ctrl_bool != self.ctrl_bool_pre):  # value changed 
            # print("DEBUG: temperature control switch I/O ", _ctrl_bool)
            # init message 
            cmd = 'X' + str(int(_ctrl_bool)) + '\n'
            # wait for a while before complete the communication
            sleep(0.1)
            # serial write message 
            self._serial.write(cmd.encode())
            sleep(0.1)
            # store new value
            self.ctrl_bool_pre = _ctrl_bool
            # the only trace that the switch really left this process
            self._parser6.add_message("TEC switched by the acquisition: {}".format(cmd.strip()))
        
        # check if temperarure value is changed 
        if  (_var_bool) == 1.0:
            temperature_msg = 'T' + str(int(temperature_set)) + '\n'
            # wait for a while before complete the communication
            sleep(0.1)
            self._serial.write(temperature_msg.encode()) 
            sleep(0.1)
            _path = Constants.manual_frequencies_path
            # reset temperature control boolean variable
            np.savetxt( _path,  np.row_stack( [param[0], param[1], param[2], param[3],param[4], 0.0, param[6]] ), fmt='%d' )
            
    
    # STOP 
    def stop(self):
        
        # close serial port
        # DEBUG 0.1.1c
        try:
            self._serial.close()
            print ("serial COM port is closed")
        except: 
            print ("WARNING: unable to close COM port ")
        
        # Signals the process to stop acquiring data.
        try:
            self._exit.set()
            print ("exit acquisition loop ")
        except:
            print ("WARNING: unable exit acquisition loop")
            
        # reset the peak frequency value file
        frequency_calibration_array = self.load_frequencies_file()
        path_RT = Constants.cvs_peakfrequencies_RT_path
        np.savetxt(path_RT, np.column_stack([frequency_calibration_array, 
                                             frequency_calibration_array]))
    

    # GET FREQUENCIES 
    # TODO
    def get_frequencies(self, samples):

        # TODO 

        """
        :param samples: Number of samples :type samples: int.
        :return: overtone :rtype: float.
        :return: fStep, frequency step  :rtype: float.
        :return: readFREQ, frequency range :rtype: float list.
        """
        
        startF = []
        stopF = []
        SG_window_size = []
        spline_factor = []
        fStep = []
        spline_points= []
        readFREQ = []
        
        
        # Loads frequencies from calibration file
        peaks_mag = self.load_frequencies_file()
        # get numbers of overtones stored in calibration
        peaks_mag_length = len(peaks_mag)
        
        
#        # Checks QCS type 5Mhz or 10MHz
#        # Sets start and stop frequencies for the corresponding overtone
#        
#        if (peaks_mag[0] >4e+06 and peaks_mag[0]<6e+06):
#            switch = Overtone_Switcher_5MHz(peak_frequencies = peaks_mag)
#            # 0=fundamental, 1=3th overtone and so on
#            (overtone_name,
#             overtone_value, 
#             self._startFreq,
#             self._stopFreq,
#             SG_window_size,
#             spline_factor) = switch.overtone5MHz_to_freq_range(self._overtone_int)
#            
#            print(TAG,"openQCM Device setup: @5MHz")
        
        # 10 MHz get frequency sweep param
        if (peaks_mag[0] >9e+06 and peaks_mag[0]<11e+06):
            for i in range(peaks_mag_length):
                # get multiscan sweep paramters 
                (startF_temp, 
                 stopF_temp, 
                 SG_window_size_temp, 
                 spline_factor_temp) = self.getMultiscanParameters_10Mhz(peaks_mag, i)
                
                # assign multiscan sweep param
                # TODO I do not like manage the list in this way try numpy array here 
                startF.append(startF_temp)
                stopF.append(stopF_temp)
                SG_window_size.append(SG_window_size_temp)
                spline_factor.append(spline_factor_temp)
                
                # Sets the frequency step 
                fStep_temp = (stopF_temp - startF_temp)/(samples - 1)
                # assing value 
                fStep.append(fStep_temp)
                
                # set spline points
                spline_points_temp = int( (stopF_temp - startF_temp) ) + 1
                # assing value
                spline_points.append(spline_points_temp)
                
                # set frequencies array 
                frequencies_array_temp = np.arange(samples) * (fStep_temp) + startF_temp 
                # assign value 
                readFREQ.append(frequencies_array_temp)
                
        # 5 MHz get frequency sweep param
        if (peaks_mag[0]> 4e+06 and peaks_mag[0]<6e+06):
            for i in range(peaks_mag_length):
                # get multiscan sweep paramters 
                (startF_temp, 
                 stopF_temp, 
                 SG_window_size_temp, 
                 spline_factor_temp) = self.getMultiscanParameters_5Mhz(peaks_mag, i)
                
                # assign multiscan sweep param
                # TODO I do not like manage the list in this way try numpy array here 
                startF.append(startF_temp)
                stopF.append(stopF_temp)
                SG_window_size.append(SG_window_size_temp)
                spline_factor.append(spline_factor_temp)
                
                # Sets the frequency step 
                fStep_temp = (stopF_temp - startF_temp)/(samples - 1)
                # assing value 
                fStep.append(fStep_temp)
                
                # set spline points
                spline_points_temp = int( (stopF_temp - startF_temp) ) + 1
                # assing value
                spline_points.append(spline_points_temp)
                
                # set frequencies array 
                frequencies_array_temp = np.arange(samples) * (fStep_temp) + startF_temp 
                # assign value 
                readFREQ.append(frequencies_array_temp)
        
        
        
        # Sets the frequency step 
        # fStep = (self._stopFreq-self._startFreq)/(samples-1)
        
        # Sets spline points for fitting
        # spline_points = int((self._stopFreq-self._startFreq))+1
        
        # Sets the frequency range for the corresponding overtone
        # readFREQ = np.arange(samples) * (fStep) + self._startFreq 
        
        
        return (startF, stopF, fStep, readFREQ, SG_window_size, spline_factor, spline_points)
    
    
    # VER 0.1.4
    # get the current values of resonance frequencies
    def get_frequencies_RT(self, samples):
        
        startF = []
        stopF = []
        SG_window_size = []
        spline_factor = []
        fStep = []
        spline_points= []
        readFREQ = []
        
# =============================================================================
#         # Loads frequencies from calibration file
#         peaks_mag = self.load_frequencies_file()
# =============================================================================
        
        # VER 0.1.4 get current values of resonance frequency from file 
        # open the realt-time resonance frequencies file          
        peaks_mag_current = self.load_frequencies_file_RT()
        
        # get numbers of overtones stored in calibration
        peaks_mag_length = len(peaks_mag_current)
        
        # 10 MHz get frequency sweep param
        if (peaks_mag_current[0] >9e+06 and peaks_mag_current[0]<11e+06):
            for i in range(peaks_mag_length):
                # get multiscan sweep paramters 
                (startF_temp, 
                 stopF_temp, 
                 SG_window_size_temp, 
                 spline_factor_temp) = self.getMultiscanParameters_10Mhz(peaks_mag_current, i)
                
                # assign multiscan sweep param
                # TODO I do not like manage the list in this way try numpy array here 
                startF.append(startF_temp)
                stopF.append(stopF_temp)
                SG_window_size.append(SG_window_size_temp)
                spline_factor.append(spline_factor_temp)
                
                # Sets the frequency step 
                fStep_temp = (stopF_temp - startF_temp)/(samples - 1)
                # assing value 
                fStep.append(fStep_temp)
                
                # set spline points
                spline_points_temp = int( (stopF_temp - startF_temp) ) + 1
                # assing value
                spline_points.append(spline_points_temp)
                
                # set frequencies array 
                frequencies_array_temp = np.arange(samples) * (fStep_temp) + startF_temp 
                # assign value 
                readFREQ.append(frequencies_array_temp)
                
        # 5 MHz get frequency sweep param
        if (peaks_mag_current[0]> 4e+06 and peaks_mag_current[0]<6e+06):
            for i in range(peaks_mag_length):
                # get multiscan sweep paramters 
                (startF_temp, 
                 stopF_temp, 
                 SG_window_size_temp, 
                 spline_factor_temp) = self.getMultiscanParameters_5Mhz(peaks_mag_current, i)
                
                # assign multiscan sweep param
                # TODO I do not like manage the list in this way try numpy array here 
                startF.append(startF_temp)
                stopF.append(stopF_temp)
                SG_window_size.append(SG_window_size_temp)
                spline_factor.append(spline_factor_temp)
                
                # Sets the frequency step 
                fStep_temp = (stopF_temp - startF_temp)/(samples - 1)
                # assing value 
                fStep.append(fStep_temp)
                
                # set spline points
                spline_points_temp = int( (stopF_temp - startF_temp) ) + 1
                # assing value
                spline_points.append(spline_points_temp)
                
                # set frequencies array 
                frequencies_array_temp = np.arange(samples) * (fStep_temp) + startF_temp 
                # assign value 
                readFREQ.append(frequencies_array_temp)
        
        return (startF, stopF, fStep, readFREQ, SG_window_size, spline_factor, spline_points)
    
    def getMultiscanParameters_10Mhz(self, peaks, overtone):
        
        if (overtone == 0):
            start = peaks[0] - Constants.L10_fundamental
            stop  = peaks[0] + Constants.R10_fundamental
            SG_win_size = Constants.SG_window_size10_fundamental
            SP_factor = Constants.Spline_factor10_fundamental
        
        elif (overtone == 1): 
            start = peaks[1] - Constants.L10_3th_overtone
            stop  = peaks[1] + Constants.R10_3th_overtone
            SG_win_size = Constants.SG_window_size10_3th_overtone
            SP_factor = Constants.Spline_factor10_3th_overtone
        
        elif (overtone == 2): 
            start = peaks[2] - Constants.L10_5th_overtone
            stop  = peaks[2] + Constants.R10_5th_overtone
            SG_win_size = Constants.SG_window_size10_5th_overtone
            SP_factor = Constants.Spline_factor10_5th_overtone
        
        return(start, stop, SG_win_size, SP_factor)
        
    def getMultiscanParameters_5Mhz(self, peaks, overtone):
        # 5 MHz fundamental 
        if (overtone == 0):
            start = peaks[0] - Constants.L5_fundamental
            stop  = peaks[0] + Constants.R5_fundamental
            SG_win_size = Constants.SG_window_size5_fundamental
            SP_factor = Constants.Spline_factor5_fundamental
        # 15 MHz 3rd overtone     
        elif (overtone == 1): 
            start = peaks[1] - Constants.L5_3th_overtone
            stop = peaks [1] + Constants.R5_3th_overtone
            SG_win_size = Constants.SG_window_size5_3th_overtone
            SP_factor = Constants.Spline_factor5_3th_overtone 
        # 25 MHz 5th overtone     
        elif (overtone == 2): 
            start = peaks[2] - Constants.L5_5th_overtone 
            stop = peaks [2] + Constants.R5_5th_overtone
            SG_win_size = Constants.SG_window_size5_5th_overtone
            SP_factor = Constants.Spline_factor5_5th_overtone
        # 35 MHz 7th overtone 
        elif (overtone == 3): 
            start = peaks[3] - Constants.L5_7th_overtone  
            stop = peaks [3] + Constants.R5_7th_overtone
            SG_win_size = Constants.SG_window_size5_7th_overtone
            SP_factor = Constants.Spline_factor5_7th_overtone
        # 45 MHz 7th overtone
        # TODO
        elif (overtone == 4): 
            start = peaks[4] - Constants.L5_9th_overtone  
            stop = peaks [4] + Constants.R5_9th_overtone
            SG_win_size = Constants.SG_window_size5_9th_overtone
            SP_factor = Constants.Spline_factor5_9th_overtone
        
        return(start, stop, SG_win_size, SP_factor) 
    
    def get_readFREQ(self, samples, overtone):
        # init temp var
        startF = []
        stopF = []
        SG_window_size = []
        spline_factor = []
        fStep = []
        spline_points= []
        
        
        # Loads frequencies from calibration file
        peaks_mag = self.load_frequencies_file()
        # get numbers of overtones stored in calibration
        # peaks_mag_length = len(peaks_mag)
        
        # 10 MHz quartz resonators
        if (peaks_mag[0] >9e+06 and peaks_mag[0]<11e+06):
            # get multiscan sweep paramters 
            (startF_temp, 
             stopF_temp, 
             SG_window_size_temp, 
             spline_factor_temp) = self.getMultiscanParameters_10Mhz(peaks_mag, overtone)

            # assign multiscan sweep param for 10 MHz quartz resonators
            # TODO I do not like manage the list in this way try numpy array here 
            startF.append(startF_temp)
            stopF.append(stopF_temp)
            SG_window_size.append(SG_window_size_temp)
            spline_factor.append(spline_factor_temp)
            
            # Sets the frequency step 
            fStep_temp = (stopF_temp - startF_temp)/(samples - 1)
            # assing value 
            fStep.append(fStep_temp)
            
            # set spline points
            spline_points_temp = int( (stopF_temp - startF_temp) ) + 1
            # assing value
            spline_points.append(spline_points_temp)
            
            # set frequencies array 
            frequencies_array_temp = np.arange(samples) * (fStep_temp) + startF_temp 
        
        # 5 MHz quartz resonators
        if (peaks_mag[0] >4e+06 and peaks_mag[0]<6e+06):
            # get multiscan sweep paramters 
            (startF_temp, 
             stopF_temp, 
             SG_window_size_temp, 
             spline_factor_temp) = self.getMultiscanParameters_5Mhz(peaks_mag, overtone)

            # assign multiscan sweep param for 5 MHz quartz resonators
            # TODO I do not like manage the list in this way try numpy array here 
            startF.append(startF_temp)
            stopF.append(stopF_temp)
            SG_window_size.append(SG_window_size_temp)
            spline_factor.append(spline_factor_temp)
            
            # Sets the frequency step 
            fStep_temp = (stopF_temp - startF_temp)/(samples - 1)
            # assing value 
            fStep.append(fStep_temp)
            
            # set spline points
            spline_points_temp = int( (stopF_temp - startF_temp) ) + 1
            # assing value
            spline_points.append(spline_points_temp)
            
            # set frequencies array 
            frequencies_array_temp = np.arange(samples) * (fStep_temp) + startF_temp 
        
        return frequencies_array_temp
        
    
    # VER 0.1.4
    # set the current values of resonance frequencies in file 
    def set_frequencies_RT(self, overtone_RT, frequency_RT):
      
        # open file 
        frequency_array_RT = self.load_frequencies_file_RT()
        
        # get overtone and frequencie
        frequency_array_RT[overtone_RT] = frequency_RT
        
        # update and write file with current value of frequency at specified overtone
        path_RT = Constants.cvs_peakfrequencies_RT_path
        np.savetxt(path_RT, np.column_stack([frequency_array_RT, frequency_array_RT]))    
    
    # LOAD FREQUENCIES FILE 
    @staticmethod
    def load_frequencies_file():
        data  = loadtxt(Constants.cvs_peakfrequencies_path)
        peaks_mag = data[:,0]
        #peaks_phase = data[:,1] #unused at the moment
        return peaks_mag
    
    # VER 0.1.4
    # load file containing the current values of resonance frequencies 
    @staticmethod
    def load_frequencies_file_RT():
        # VER 0.1.4
        data  = loadtxt(Constants.cvs_peakfrequencies_RT_path)
        peaks_mag_RT = data[:,0]
        #peaks_phase = data[:,1] #unused at the moment
        return peaks_mag_RT
    
    # LOAD CALIBRATION FILE 
    def load_calibration_file(self):
        # Loads Fundamental frequency and Overtones from file
        peaks_mag = self.load_frequencies_file()
        
        ############################### 
        # TODO check the damn QCM type 
        ###############################
        
        '''
        # Checks QCS type 5Mhz or 10MHz
        if len(peaks_mag) == 5:
           filename = Constants.csv_calibration_path
        elif len(peaks_mag) == 3:
           filename = Constants.csv_calibration_path10 
        '''
        
        # Checks QCS type 5Mhz or 10MHz
        if (peaks_mag[0] >4e+06 and peaks_mag[0]<6e+06):
           filename = Constants.csv_calibration_path
        elif (peaks_mag[0] >9e+06 and peaks_mag[0]<11e+06):
           filename = Constants.csv_calibration_path10 
        
        
        data  = loadtxt(filename)
        freq_all  = data[:,0]
        mag_all   = data[:,1]
        phase_all = data[:,2]
        return freq_all, mag_all, phase_all

    # GET SWEEP PARAMTERS 
    def get_sweep_parameters(): 
        # TODO develop if necessary a simple get sweep param
        print ("GET SWEEP PARAMETERS HERE")
    
    # TODO get all overtone  
    @staticmethod
    def get_speeds():
        #:return: List of the Overtones :rtype: str list.
        # Loads frequencies from  file (path: 'common\')
        data  = loadtxt(Constants.cvs_peakfrequencies_path)
        peaks_mag = data[:,0]
        reversed_peaks_mag = peaks_mag[::-1]
        return [str(v) for v in reversed_peaks_mag]   

    # SEARCH TEENSY COM PORTS     
    @staticmethod
    def get_ports(): 
        from openQCM.common.architecture import Architecture,OSType
        if Architecture.get_os() is OSType.macosx:
            import glob
            return glob.glob("/dev/tty.usbmodem*")
        elif Architecture.get_os() is OSType.linux:
            import glob
            return glob.glob("/dev/ttyACM*")
        else:
            found_ports = []
            port_connected = []
            found = False
            ports_avaiable = list(list_ports.comports())
            # VER 0.1.5 change the iedntification of the COM port connected to Teensy 4.0 
            # using USB VID:PID=16C0:0483  VID 0 VENDOR_ID and PID = PRODUCT_ID of USB devices to identify hardware
            # port[2] = hwid Technical description of serial port 
            for port in ports_avaiable:
                if port[2].startswith("USB VID:PID=16C0:0483"):
                    found = True
                    port_connected.append(port[0])
                #else:
                #    Gets a list of the available serial ports.
                #    found_ports.append(port[0])
            if found:
               found_ports = port_connected 
            return found_ports
    
    # COM PORT AVAILABLE 
    def _is_port_available(self, port):
        """
        :param port: Port name to be verified.
        :return: True if the port is connected to the host :rtype: bool.
        """
        for p in self.get_ports():
            if p == port:
                return True
        return False
    
    def _zerolistmaker(self, n):
        listofzeros = [0] * n
        return listofzeros
