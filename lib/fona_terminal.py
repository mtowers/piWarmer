"""
Runs an interactive terminal to
allow for experimentation and
diagnosis with the Fona unit.
"""

import lib.fona as fona
import lib.local_debug as local_debug

if __name__ == '__main__':
    import serial

    if local_debug.is_debug():
        SERIAL_CONNECTION = None
    else:
        SERIAL_CONNECTION = serial.Serial('/dev/ttyUSB0', 9600)

    FONA = fona.Fona(None,
                     SERIAL_CONNECTION,
                     fona.DEFAULT_POWER_STATUS_PIN,
                     fona.DEFAULT_RING_INDICATOR_PIN,
                     True)

    if not FONA.is_power_on():
        print "Power is off.."
        exit()

    FONA.simple_terminal()
