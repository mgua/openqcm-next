/***********************************************************************************************

   LICENSE
   Copyright (C) 2018 openQCM
   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   You should have received a copy of the GNU General Public License
   along with this program.  If not, see http://www.gnu.org/licenses/gpl-3.0.txt
  --------------------------------------------------------------------------------
   OPENQCM NEXT - Quartz Crystal Microbalance with dissipation monitoring,
   multiovertone monitoring and temperature control
   openQCM is the unique opensource quartz crystal microbalance
   http://openqcm.com/

   ELECTRONICS
     - board and firmware designed for TEENSY 4.0 dev board https://www.pjrc.com/store/teensy40.html
     - DDS/DAC Synthesizer AD9851
     - phase comparator AD8302
     - I2C digital potentiometer AD5251+
     - MTD415T - TEC driver Thorlabs
     info      https://www.thorlabs.com/thorproduct.cfm?partnumber=MTD415T
     datasheet https://www.thorlabs.com/drawings/b4052d6b3d0a3c51-05F7919E-E07A-065E-046B0AD9948EAEB5/MTD415T-DataSheet.pdf

     - Transistor to turn on the TEC THORLAB MTD415T: PIN 10 = HIGH
     - Teensy pin control to enable/disable TEC THORLAB MTD415T: PIN 11 = LOW
     - MCP9808 temperature sensor for ambient temperature monitoring
     - FAN added a cooling fan to optimize the termal control, in particular to prevent overheating of the fluidic cell

   HISTORY CHANGES
   --------------------------------------------------------------------------------
   version      0.1.5d
   version tag  // VER 0.1.5d
   date         2026-10-02

   SWEEP AVERAGE: THE TWO SUMS ARE RESET AT EVERY FREQUENCY POINT
   - Bug in 0.1.5a, 0.1.5b and 0.1.5c (and their -TEST variants): `value` and
     `value2`, the sums of the AVERAGE_SAMPLE = 500 ADC readings of each point,
     are globals initialised to 0 at power-up and NEVER reset. After the
     division they hold the mean just printed, so the next point's sum started
     from it: printed v_i = m_i + v_(i-1)/500. On a steady signal that is
     m * 500/499 = +0.2 % on both channels (magnitude and phase counts), and
     the first point of every sweep also carried 1/500 of the last point of the
     sweep before -- another overtone. Small, but not negligible for the exact
     divider inversion of the host.
   - Fix: both sums are set to 0 before the 500 readings of every point.
     Nothing else changes: same averaging, same wire format, same commands.
   - FW_VERSION goes to 0.1.5d, and Constants.FW_VERSION moves with it.

   version      0.1.5c
   version tag  // VER 0.1.5c
   date         2026-08-31

   STOP AN ONGOING SWEEP
   - End the sweep in progress over serial communication
      COMMAND     RESPONSE
      'Q'         the sweep stops at the next whole sample and the measurement
                  terminates normally, so the stream still ends with the
                  contracted line temperature;status;error;s
     Why it exists: the board sweeps once per command and reads the serial port
     only at the top of loop(), so a sweep runs to completion whatever the host
     does. When the host stops an acquisition it kills its own child process,
     but the BOARD keeps sending for the rest of the sweep -- about 1.8 s per
     overtone on this instrument -- and the next question the GUI asks comes
     back answered with amplitude;phase data. 'Q' is what makes taking the port
     back immediate instead of a wait.
   - The sweep loop polls Serial at the END of each iteration, so the break
     never lands in the middle of a printed line, and consumes only the 'Q'
     line: any other character is left for the parser at the top of loop().
   - 'Q' also has a top-level branch that does nothing, which is worth having:
     without it the letter falls through to the sweep parser and silently
     overwrites freq_start. ⚠️ It does NOT start a scan -- message is latched
     only after the THIRD field, so a single letter never begins a sweep. That
     is the difference from openQCM Q-1, whose parser did latch and whose 'F'
     really could set the board off from 0 Hz; the claim that ours behaves the
     same way was wrong and is corrected here.
   - FW_VERSION goes to 0.1.5c, and Constants.FW_VERSION moves with it.

   version      0.1.5b
   version tag  // VER 0.1.5b
   date         2026-08-31

   MACHINE IDENTIFICATION NUMBER
   - Read the identification number of the board over serial communication
      COMMAND     RESPONSE
      'S'         SSNN, e.g. 1920, or NO_SERIAL when the board has none
     The number lives in four bytes of Teensy EEPROM written once per board by
     firmware/openQCM_Next_SerialNumber. This firmware only READS it: if the
     magic byte is missing it reports NO_SERIAL and never invents or writes one.
     EEPROM layout, shared byte for byte with the openQCM Q-1:
        [0] MAGIC 0xA5   [1] SERIES   [2] UNIT HIGH   [3] UNIT LOW  (big-endian)
     Format is SSNN, one compact integer with no separator: series without
     leading zeros, unit always two digits, sprintf("%u%02u", series, unit).
     Series 19 unit 20 is 1920, and the board after 2099 is 2100. The older
     SERIES-NNNN form is obsolete and appears nowhere.
   - FW_VERSION goes to 0.1.5b. The host compares this string exactly and offers a
     firmware update when it differs, so Constants.FW_VERSION moves with it.

   version      0.1.5a
   version tag  // VER 0.1.5a
   date         2024-02-19 

   MINOR REVISION
   - Higher pot (potentiometer) value for signal noise reduction. electronic amplifier fixed 
     
     #define POT_VALUE 240 // 180 
     
     note: add a led blink alert for checking the firmware minor update
   
   version     0.1.5
   version tag // VER 0.1.5
   date        2022-11-14 
   - Change the way the MCP9808 error status is read by using error register 
   defined in Error Register and Safety Bitmask (paragraph 6.3 page 18 MTD415T Data Sheet Rev. 1.2)
   - Read MCP9808 TEC controller error register
   PROGRAMMING
   COMMAND   RESPONSE
   E?        return: 16 bit error register
             Reads the Error Register. For responses see section:
             Error Register and Safety Bitmask (paragraph 6.3 page 18 MTD415T Data Sheet Rev. 1.2)
   - Improved MTD415T startup, insert a delay and serial flush in setup()
   - Send temperature and error register command in MTD415T status: 
   temperature control acrtive and temperature setpoint ok 
   - Add a new parameter to the sweep output buffer: error_register_bit
        amplitude_0;phase_0
        amplitude_1;phase_1
        ...
        amplitude_n;phase_n
        temperature;status_control;error_register_bit;termination_char     
   - Turn the Fan ON if only if the temperature control is active 

   --------------------------------------------------------------------------------
   version 0.1.4
   version tag // VER 0.1.4
   - Change the sweep frequency step to 1 Hz to avoid distortion of the raw signal
   Parameters affecting ADC sampling:
      #define AVERAGING
      int AVERAGE_SAMPLE
      ADC_CONVERSION_SPEED
      ADC_SAMPLING_SPEED
   - change the average to 500 samples
   int AVERAGE_SAMPLE = 500;
   - Read the current firmware version using serial communication,
      COMMAND     RESPONSE
      ‘F’     FW_VERSION
    The current firmware version is defined in the firmware
    #define FW_VERSION "0.1.4"
   - Read the TEC controller status and value of electrical current
      COMMAND     RESPONSE
      ‘A?’    Reads the actual TEC, [x<LF>][mA]
   - TEC status control variable definition
      // VER 0.1.4
      // variable current status control
      // _STATUS_CONTROL = -1   > TEC controller is active and STATUS pin is low and current is null
      // _STATUS_CONTROL =  0   > TEC controller is not active
      // _STATUS_CONTROL =  1   > TEC controller is active and STATUS pin is low and current is not null
      // _STATUS_CONTROL =  2   > TEC controller is active and STATUS pin is HIGH
   - Test sweep string
      5000000;5016000;1
   - TODO set adc conversion and sampling speed. Current value is HIGH_SPEED

   --------------------------------------------------------------------------------

   version 0.1.3
   --

   version 0.1.1c
   MAJOR CHANGES
    - include ADC.h library in src directory
    https://pedvide.github.io/ADC/ and https://github.com/pedvide/ADC

   version 0.1.1a
   MAJOR CHANGES
    - Change the RGB pin definition and RGB colour function, accoring to electronic configuration
    - Change the colour of onboard RGB led pin for different machine status
    - Change the ADC conversion speed to VERY_HIGH_SPEED to eliminate some noise in amplitude signal
    - Change the temperature measurement via THORLAB MTD415T, even if temperatre control is turned off
    - Change the temperature control via THORLAB MTD415T ENABLE PIN

   TEST MTD415T using enable control pin
   --------------------------------------------------------------------------------
   PROGRAMMING
   COMMAND   RESPONSE
   m?        Reads the version of hardware and software
   TEMPERATURE
   --------------------------------------------------------------------------------
   programming
   Tx        Sets the set temperature to x (x: 5000 to 45000 [10-3 °C])
   Lx        Sets the TEC current limit to x (x: 200 to 2000 [mA])
   reading
   T?        Reads the set temperature (Value range x: 5000 to 45000 [10-3 °C])
   Te?       Reads the actual temperature
   A?        Reads the actual TEC current in [mA]
   PID Settings
   ----------------------------------------------------------------------------------------------------
   programming
   Cx        Sets the cycling time to x (Value range x: 1 to 1000 [msec])     default 50 msec
   Px        Sets the P Share to x  (Value range x: 0 to 100000 [mA/K])       default 1000 mA/K
   Ix        Sets the I Share to x  (Value range x: 0 to 100000 [mA/(K+sec)]) default 200 mA/(K*sec)
   Dx        Sets the D Share to x  (Value range x: 0 to 100000 [(mA*s)/K])   default 100 (mA*sec)/K
   ----------------------------------------------------------------------------------------------------

   TEST FREQUENCY INPUT STRING
   // VER 0.1.4
   5000000;5012000;1 (12k samples)
   5000000;5000100;1 (100 samples)

   --------------------------------------------------------------------------------
   version  0.1.5
   date     2022-10-31
   author   marco - openQCM team
   --------------------------------------------------------------------------------

 ***********************************************************************************************/

/************************** LIBRARIES **************************/
#include <Wire.h>

// VER 0.1.5b
// MACHINE IDENTIFICATION NUMBER, four bytes of EEPROM written by
// firmware/openQCM_Next_SerialNumber. Layout shared with the openQCM Q-1.
#include <EEPROM.h>
#define ADDR_MAGIC        0
#define ADDR_SERIES       1
#define ADDR_SERIAL_HIGH  2
#define ADDR_SERIAL_LOW   3
#define MAGIC_BYTE        0xA5

// libraries included in /src folder
#include "src/Adafruit_MCP9808.h"
# include "src/ADC/ADC.h"
# include "src/ADC/ADC_util.h"

/*************************** DEFINE ***************************/
// potentiometer AD5252 I2C address is 0x2C(44)
#define ADDRESS 0x2C
// potentiometer AD5252 default value
// VER 0.1.4 low pot value for compatibility with new electronic amplifier
// VER 0.1.5a higher pot value electronic amplifier fixed 
#define POT_VALUE 240 // 180 
// reference clock
#define REFCLK 125000000

#define AVERAGING   1
#define RESOLUTION 12

// VER 0.1.5 define wait time for MTD415T startup
// wait for a second before MTD415T serial flush in setup
#define MTD415T_TIME_SEC_STARTUP  1000

// VER 0.1.4 define firmware version
#define FW_VERSION "0.1.5d"


/*************************** VARIABLE DECLARATION ***************************/

// VER 0.1.4 change reduce the number of samples for averaging ADC
int AVERAGE_SAMPLE = 500;

// RGB LED
int RGB_RED_PIN   = 5;
int RGB_GREEN_PIN = 6;
int RGB_BLUE_PIN  = 7;

// current input frequency
long freq = 0;
// DDS Synthesizer AD9851 pin function for TEENSY 4.0
int WCLK = 3;
int DATA = 4;
int FQ_UD = 2;
// frequency tuning word
long FTW;
float temp_FTW; // temporary variable

// T40 pin ADC
const int readPin = A9;
const int readPin2 = A3;
// init  adc object
ADC *adc = new ADC();

// TODO VER 0.1.3
// wait for a while before change the frequency of the input signal
// to prevent distortion in the response signal
// ADC init variabl
boolean WAIT = false;
// ADC waiting delay microseconds
int WAIT_DELAY_US = 200;
// ADC averaging
boolean AVERAGING_BOOL = true;

// VER 0.1.4 change - reduce the number of samples for smoothing ADC
// init number of averaging
// VER 0.1.3 doubled number of samples for smoothing ADC
// int AVERAGE_SAMPLE = 4096; // TODO VER 0.1.3 increase to 8192

// teensy ADC averaging init
// int ADC_RESOLUTION = 13;

// init sweep param
long freq_start;
long freq_stop;
long freq_step;

// init output ad8302 measurement (cast to double)
double measure_phase = 0;
double measure_mag = 0;

// MTD415T variable declaration
// -----------------------------
// Status Signal input
// HIGH = Temperature within defined temperature window
// LOW  = Temperature outside programmed temperature window or an error occurred
int STATUS_TEC = 9;
// Transistor to turn on the TEC THORLAB MTD415T: PIN 10 = HIGH
int CTRL_SWITCH_PIN = 10;
// Teensy pin control to enable/disable TEC THORLAB MTD415T: PIN 11 = LOW
int ENABLE_PIN = 11;
// set boolean temperature control switch OFF
boolean CTRL_SWITCH = false;

// TODO embedded light on T40 delete ?
const int ledPin = 13;

// MCP9808 temperature sensor
// -----------------------------
// Create the MCP9808 temperature sensor object
Adafruit_MCP9808 tempsensor = Adafruit_MCP9808();
// init temperature variable
float temperature = 0;

// TODO DELETE
int _TIME = 100;

// VER 0.1.4
// variable current status control
// _STATUS_CONTROL = -1   > TEC controller is active and STATUS pin is low and current is null
// _STATUS_CONTROL =  0   > TEC controller is not active
// _STATUS_CONTROL =  1   > TEC controller is active and STATUS pin is low and current is not null
// _STATUS_CONTROL =  2   > TEC controller is active and STATUS pin is HIGH
int _STATUS_CONTROL = 0;

// VER 0.1.4
// FAN control pin
// T40 pin  8 = voltage control (output)
// T40 pin 12 = status control  (input)
int FAN_PIN = 8; // 12

/*************************** FUNCTION ***************************/

/* AD9851 set frequency fucntion */
void SetFreq(long frequency)
{
  // set to 125 MHz internal clock
  temp_FTW = (frequency * pow(2, 32)) / REFCLK;
  FTW = long (temp_FTW);

  long pointer = 1;
  int pointer2 = 0b10000000;
  int lastByte = 0b10000000;

  /* 32 bit dds tuning word frequency instructions */
  for (int i = 0; i < 32; i++)
  {
    if ((FTW & pointer) > 0) digitalWrite(DATA, HIGH);
    else digitalWrite(DATA, LOW);
    digitalWrite(WCLK, HIGH);
    digitalWrite(WCLK, LOW);
    pointer = pointer << 1;
  }

  /* 8 bit dds phase and x6 multiplier refclock*/
  for (int i = 0; i < 8; i++)
  {
    //if ((lastByte & pointer2) > 0) digitalWrite(DATA, HIGH);
    //else digitalWrite(DATA, LOW);
    digitalWrite(DATA, LOW);
    digitalWrite(WCLK, HIGH);
    digitalWrite(WCLK, LOW);
    pointer2 = pointer2 >> 1;
  }

  digitalWrite(FQ_UD, HIGH);
  digitalWrite(FQ_UD, LOW);

  //FTW = 0;
}

// TODO DELETE BLINK
void my_blink() {
  digitalWrite(ledPin, HIGH);   // set the LED on
  delay(100);                  // wait for a second
  digitalWrite(ledPin, LOW);    // set the LED off
  delay(100);
}

// RGB LED function
// RGB light value 0,..., 255
void RGB_color(int red_light_value, int green_light_value, int blue_light_value)
{
  analogWrite(RGB_RED_PIN, 255 - red_light_value);
  analogWrite(RGB_GREEN_PIN, 255 - green_light_value);
  analogWrite(RGB_BLUE_PIN, 255 - blue_light_value);
}

// VER 0.1.5a blink message 
void blink_a(){
  // point
  RGB_color(0, 0, 0); 
  delay(250);
  RGB_color(255, 255, 255); 
  delay(250); 
  
  // line
  RGB_color(0, 0, 0); 
  delay(750);     
  RGB_color(255, 255, 255); 
  
}

// flush serial 1
void Serial_1_Flush() {
  while (Serial1.available() > 0) {
    String flush_buffer = Serial1.readStringUntil('\n');
    // DEBUG
    // Serial.print ("DEBUG: serial1 flush read buffer: ");
    // Serial.println(flush_buffer);
  }
}


/*************************** SETUP ***************************/
void setup()
{
  // Initialise I2C communication as Master
  Wire.begin();
  // Initialise serial communication, set baud rate = 9600
  Serial.begin(115200);
  // DEBUG_0.1.1a
  Serial.setTimeout(250);

  // set potentiometer value
  // Start I2C transmission
  Wire.beginTransmission(ADDRESS);
  // Send instruction for POT channel-0
  Wire.write(0x01);
  // Input resistance value, 0x80(128)
  Wire.write(POT_VALUE);
  // Stop I2C transmission
  Wire.endTransmission();

  // AD9851 set pin mode
  pinMode(WCLK, OUTPUT);
  pinMode(DATA, OUTPUT);
  pinMode(FQ_UD, OUTPUT);

  // AD9851 enter serial mode
  digitalWrite(WCLK, HIGH);
  digitalWrite(WCLK, LOW);
  digitalWrite(FQ_UD, HIGH);
  digitalWrite(FQ_UD, LOW);

  // ----------------------------------------------------------
  // TEENSY 4.0 ADC SETTING
  // ----------------------------------------------------------

  // T40 init ADC pin
  pinMode(readPin, INPUT);
  pinMode(readPin2, INPUT);

  // ADC0 setting
  adc->setAveraging(AVERAGING); // set number of averages
  adc->setResolution(RESOLUTION); // set bits of resolution
  // it can be any of the ADC_CONVERSION_SPEED enum: VERY_LOW_SPEED, LOW_SPEED, MED_SPEED, HIGH_SPEED_16BITS, HIGH_SPEED or VERY_HIGH_SPEED
  // see the documentation for more information
  // additionally the conversion speed can also be ADACK_2_4, ADACK_4_0, ADACK_5_2 and ADACK_6_2,
  // where the numbers are the frequency of the ADC clock in MHz and are independent on the bus speed.
  adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED); // VER 0.1.4 change the conversion speed to HIGH_SPEED
  // it can be any of the ADC_MED_SPEED enum: VERY_LOW_SPEED, LOW_SPEED, MED_SPEED, HIGH_SPEED or VERY_HIGH_SPEED
  adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED); // VER 0.1.4 change the conversion speed to HIGH_SPEED

  // ADC1 setting
  adc->setAveraging(AVERAGING, ADC_1); // set number of averages
  adc->setResolution(RESOLUTION, ADC_1); // set bits of resolution
  adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED, ADC_1); // change the conversion speed to HIGH_SPEED
  adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED, ADC_1); // change the sampling speed to HIGH_SPEED

  // start adc read synchronized continuous
  adc->startSynchronizedContinuous(readPin, readPin2);

  // VER 0.1.5 TODO delete MCP9808 temperature sensor init
  // begin MCP9808 sensor temperature sensor
  tempsensor.begin();

  // ----------------------------------------------------------
  // MTD415T TEC CONTROLLER SETUP
  // ----------------------------------------------------------

  // init status signal pin
  pinMode(STATUS_TEC, INPUT);
  // init control switch power on/off
  pinMode(CTRL_SWITCH_PIN, OUTPUT);
  // init enable pin
  pinMode(ENABLE_PIN, OUTPUT);
  // Turn ON MTD415T TEC by default
  digitalWrite(CTRL_SWITCH_PIN, HIGH);
  // Disable temperature control TEC by default (LOW active)
  digitalWrite(ENABLE_PIN, HIGH);

  // begin T40 UART Serial1
  Serial1.begin(115200);
  // DEBUG_0.1.1a
  Serial1.setTimeout(250);

  // VER 0.1.5
  // wait for MTD415T at startup
  delay(MTD415T_TIME_SEC_STARTUP);
  // flush serial 1 at startup, clear the serial1 at startup
  Serial_1_Flush();

  // RGB LED SETUP
  pinMode(RGB_RED_PIN, OUTPUT);
  pinMode(RGB_GREEN_PIN, OUTPUT);
  pinMode(RGB_BLUE_PIN, OUTPUT);

  // shine on you crazy diamond, exposed to the light openqcm (0, 142, 192)
  RGB_color(255, 255, 255);

  // VER 0.1.4
  // FAN pwm control init
  pinMode(FAN_PIN, OUTPUT);

  // T40 PWM and Tone code info https://www.pjrc.com/teensy/td_pulse.html
  // setting PWM frequency output
  // analogWriteFrequency(FAN_PIN, 25000);
  // setting PWM resolution analogWrite value 0 to 4095, or 4096 for high
  // analogWriteResolution(12);

  // setting PWM output ( tested: minimum 40 to maximum 255 )
  // VER 0.1.5 turn off the fan if the temperature control is disabled
  analogWrite(FAN_PIN, 0);

  delay(100);
}

/*************************** GLOBAL VARIABLE INIT ***************************/
int message = 0;
// boolean debug = true;
long pre_time = 0;
long last_time = 0;

int byteAtPort = 0;

// MTD415T string test init
// init first setting if temperature module
boolean TEMPERATURE_BOOLEAN = true;
// init read string
String MTD415T_READ_STRING = "";

// VER 0.1.5 init read string error register
String MTD415T_READ_STRING_ERROR = "";

// PROGRAM
String TEMPERATURE_SET = "T20000\n";
String TEMPERATURE_GET = "Te?\n";
String P_SET = "P1000\n";
String P_GET = "";

String TEMPERATURE_SET_READ = "T?";
String TEMPERATURE_READ = "Te?";

String message_str = "";
String readStr = "";

// T40 init ADC
double value = 0;
double value2 = 0;
long time_start = 0;

ADC::Sync_result result;

unsigned long MAIN_COUNTER = 0;

// TODO delete temporary debug var
boolean DBG_TEMP = false;
String my_string = "";
String read_message_TEMP = "";

/*************************** LOOP ***************************/
void loop()
{
  // ----------------------------------------------------------
  // READ enable pin and set the control status boolean
  // ----------------------------------------------------------
  int read_enable_pin = 0;
  read_enable_pin = digitalRead(ENABLE_PIN);
  // LOW = enable temperarture control
  if (read_enable_pin == 0) {
    // set boolean
    CTRL_SWITCH = true;
  }
  // HIGH = disable temperature control
  if (read_enable_pin == 1) {
    // set boolean
    CTRL_SWITCH = false;
  }

  // ----------------------------------------------------------
  // READ the MTD415T STATUS PIN
  // only if the temperature control is active and the sweep is moving
  // ----------------------------------------------------------
  // set read status tec variable
  int read_status_tec = 0;
  read_status_tec = digitalRead(STATUS_TEC);

  // ----------------------------------------------------------
  // TEMPERATURE CONTROL ACTIVE CHECK and ROUTINE
  // ----------------------------------------------------------
  if (CTRL_SWITCH == true) {
    // HIGH status = OK, temperature setpoint ok
    if (read_status_tec == 1) {
      // Status Signal High = temperature within defined temperature window
      RGB_color(0, 142, 192);
      _STATUS_CONTROL = 2;

      // VER 0.1.5 send temperature amd register status request 
      // also in status: temperatue control active, temperature setpoint ok 
      
      // SEND TEMPERATURE COMMAND MTD415T
      // -----------------------------------------------------
      Serial1.println(TEMPERATURE_GET);
      delay(10);
      /////////////////////////////////////////////////////////////////////////////
      // READ STRING at UART1 SERIAL
      if (Serial1.available()) {
        // read message from MTD415T
        MTD415T_READ_STRING = Serial1.readStringUntil('\n');
        // DEBUG
        // Serial.print("DEBUG MTD415T_READ_STRING "); Serial.println(MTD415T_READ_STRING);
      }
      /////////////////////////////////////////////////////////////////////////////

      // SEND ERROR CONTROL COMMAND MTD415T
      // -----------------------------------------------------
      // TODO check the way the message is read from MTD415T
      // as for temperature above
      Serial_1_Flush();
      Serial1.println("E?");
      delay(10);
      /////////////////////////////////////////////////////////////////////////////
      // READ STRING at UART1 SERIAL
      // read message from MTD415T
      // TODO check if the string is null before
      MTD415T_READ_STRING_ERROR = Serial1.readStringUntil('\n');
      // DEBUG
      // Serial.print("DEBUG MTD415T_READ_STRING_ERROR "); Serial.println(MTD415T_READ_STRING_ERROR);
      /////////////////////////////////////////////////////////////////////////////
      delay(10);

    }
    // LOW status = Temperature outside programmed temperature window or an error occurred
    else if (read_status_tec == 0) {
      // clear the serial
      Serial1.clear();
      delay(10);
      // check the current
      Serial1.println("A?");
      int actual_TEC_current = 0;
      // Serial1.clear();
      delay(10);
      // read the actual temperature current
      if (Serial1.available()) {
        actual_TEC_current = Serial1.readStringUntil('\n').toInt();
        // DEBUG
        // Serial.print("DEBUG ACTUAL TEC CURRENT "); Serial.println(actual_TEC_current );
      }
      delay(10);
      // clear the serial
      Serial1.clear();

      // SEND TEMPERATURE COMMAND MTD415T
      // -----------------------------------------------------
      Serial1.println(TEMPERATURE_GET);
      delay(10);
      /////////////////////////////////////////////////////////////////////////////
      // READ STRING at UART1 SERIAL
      if (Serial1.available()) {
        // read message from MTD415T
        MTD415T_READ_STRING = Serial1.readStringUntil('\n');
        // DEBUG
        // Serial.print("DEBUG MTD415T_READ_STRING "); Serial.println(MTD415T_READ_STRING);
      }
      /////////////////////////////////////////////////////////////////////////////

      // SEND ERROR CONTROL COMMAND MTD415T
      // -----------------------------------------------------
      // TODO check the way the message is read from MTD415T
      // as for temperature above
      Serial_1_Flush();
      // send error
      Serial1.println("E?");
      delay(10);
      /////////////////////////////////////////////////////////////////////////////
      // READ STRING at UART1 SERIAL
      // read message from MTD415T
      // TODO check if the string is null before
      MTD415T_READ_STRING_ERROR = Serial1.readStringUntil('\n');
      // DEBUG
      // Serial.print("DEBUG MTD415T_READ_STRING_ERROR "); Serial.println(MTD415T_READ_STRING_ERROR);
      /////////////////////////////////////////////////////////////////////////////
      delay(10);

      // -----------------------------------------------------
      // TODO ask for the temperature again ?
      // -----------------------------------------------------

      // -----------------------------------------------
      // CHECK THE STATUS OF THE TEC MODULE
      // -----------------------------------------------

      // if the current is not zero the TEC status is OK
      //      if  (actual_TEC_current != 0) {
      //        // You don't have to put on the red light
      //        RGB_color(255, 125, 10);
      //        _STATUS_CONTROL = 1;
      //      }
      //      // if the current is not zero the TEC status is ERROR
      //      else if (actual_TEC_current == 0) {
      //        // You HAVE to put on the red light
      //        RGB_color(255, 0, 0);
      //        // status contrl error
      //        _STATUS_CONTROL = -1;
      //      }

      // if the error message is zero TEC status is OK
      if (MTD415T_READ_STRING_ERROR.toInt() == 0) {
        // You don't have to put on the red light
        RGB_color(255, 125, 10);
        _STATUS_CONTROL = 1;
      }
      // if the error message is not zero the TEC status is ERROR
      else if (MTD415T_READ_STRING_ERROR.toInt() != 0) {
        // You HAVE to put on the red light
        RGB_color(255, 0, 0);
        // status contrl error
        _STATUS_CONTROL = -1;
      }
    }
  }

  // VER 0.1.5
  // ----------------------------------------------------------
  // TEMPERATURE CONTROL NOT ACTIVE CHECK THE ERROR REGISTER
  // ----------------------------------------------------------
  else if (CTRL_SWITCH == false) {

    // SEND TEMPERATURE COMMAND MTD415T
    // -----------------------------------------------------
    Serial1.println(TEMPERATURE_GET);
    delay(10);
    /////////////////////////////////////////////////////////////////////////////
    // READ STRING at UART1 SERIAL
    if (Serial1.available()) {
      // read message from MTD415T
      MTD415T_READ_STRING = Serial1.readStringUntil('\n');
      // DEBUG
      // Serial.print("DEBUG MTD415T_READ_STRING "); Serial.println(MTD415T_READ_STRING);
    }
    /////////////////////////////////////////////////////////////////////////////

    // SEND ERROR CONTROL COMMAND MTD415T
    // -----------------------------------------------------
    // TODO check the way the message is read from MTD415T
    // as for temperature above
    Serial_1_Flush();
    Serial1.println("E?");
    delay(10);
    /////////////////////////////////////////////////////////////////////////////
    // READ STRING at UART1 SERIAL
    // read message from MTD415T
    // TODO check if the string is null before
    MTD415T_READ_STRING_ERROR = Serial1.readStringUntil('\n');
    // DEBUG
    // Serial.print("DEBUG MTD415T_READ_STRING_ERROR "); Serial.println(MTD415T_READ_STRING_ERROR);
    /////////////////////////////////////////////////////////////////////////////
    delay(10);
  }

  // ----------------------------------------------
  // READ BYTE at SERIAL PORT
  // ----------------------------------------------
  if ( (byteAtPort = Serial.available()) > 0 ) {

    // TODO
    // reset the case switch variable
    // message = 0;

    // read string message at serial port
    message_str = Serial.readStringUntil('\n');
    // convert string to byte artay
    char buf[byteAtPort];
    message_str.toCharArray(buf, sizeof(buf));

    // DECODE MESSAGE at SERIAL PORT check first byte
    // list of char decoding message
    // 'T', 'C', 'P', 'I', 'D', 'X', 'A', 'L', 'E'
    // ----------------------------------------------

    // TEMPERATURE SETTING
    // ----------------------------------------------
    if (buf[0] == 'T') {
      // send message to Peltier Module
      Serial1.println(message_str);
      // set temperature
      if (message_str == TEMPERATURE_SET_READ) {
        Serial.println("reading the set temperature");
        // Serial.println(MTD415T_READ_STRING);
        Serial.println(Serial1.readStringUntil('\n'));
      }
      // read temperature
      else if (message_str == TEMPERATURE_READ) {
        Serial.println("reading the actual temperature");
        // Serial.println(MTD415T_READ_STRING);
        Serial.println(Serial1.readStringUntil('\n'));
      }
      else {
        Serial1.readStringUntil('\n');
      }
    }

    // PID SETTING
    // ----------------------------------------------
    // cycling time
    else if ( buf[0] == 'C' ) {
      // send message to Peltier Module
      Serial1.println(message_str);
      // read message
      read_message_TEMP = Serial1.readStringUntil('\n');
      if (DBG_TEMP) Serial.println(read_message_TEMP );
      if ( buf[1] == '?') Serial.println(read_message_TEMP );
    }
    // P Share
    else if ( buf[0] == 'P' ) {
      // send message to Peltier Module
      Serial1.println(message_str);
      // read message
      read_message_TEMP = Serial1.readStringUntil('\n');
      if (DBG_TEMP) Serial.println(read_message_TEMP );
      if ( buf[1] == '?') Serial.println(read_message_TEMP );
    }
    // I Share
    else if ( buf[0] == 'I' ) {
      // send message to Peltier Module
      Serial1.println(message_str);
      // read message
      read_message_TEMP = Serial1.readStringUntil('\n');
      if (DBG_TEMP) Serial.println(read_message_TEMP );
      if ( buf[1] == '?') Serial.println(read_message_TEMP );
    }
    // D Share
    else if ( buf[0]  == 'D' ) {
      // send message to Peltier Module
      Serial1.println(message_str);
      // read message
      read_message_TEMP = Serial1.readStringUntil('\n');
      if (DBG_TEMP) Serial.println(read_message_TEMP );
      if ( buf[1] == '?') Serial.println(read_message_TEMP );
    }

    // TURN TEC ON/OFF command
    // TURN ON
    else if (buf[0]  == 'X' ) {
      // Serial.println("TURN THE TEC ...");
      if ( buf[1] == '1') {
        // ENABLE  the TEC default (LOW active)
        digitalWrite(ENABLE_PIN, LOW);
        // set boolean control true
        CTRL_SWITCH = true;
        // change led color
        RGB_color(0, 142, 192);
        // VER 0.1.5 turn Fan ON
        analogWrite(FAN_PIN, 255);

      }
      // TURN OFF
      if ( buf[1] == '0') {
        // DISABLE the TEC default (LOW active)
        digitalWrite(ENABLE_PIN, HIGH);
        // set boolean control false
        CTRL_SWITCH = false;
        // VER 0.1.5 turn Fan OFF
        analogWrite(FAN_PIN, 0);

        // not in measure mode
        if (message == 0) {
          // turn white, inactive
          RGB_color(255, 255, 255);
        }
        // measure mode
        else if (message == 1) {
          // turn yellow
          RGB_color(255, 255, 0);
        }
      }
    }

    // VER 0.1.4
    // Reads the actual TEC current in mA
    else if (buf[0]  == 'A' ) {
      // long _time_pre = micros();
      Serial1.println("A?");
      delay(10);
      // echo write what you read
      Serial.println(Serial1.readStringUntil('\n'));
      // Serial.println ((micros() - _time_pre));
    }

    // Set the TEC current limit in mA (value range x: 200 to 1500 [mA])
    else if (buf[0]  == 'L' ) {
      // send message to Peltier Module
      Serial1.println(message_str);
      // read message
      read_message_TEMP = Serial1.readStringUntil('\n');
    }

    // VER 0.1.4
    // READ the current firmware version
    // character 'F'
    else if (buf[0] == 'F') {
      Serial.println(FW_VERSION);

      // VER 0.1.5a
      blink_a();
      
    }

    // VER 0.1.5c
    // STOP an ongoing sweep. Reaching this branch means there is no sweep to
    // stop -- the one in progress is polled inside its own loop -- so there is
    // nothing to do here.
    // ⚠️ The branch is worth having all the same: without it 'Q' falls through
    // to the sweep parser below, where atol("Q") is 0 and freq_start is
    // silently overwritten. It does NOT start a scan -- message is latched only
    // after the THIRD field, so a single letter never begins a sweep, and every
    // real sweep command re-sends all three. That is the difference from
    // openQCM Q-1, whose parser did latch and whose 'F' really could set the
    // board off from 0 Hz. Verified on hardware 2026-09-01: a 0.1.5a board,
    // which has no branch for 'S', answers nothing and keeps working.
    else if (buf[0] == 'Q') {
      // no-op
    }

    // VER 0.1.5b
    // READ the machine identification number from EEPROM
    // character 'S'  ->  SSNN (e.g. 1920), or NO_SERIAL
    else if (buf[0] == 'S') {
      if (EEPROM.read(ADDR_MAGIC) == MAGIC_BYTE) {
        byte series = EEPROM.read(ADDR_SERIES);
        uint16_t unit = ((uint16_t)EEPROM.read(ADDR_SERIAL_HIGH) << 8)
                      | EEPROM.read(ADDR_SERIAL_LOW);
        char snBuf[16];
        // one compact integer, no separator: the format is the specification's
        sprintf(snBuf, "%u%02u", series, unit);
        Serial.println(snBuf);
      } else {
        // never invent a number for an unprogrammed board
        Serial.println("NO_SERIAL");
      }
    }

    // VER 0.1.5
    // Reads the error register
    else if (buf[0]  == 'E' ) {
      // flush serial1
      Serial_1_Flush();
      // send command
      Serial1.println("E?");
      delay(10);
      // echo write what you read
      Serial.println(Serial1.readStringUntil('\n'));
    }

    // GET SWEEP FREQUENCY PARAMETERS
    // ----------------------------------------------
    else {
      // init
      char *p = buf;
      char *str;
      int nn = 0;

      // DECODE MESSAGE
      while ((str = strtok_r(p, ";", &p)) != NULL) {
        // frequency start
        if (nn == 0) {
          freq_start = atol(str);
          nn = 1;
        }
        // frequency stop
        else if (nn == 1) {
          freq_stop = atol(str);
          nn = 2;
        }
        // frequency step
        else if (nn == 2) {
          freq_step = atol(str);
          nn = 0;
          message = 1;
        }
      }
    }

    // VER 0.1.5 TODO
    // check if message is not decoded
    // Serial.println(message_str);

    // DUMMY DO NOTHING
    if (message == 0) {
      // nothing to do here, a dummy state
    }

    // START FREQUENCY SWEEP LOOP
    // ----------------------------------------------
    if (message == 1) {
      // start sweep
      long count = 0;
      pre_time = millis();
      // start sweep cycle measurement
      for (count = freq_start; count <= freq_stop; count = count + freq_step)
      {
        // set AD9851 DDS current frequency
        SetFreq(count);

        // ADC measure and averaging
        if (AVERAGING_BOOL == true) {
          // VER 0.1.5d the sums start from zero at every point: before this they
          // were never reset, and each point carried 1/500 of the one before
          value = 0;
          value2 = 0;
          for (int i = 0; i < AVERAGE_SAMPLE; i++) {
            result = adc->readSynchronizedContinuous();
            value += (uint16_t)result.result_adc0;
            value2 += (uint16_t)result.result_adc1;
          }
          // averaging (cast to double)
          value2 = 1.0 * value2 / AVERAGE_SAMPLE;
          value = 1.0 * value / AVERAGE_SAMPLE;

          // serial print data bit-amplitude and bit-phase values
          Serial.print(value);
          Serial.print(";");
          Serial.print(value2);
          Serial.println();
        }

        // VER 0.1.5c the host can end a sweep in progress
        // ⚠️ Polled at the END of an iteration, so the break can never land in
        // the middle of a printed line: whoever is listening always sees whole
        // lines. Only the 'Q' line is consumed -- any other character is left
        // where it is, for the parser at the top of loop().
        if (Serial.available() > 0 && Serial.peek() == 'Q') {
          while (Serial.available() > 0 && Serial.read() != '\n') { }
          break;
        }
      }

      // SEND TEMPERATURE COMMAND MTD415T
      // -----------------------------------------------------
      Serial1.println(TEMPERATURE_GET);

      /////////////////////////////////////////////////////////////////////////////
      // READ STRING at UART1 SERIAL
      if (Serial1.available()) {
        // read message from MTD415T
        MTD415T_READ_STRING = Serial1.readStringUntil('\n');
        // Serial.print("DEBUG MTD415T_READ_STRING "); Serial.println(MTD415T_READ_STRING);
      }
      /////////////////////////////////////////////////////////////////////////////

      // CHECK if TEMPERATURE CTRL is ACTIVE
      // NO temperature ctrl
      if (CTRL_SWITCH == false) {

        // we're all live in a yellow submarine
        // color yellow
        RGB_color(255, 255, 0);

        // print thermistor temperature
        Serial.print(MTD415T_READ_STRING.toFloat() / 1000.0);
        Serial.print(";");

        // VER 0.1.4
        // print TEC status boolean control variable
        Serial.print(0);
        // semicolon
        Serial.print(";");

        // VER 0.1.5 print the value of the error message
        Serial.print(MTD415T_READ_STRING_ERROR.toInt());
        Serial.print(";");

        // print termination char EOM
        Serial.print("s");
      }

      // OK temperature ctrl
      else if (CTRL_SWITCH == true) {
        // print thermistor temperature
        Serial.print(MTD415T_READ_STRING.toFloat() / 1000.0);
        Serial.print(";");

        // READ STATUS TEC PIN
        if (digitalRead(STATUS_TEC) == 1) {
          // Status Signal (High = temperature within defined temperature window
          RGB_color(0, 142, 192);
          // VER 0.1.4
          // print TEC status boolean control variable
          Serial.print(_STATUS_CONTROL);
          // semicolon
          Serial.print(";");

        }

        // Low = Temperature outside programmed temperature window or an ERROR occurred
        else if (digitalRead(STATUS_TEC) == 0) {

          // TODO the test control status variable can switch to 1 randomly
          if (_STATUS_CONTROL == 1)  RGB_color(255, 125, 10);
          if (_STATUS_CONTROL == -1) RGB_color(255, 0, 0);

          // VER 0.1.4
          // print TEC status boolean control variable
          // check the current outide the loop
          Serial.print(_STATUS_CONTROL);
          // semicolon
          Serial.print(";");
        }

        // VER 0.1.5 print the value of the error message
        Serial.print(MTD415T_READ_STRING_ERROR.toInt());
        Serial.print(";");

        // print termination char EOM
        Serial.print("s");
      }

      // check time elapsed
      // Serial.println(millis()-pre_time);
      // Serial.println();

      // TODO
      // VER 0.1.3
      // reset the case switch variable
      message = 0;
    }
  }
}
