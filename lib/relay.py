"""
Module to handle sending commands to the power relay.
"""
import subprocess
import time
import RPi.GPIO as GPIO

DEFAULT_RELAY_TYPE = "always_off"
DEFAULT_GPIO_PIN = 18


class PowerRelay(object):
    """
    Class that controls an AC/DC control relay

    Attributes:
    name: Relay name (IE - Heater, Light, etc.
    GPIO_PIN: BCM GPIO PIN on rasperry pi that
    the AC/D control relay is plugged into
    """

    def __init__(self, name, GPIO_PIN, relay_type=DEFAULT_RELAY_TYPE):
        """
        Return a relay object whose name is  *name*.
        """
        self.name = name
        self.gpio_pin = GPIO_PIN
        self.type = relay_type
        # setup GPIO Pins
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(GPIO_PIN, GPIO.OUT)

    def switch_high(self):
        """
        Sets the GPIO pin to HIGH
        """
        try:
            GPIO.output(self.gpio_pin, GPIO.HIGH)
            time.sleep(3)
        except:
            return False
        return True

    def switch_low(self):
        """
        Sets the GPIO pin to LOW
        """
        try:
            GPIO.output(self.gpio_pin, GPIO.LOW)
            time.sleep(3)
        except:
            return False

        return True

    def get_status(self):
        """
        return current status of switch, 0 or 1
        """
        try:
            read_process = subprocess.Popen(["gpio -g read "
                                             + str(self.gpio_pin)],
                                            shell=True,
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
            message = read_process.communicate(input)
            return message[0].rstrip()
        except:
            return False


##############
# UNIT TESTS #
##############


def test_default():
    '''
    Test that the default is off.
    '''
    power_relay = PowerRelay("Heater", DEFAULT_GPIO_PIN)
    assert power_relay.get_status == 0


def test_on():
    '''
    Test that it can be turned on.
    '''
    power_relay = PowerRelay("Heater", DEFAULT_GPIO_PIN)
    power_relay.switch_high()
    assert power_relay.get_status == 1


def test_off():
    '''
    Test that it can be turned off.
    '''
    power_relay = PowerRelay("Heater", DEFAULT_GPIO_PIN)
    power_relay.switch_high()
    power_relay.switch_low()
    assert power_relay.get_status == 1


if __name__ == '__main__':
    import doctest

    print "Starting tests."

    doctest.testmod()

    print "Tests finished"

    TEST_RELAY = PowerRelay("Heater", DEFAULT_GPIO_PIN)
    TEST_RELAY.switch_high()
    time.sleep(10)
    TEST_RELAY.switch_low()
