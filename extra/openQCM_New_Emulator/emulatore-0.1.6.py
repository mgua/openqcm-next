#!/usr/bin/env python3

"""
openQCM NEXT serial device emulator.

Emulates the serial protocol used by:
    software/openQCM/ui/mainWindow.py
    software/openQCM/processors/Serial.py

Serial:
    115200 8N1

The emulator expects to be connected to one side of a virtual
serial port pair.

Example Linux/macOS:

    socat -d -d \
        pty,raw,echo=0,link=/tmp/openqcm_host \
        pty,raw,echo=0,link=/tmp/openqcm_device

Then:

    python qcm_emulator.py --port /tmp/openqcm_device

and configure openQCM NEXT to use:

    /tmp/openqcm_host
"""

import argparse
import math
import threading
import time

import serial


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BAUDRATE = 115200

FIRMWARE_VERSION = "0.1.5c"
BOARD_SERIAL = "1920"

DEFAULT_TEMPERATURE_MILLI_C = 25000

DEFAULT_CYCLING = 50
DEFAULT_P = 500
DEFAULT_I = 50
DEFAULT_D = 300

DEFAULT_TEC_CURRENT = 1.0
DEFAULT_ERROR_REGISTER = 0

# Simulated resonance frequency.
# The application supports 5 MHz and 10 MHz QCMs.
#RESONANCE_FREQUENCY = 10_000_000.0
#RESONANCE_FREQUENCY = 9_500_000.0
RESONANCE_FREQUENCY = 9_996_500.0

# Width of the simulated resonance curve in Hz.
RESONANCE_WIDTH = 1200.0

# ADC-like values used by the firmware protocol.
ADC_CENTER = 1500.0
ADC_AMPLITUDE = 900.0

# Phase signal parameters.
PHASE_CENTER = 1800.0
PHASE_AMPLITUDE = 600.0


class OpenQCMEmulator:

    def __init__(self, port):
        self.port_name = port

        self.ser = serial.Serial(
            port=port,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
            write_timeout=5.0,
        )

        self.running = True
        self.sweeping = False

        self.temperature_milli_c = DEFAULT_TEMPERATURE_MILLI_C

        self.tec_enabled = False
        self.tec_current = DEFAULT_TEC_CURRENT
        self.error_register = DEFAULT_ERROR_REGISTER

        self.cycling = DEFAULT_CYCLING
        self.p_value = DEFAULT_P
        self.i_value = DEFAULT_I
        self.d_value = DEFAULT_D

        self.sweep_thread = None

        self.rx_buffer = b""
        self.old_data = ""

    # ------------------------------------------------------------------
    # Serial helpers
    # ------------------------------------------------------------------

    def send(self, text):
        
        """Send text exactly as a real serial device would."""
        if isinstance(text, str):
            data = text.encode("utf-8")
        else:
            data = text
        
        if data == self.old_data:
            print(".", end='', flush=True)
        else:
            print(f"<<< {data}")
            self.old_data = data
        
        try:
            self.ser.write(data)
        except Exception:
            print("Serial timeout")
            
        #self.ser.flush()
        
        # The real device streams very quickly. We don't need to emulate
        # the exact hardware timing; a tiny delay prevents the emulator
        # from monopolizing the CPU.
        #time.sleep(0.00005)
        time.sleep(len(text) * 10 / 115200)
    
    def send_sweep_cancellami(self, text):
        """Send text exactly as a real serial device would."""
        if isinstance(text, str):
            data = text.encode("utf-8")
        else:
            data = text

        self.ser.write(data)
        self.ser.flush()
        
        if data.endswith(b"s"):
            print(f"<<< EOM: {data!r}")

    # ------------------------------------------------------------------
    # Command processing
    # ------------------------------------------------------------------

    def process_command(self, command):
        command = command.strip()

        if not command:
            return

        print(f">>> {command}")

        # --------------------------------------------------------------
        # Firmware
        # --------------------------------------------------------------

        if command == "F":
            self.send(FIRMWARE_VERSION + "\n")
            return

        # --------------------------------------------------------------
        # Board serial number
        # --------------------------------------------------------------

        if command == "S":
            self.send(BOARD_SERIAL + "\n")
            return

        # --------------------------------------------------------------
        # TEC current
        # --------------------------------------------------------------

        if command == "A":
            self.send(f"{float(self.tec_current):.3f}\n")
            return

        # --------------------------------------------------------------
        # TEC error register
        # --------------------------------------------------------------

        if command == "E":
            self.send(f"{self.error_register}\n")
            return

        # --------------------------------------------------------------
        # Stop sweep
        # --------------------------------------------------------------

        if command == "Q":
            print("Stopping sweep")
            self.sweeping = False
            return

        # --------------------------------------------------------------
        # TEC
        # --------------------------------------------------------------

        if command.startswith("X"):
            try:
                value = int(command[1:])

                self.tec_enabled = bool(value)
                
                if self.tec_enabled:
                    # Restore simulated current when TEC is enabled.
                    if self.tec_current == 0:
                        self.tec_current = DEFAULT_TEC_CURRENT
                else:
                    # TEC disabled -> no current.
                    self.tec_current = 0.0

                print(
                    "TEC:",
                    "ON" if self.tec_enabled else "OFF",
                    "current=",
                    f"{self.tec_current:.3f}"
                )

            except ValueError:
                print("Invalid X command")

            return

        # --------------------------------------------------------------
        # Temperature
        # --------------------------------------------------------------

        if command.startswith("T"):
            try:
                self.temperature_milli_c = int(command[1:])

                print(
                    f"Temperature setpoint = "
                    f"{self.temperature_milli_c / 1000:.3f} °C"
                )

            except ValueError:
                print("Invalid T command")

            return

        # --------------------------------------------------------------
        # PID set
        # --------------------------------------------------------------

        if command.startswith("C") and not command.endswith("?"):
            self._set_integer("C", command[1:])
            return

        if command.startswith("P") and not command.endswith("?"):
            self._set_integer("P", command[1:])
            return

        if command.startswith("I") and not command.endswith("?"):
            self._set_integer("I", command[1:])
            return

        if command.startswith("D") and not command.endswith("?"):
            self._set_integer("D", command[1:])
            return

        # --------------------------------------------------------------
        # PID queries
        # --------------------------------------------------------------

        if command == "C?":
            self.send(f"{self.cycling}\n")
            return

        if command == "P?":
            self.send(f"{self.p_value}\n")
            return

        if command == "I?":
            self.send(f"{self.i_value}\n")
            return

        if command == "D?":
            self.send(f"{self.d_value}\n")
            return

        # --------------------------------------------------------------
        # Frequency sweep
        #
        # Format:
        #
        #     START;STOP;STEP
        #
        # Example:
        #
        #     4988000;5018000;1
        # --------------------------------------------------------------

        if ";" in command:
            self.start_sweep_command(command)
            return

        print(f"Unknown command: {command}")

    def _set_integer(self, key, value):
        try:
            value = int(value)
        except ValueError:
            print(f"Invalid {key} command: {value}")
            return

        if key == "C":
            self.cycling = value

        elif key == "P":
            self.p_value = value

        elif key == "I":
            self.i_value = value

        elif key == "D":
            self.d_value = value

        print(f"{key} = {value}")

    # ------------------------------------------------------------------
    # Sweep
    # ------------------------------------------------------------------

    def start_sweep_command(self, command):
        try:
            start, stop, step = command.split(";")

            start = float(start)
            stop = float(stop)
            step = float(step)

        except ValueError:
            print(f"Invalid sweep command: {command}")
            return

        if step == 0:
            print("Invalid sweep step")
            return

        print(
            f"SWEEP start={start} "
            f"stop={stop} "
            f"step={step}"
        )

        # Avoid running multiple sweeps concurrently.
        if self.sweeping:
            print("Sweep already running")
            return

        self.sweeping = True

        self.sweep_thread = threading.Thread(
            target=self.generate_sweep,
            args=(start, stop, step),
            daemon=True,
        )

        self.sweep_thread.start()

    def generate_sweep(self, start, stop, step):
        """
        Generate the ADC magnitude/phase stream expected by Serial.py.

        Serial.py converts:

            magnitude:
                (ADC * 3.3 / 4096 / 2 - 0.9) / 0.03

            phase:
                (ADC * 3.3 / 4096 / 1.5 - 0.9) / 0.01
        """

        try:
            if step > 0:
                frequency = start

                while (
                    frequency <= stop
                    and self.sweeping
                ):
                    self.send_sample(frequency)

                    #frequency += step
                    frequency += 100                            # SPARO: Ho messo gli step a mano così scrive meno roba (90 scritture contro 19000)

            else:
                frequency = start

                while (
                    frequency >= stop
                    and self.sweeping
                ):
                    self.send_sample(frequency)

                    frequency += step

            if self.sweeping:
                # ------------------------------------------------------
                # Last line expected by Serial.py:
                #
                # temperature ; TEC status ; error register
                #
                # Do NOT put a newline after this line.
                # This matches the parsing logic in Serial.py.
                # ------------------------------------------------------

                status = (
                    f"{self.temperature_milli_c / 1000.0:.3f};"
                    f"{int(self.tec_status())};"
                    f"{self.error_register}"
                )

                # The firmware/application uses the character 's'
                # as end-of-measurement marker.
                self.send(status + ";s")

                print("SWEEP complete")

        finally:
            self.sweeping = False

    def send_sample_old(self, frequency):
        """
        Produce a synthetic resonance curve.

        The magnitude contains a Gaussian-shaped resonance peak.

        The phase has a dispersive shape around resonance.
        """

        delta = frequency - RESONANCE_FREQUENCY

        # Gaussian resonance peak.
        gaussian = math.exp(
            -0.5 * (delta / RESONANCE_WIDTH) ** 2
        )

        # --------------------------------------------------------------
        # Magnitude ADC
        # --------------------------------------------------------------

        magnitude_adc = (
            ADC_CENTER
            + ADC_AMPLITUDE * gaussian
        )

        magnitude_adc = max(
            0,
            min(4095, magnitude_adc)
        )

        # --------------------------------------------------------------
        # Phase ADC
        # --------------------------------------------------------------

        phase_shape = math.tanh(
            delta / RESONANCE_WIDTH
        )

        phase_adc = (
            PHASE_CENTER
            - PHASE_AMPLITUDE * phase_shape
        )

        phase_adc = max(
            0,
            min(4095, phase_adc)
        )

        line = (
            f"{magnitude_adc:.3f};"
            f"{phase_adc:.3f}\n"
        )

        self.send(line)

        # The real device streams very quickly. We don't need to emulate
        # the exact hardware timing; a tiny delay prevents the emulator
        # from monopolizing the CPU.
        #time.sleep(0.00005)
        time.sleep(len(line) * 10 / 115200)
        
    def send_sample(self, frequency):
        """
        Simula una frequenza che parte dalla frequenza passata
        e converge progressivamente verso RESONANCE_FREQUENCY.
        """

        target_frequency = RESONANCE_FREQUENCY

        # Velocità di avvicinamento al target.
        # Più è piccolo, più la stabilizzazione è lenta.
        alpha = 0.05

        # Stato interno della frequenza
        if not hasattr(self, "_current_frequency"):
            self._current_frequency = frequency

        # Avvicinamento progressivo alla frequenza di risonanza
        self._current_frequency += (
            target_frequency - self._current_frequency
        ) * alpha

        frequency = self._current_frequency

        delta = frequency - target_frequency

        # Gaussiana
        gaussian = math.exp(
            -0.5 * (delta / RESONANCE_WIDTH) ** 2
        )

        # Magnitude ADC
        magnitude_adc = (
            ADC_CENTER
            + ADC_AMPLITUDE * gaussian
        )

        magnitude_adc = max(
            0,
            min(4095, magnitude_adc)
        )

        # Phase ADC
        phase_shape = math.tanh(
            delta / RESONANCE_WIDTH
        )

        phase_adc = (
            PHASE_CENTER
            - PHASE_AMPLITUDE * phase_shape
        )

        phase_adc = max(
            0,
            min(4095, phase_adc)
        )

        line = (
            f"{magnitude_adc:.3f};"
            f"{phase_adc:.3f}\n"
        )
        
        self.send(line)

    def tec_status(self):
        """
        Return the TEC status value expected by Serial.py.

        0 = not active
        1 = active
        """

        if not self.tec_enabled:
            return 0

        return 1

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        print()
        print("==============================================")
        print(" openQCM NEXT SERIAL EMULATOR")
        print("==============================================")
        print(f"Port     : {self.port_name}")
        print(f"Baudrate : {BAUDRATE}")
        print(f"Firmware : {FIRMWARE_VERSION}")
        print(f"S/N      : {BOARD_SERIAL}")
        print("==============================================")
        print()

        try:
            while self.running:

                data = self.ser.read(
                    self.ser.in_waiting or 1
                )

                if not data:
                    continue

                self.rx_buffer += data

                # Commands are LF terminated.
                while b"\n" in self.rx_buffer:

                    line, self.rx_buffer = (
                        self.rx_buffer.split(
                            b"\n",
                            1
                        )
                    )

                    try:
                        command = line.decode(
                            "utf-8",
                            errors="replace"
                        )

                    except Exception:
                        continue

                    self.process_command(command)

        except KeyboardInterrupt:
            print("\nStopping emulator...")

        finally:
            self.running = False
            self.sweeping = False

            try:
                self.ser.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="openQCM NEXT serial device emulator"
    )

    parser.add_argument(
        "--port",
        required=True,
        help="Serial port used by the emulator"
    )

    args = parser.parse_args()

    emulator = OpenQCMEmulator(args.port)
    
    emulator.run()


if __name__ == "__main__":
    main()
