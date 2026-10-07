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
   OPENQCM NEXT - Quartz Crystal Microbalance with dissipation monitoring
   http://openqcm.com/

   =========================================================================
   TEST-BOARD VARIANT  --  NO TEC / TEMPERATURE-CONTROL SECTION
   =========================================================================
   This firmware is for a special openQCM NEXT board built for TESTING that
   DOES NOT mount the temperature-control (TEC) section:
     - NO MTD415T TEC driver (Thorlabs) on UART Serial1
     - NO MCP9808 temperature sensor
     - NO cooling fan / TEC enable / status / control-switch transistor

   Because the MTD415T is absent, this firmware NEVER talks on Serial1.
   In the original firmware every sweep issued blocking Serial1
   readStringUntil('\n') calls that, with the 250 ms serial timeout, would
   stall for ~seconds on a board with no TEC. All of that is removed here.

   The frequency-sweep measurement engine (AD9851 DDS + AD8302 phase
   comparator + Teensy ADC + AD5252 digital pot) is UNCHANGED, so the raw
   amplitude/phase data is identical to the production firmware.

   HOST-SOFTWARE COMPATIBILITY
   ---------------------------
   The host (openQCM NEXT python, Serial.py / Multiscan.py) reads the sweep
   as raw bytes until it sees the EOM char 's', then splits by '\n' and ';'.
   Each data line is:            amplitude;phase
   The final line MUST be:       temperature;status_control;error_register;s
     - temperature       : float, degrees Celsius  (host uses it directly)
     - status_control    : TEC status (0 = not active) -> always 0 here
     - error_register    : MTD415T error bitmask (0 = no error) -> always 0 here
     - s                 : end-of-measurement terminator
   This variant emits exactly that format so no host change is required.

   SIMULATED TEMPERATURE
   ---------------------
   With no sensor on board, the temperature field is SIMULATED: a stable
   ambient baseline with a small, slow, deterministic wobble so the host
   temperature plot looks alive but plausible. See simulated_temperature().
   Optionally the Teensy 4.0 on-die temperature can be reported instead by
   defining USE_INTERNAL_TEMP below.

   --------------------------------------------------------------------------------
   version      0.1.5d-TEST
   date         2026-10-02
   based on     openQCM_Next_py_0.1.5d_teensy.ino (production, with TEC)
   --------------------------------------------------------------------------------

   HISTORY CHANGES
   --------------------------------------------------------------------------------
   version      0.1.5d-TEST
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
   - FW_VERSION goes to 0.1.5d-TEST, and Constants.FW_VERSION moves with it.

   version      0.1.5c-TEST
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
   - FW_VERSION goes to 0.1.5c-TEST, and Constants.FW_VERSION moves with it.

   version      0.1.5b-TEST
   version tag  // VER 0.1.5b
   date         2026-08-31

   MACHINE IDENTIFICATION NUMBER
   - Read the identification number of the board over serial communication
      COMMAND     RESPONSE
      'S'         SSNN, e.g. 1920, or NO_SERIAL when the board has none
     Carried from production unchanged. This variant strips the TEC, not the
     protocol: a host that speaks to a prototype board has to get the same
     answers to the same commands. The number lives in four bytes of Teensy
     EEPROM written once per board by firmware/openQCM_Next_SerialNumber, and
     this firmware only READS it -- if the magic byte is missing it reports
     NO_SERIAL and never invents or writes one.
     EEPROM layout, shared byte for byte with the openQCM Q-1:
        [0] MAGIC 0xA5   [1] SERIES   [2] UNIT HIGH   [3] UNIT LOW  (big-endian)
     Format is SSNN, one compact integer with no separator: series without
     leading zeros, unit always two digits, sprintf("%u%02u", series, unit).
     Series 19 unit 20 is 1920. The older SERIES-NNNN form is obsolete.
   - FW_VERSION goes to 0.1.5b-TEST. ⚠️ It does not match Constants.FW_VERSION
     and is not meant to: the host compares that string exactly, so a prototype
     board raises the firmware-update warning on every connect. It always has.

   version      0.1.5a-TEST
   date         2026-07-21
   - First cut of the no-TEC variant, split from production 0.1.5a.
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
# include "src/ADC/ADC.h"
# include "src/ADC/ADC_util.h"

// --- SIMULATED TEMPERATURE SOURCE ------------------------------------------
// By default the temperature is fully simulated (see simulated_temperature()).
// Uncomment the line below to report the REAL Teensy 4.0 on-die temperature
// instead (still not a fluidic-cell temperature, but a real physical reading).
// #define USE_INTERNAL_TEMP
#ifdef USE_INTERNAL_TEMP
#  include "src/InternalTemperature.h"
#endif

/*************************** DEFINE ***************************/
// potentiometer AD5252 I2C address is 0x2C(44)
#define ADDRESS 0x2C
// potentiometer AD5252 default value
// VER 0.1.5a higher pot value electronic amplifier fixed
#define POT_VALUE 240 // 180
// reference clock
#define REFCLK 125000000

#define AVERAGING   1
#define RESOLUTION 12

// firmware version (test-board variant)
#define FW_VERSION "0.1.5d-TEST"

// --- simulated temperature parameters --------------------------------------
// baseline ambient temperature reported to the host [degrees Celsius]
#define SIM_TEMP_BASE   25.00f
// peak wobble around the baseline [degrees Celsius]
#define SIM_TEMP_AMPL    0.05f
// number of measurements for one full wobble cycle (slow, plausible drift)
#define SIM_TEMP_PERIOD  120


/*************************** VARIABLE DECLARATION ***************************/

// VER 0.1.4 number of samples for averaging ADC
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

// ADC init variable
boolean WAIT = false;
// ADC waiting delay microseconds
int WAIT_DELAY_US = 200;
// ADC averaging
boolean AVERAGING_BOOL = true;

// init sweep param
long freq_start;
long freq_stop;
long freq_step;

// init output ad8302 measurement (cast to double)
double measure_phase = 0;
double measure_mag = 0;

// embedded LED on T40 (used for the version-check blink alert)
const int ledPin = 13;

/*************************** FUNCTION ***************************/

/* AD9851 set frequency function */
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
    digitalWrite(DATA, LOW);
    digitalWrite(WCLK, HIGH);
    digitalWrite(WCLK, LOW);
    pointer2 = pointer2 >> 1;
  }

  digitalWrite(FQ_UD, HIGH);
  digitalWrite(FQ_UD, LOW);
}

// RGB LED function
// RGB light value 0,..., 255
void RGB_color(int red_light_value, int green_light_value, int blue_light_value)
{
  analogWrite(RGB_RED_PIN, 255 - red_light_value);
  analogWrite(RGB_GREEN_PIN, 255 - green_light_value);
  analogWrite(RGB_BLUE_PIN, 255 - blue_light_value);
}

// VER 0.1.5a blink message (visual confirmation of a firmware update / F command)
void blink_a() {
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

// --------------------------------------------------------------------------
// SIMULATED TEMPERATURE
// This test board has no MTD415T and no MCP9808, so there is no real
// temperature to read. We synthesize a stable ambient value with a small,
// slow, deterministic wobble so the host plot is alive but realistic.
// Returns degrees Celsius (the host divides nothing further; it plots it
// directly), exactly as the production firmware reported MTD415T temp/1000.
// --------------------------------------------------------------------------
unsigned long SIM_TEMP_COUNTER = 0;

float simulated_temperature()
{
#ifdef USE_INTERNAL_TEMP
  // report the real Teensy 4.0 on-die temperature instead of a synthetic one
  return InternalTemperature.readTemperatureC();
#else
  // slow sinusoidal wobble around the baseline; advances once per sweep
  float phase = (float)(SIM_TEMP_COUNTER % SIM_TEMP_PERIOD) / (float)SIM_TEMP_PERIOD;
  return SIM_TEMP_BASE + SIM_TEMP_AMPL * sin(phase * 2.0f * PI);
#endif
}


/*************************** SETUP ***************************/
void setup()
{
  // Initialise I2C communication as Master (needed for the AD5252 digital pot)
  Wire.begin();
  // Initialise serial communication with the host, baud rate = 115200
  Serial.begin(115200);
  Serial.setTimeout(250);

  // set potentiometer value
  // Start I2C transmission
  Wire.beginTransmission(ADDRESS);
  // Send instruction for POT channel-0
  Wire.write(0x01);
  // Input resistance value
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
  // TEENSY 4.0 ADC SETTING (unchanged from production firmware)
  // ----------------------------------------------------------

  // T40 init ADC pin
  pinMode(readPin, INPUT);
  pinMode(readPin2, INPUT);

  // ADC0 setting
  adc->setAveraging(AVERAGING);
  adc->setResolution(RESOLUTION);
  adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED);
  adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED);

  // ADC1 setting
  adc->setAveraging(AVERAGING, ADC_1);
  adc->setResolution(RESOLUTION, ADC_1);
  adc->setConversionSpeed(ADC_CONVERSION_SPEED::HIGH_SPEED, ADC_1);
  adc->setSamplingSpeed(ADC_SAMPLING_SPEED::HIGH_SPEED, ADC_1);

  // start adc read synchronized continuous
  adc->startSynchronizedContinuous(readPin, readPin2);

  // ----------------------------------------------------------
  // NO TEC SECTION ON THIS BOARD
  // The MTD415T (Serial1), MCP9808 sensor, fan, enable/status/control
  // switch pins are intentionally NOT initialised or used.
  // ----------------------------------------------------------

  // onboard LED (blink alert)
  pinMode(ledPin, OUTPUT);
  digitalWrite(ledPin, LOW);

  // RGB LED SETUP
  pinMode(RGB_RED_PIN, OUTPUT);
  pinMode(RGB_GREEN_PIN, OUTPUT);
  pinMode(RGB_BLUE_PIN, OUTPUT);

  // idle: white
  RGB_color(255, 255, 255);

  delay(100);
}

/*************************** GLOBAL VARIABLE INIT ***************************/
int message = 0;
long pre_time = 0;
long last_time = 0;

int byteAtPort = 0;

String message_str = "";
String readStr = "";

// T40 init ADC
double value = 0;
double value2 = 0;
long time_start = 0;

ADC::Sync_result result;

/*************************** LOOP ***************************/
void loop()
{
  // ----------------------------------------------
  // READ BYTE at SERIAL PORT
  // ----------------------------------------------
  if ( (byteAtPort = Serial.available()) > 0 ) {

    // read string message at serial port
    message_str = Serial.readStringUntil('\n');
    // convert string to byte array
    char buf[byteAtPort];
    message_str.toCharArray(buf, sizeof(buf));

    // DECODE MESSAGE at SERIAL PORT check first byte
    // ----------------------------------------------
    // This test board has no TEC, so the temperature-control commands
    // (T, C, P, I, D, X, A, L, E) are accepted and answered with benign,
    // no-op responses so the host never blocks waiting for a reply.
    // ----------------------------------------------

    // TEMPERATURE / PID / TEC-LIMIT SETTINGS -> no-op (no TEC hardware)
    if (buf[0] == 'T' || buf[0] == 'C' || buf[0] == 'P' ||
        buf[0] == 'I' || buf[0] == 'D' || buf[0] == 'L') {
      // query variants ("...?") get a benign echo so the host does not hang
      if (buf[1] == '?') {
        Serial.println(0);
      }
    }

    // TURN TEC ON/OFF command -> only drives the status LED here
    else if (buf[0] == 'X') {
      if (buf[1] == '1') {
        // "on" requested: no TEC, just indicate active (blue)
        RGB_color(0, 142, 192);
      }
      if (buf[1] == '0') {
        // "off": white if idle, yellow if measuring
        if (message == 0) RGB_color(255, 255, 255);
        else              RGB_color(255, 255, 0);
      }
    }

    // Reads the actual TEC current -> no TEC, report 0 mA
    else if (buf[0] == 'A') {
      Serial.println(0);
    }

    // Reads the MTD415T error register -> no TEC, report 0 (no error)
    else if (buf[0] == 'E') {
      Serial.println(0);
    }

    // READ the current firmware version
    else if (buf[0] == 'F') {
      Serial.println(FW_VERSION);
      // VER 0.1.5a visual blink alert
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

    // DUMMY DO NOTHING
    if (message == 0) {
      // nothing to do here, a dummy state
    }

    // START FREQUENCY SWEEP LOOP
    // ----------------------------------------------
    if (message == 1) {
      // measuring: yellow
      RGB_color(255, 255, 0);

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

      // ------------------------------------------------------------------
      // END-OF-MEASUREMENT LINE (host expects: temp;status;error;s)
      // ------------------------------------------------------------------
      // advance the simulated-temperature phase once per sweep
      SIM_TEMP_COUNTER++;

      // simulated temperature [degrees Celsius]
      Serial.print(simulated_temperature(), 2);
      Serial.print(";");

      // status_control: no TEC on this board -> 0 (not active)
      Serial.print(0);
      Serial.print(";");

      // error_register: no MTD415T on this board -> 0 (no error)
      Serial.print(0);
      Serial.print(";");

      // print termination char EOM
      Serial.print("s");

      // reset the sweep state variable
      message = 0;
    }
  }
}
