"""
Mock package to allow for testing/compilation on a Windows
machine for development.
"""

import sys

BOARD = 1
OUT = 1
IN = 1
HIGH = 1
LOW = 0
BCM = "bcm"

THIS_MODULE = sys.modules[__name__]
THIS_MODULE.setups = {}
THIS_MODULE.io_pins = {}
THIS_MODULE.mode = 0
THIS_MODULE.warnings = False


def setmode(mode_to_set):
    """ Mock for setmode """
    THIS_MODULE.mode = mode_to_set


def setup(key_to_set, value):
    """ Mock for setup """
    THIS_MODULE.setups[key_to_set] = value


def output(pin_to_set, value_of_pin):
    """ Mocks changing the state of a pin """
    THIS_MODULE.io_pins[pin_to_set] = value_of_pin

def input(pin_to_get):
    """ Mocks getting a pin value from the IO board """
    if not pin_to_get in THIS_MODULE.io_pins:
        THIS_MODULE.io_pins[pin_to_get] = 0

    return THIS_MODULE.io_pins[pin_to_get]


def cleanup():
    """ Mocks cleaning up """
    THIS_MODULE.setups = {}
    THIS_MODULE.io_pins = {}


def setwarnings(flag):
    """ Mock for enabling/disabling warnings """
    THIS_MODULE.warnings = flag
