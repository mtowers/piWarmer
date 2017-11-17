""" Module to handle sending commands to the power relay. """
import subprocess
import time
import RPi.GPIO as GPIO


class PowerRelay(object):
    """Class that controls an AC/DC control relay

    Attributes:
    name: Relay name (IE - Heater, Light, etc.
    GPIO_PIN: BCM GPIO PIN on rasperry pi that the AC/D control relay is plugged into
    """

    def __init__(self, name, GPIO_PIN, relay_type="always_off"):
        """Return a relay object whose name is  *name*."""
        self.name = name
        self.gpio_pin = GPIO_PIN
        self.type = relay_type
        # setup GPIO Pins
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(GPIO_PIN, GPIO.OUT)

    def switch_high(self):
        """ Sets the GPIO pin to HIGH """
        try:
            GPIO.output(self.gpio_pin, GPIO.HIGH)
            time.sleep(3)
        except:
            return False
        return True

    def switch_low(self):
        """ Sets the GPIO pin to LOW """
        try:
            GPIO.output(self.gpio_pin, GPIO.LOW)
            time.sleep(3)
        except:
            return False

        return True

    def get_status(self):
        """ return current status of switch, 0 or 1 """
        try:
            read_process = subprocess.Popen(["gpio -g read " + str(self.gpio_pin)],
                                            shell=True,
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT)
            message = read_process.communicate(input)
            return message[0].rstrip()
        except:
            return False


'''
heater = relay()
print heater.status()
heater.switch_high()
heater.switch_low()
'''
