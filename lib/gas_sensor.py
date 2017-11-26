""" Module to help with the gas sensor. """

import RPi.GPIO as GPIO
import time

DEFAULT_READ_GPIO_PIN = 23
DEFAULT_WRITE_GPIO_PIN = 24


class GasSensor(object):
    """
    Class to help with the gas sensor.
    """
    def __init__(self, read_pin, write_pin):
        print "Starting init"
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        GPIO.setup(write_pin, GPIO.IN)
        GPIO.setup(read_pin, GPIO.IN)

        self.read_pin = read_pin
        self.write_pin = write_pin

    def is_gas_present(self):
        return GPIO.input(self.read_pin)

    def start_alarm(self):
        print GPIO.input(self.write_pin)
        # GPIO.output(self.write_pin, GPIO.HIGH)

    def stop_alarm(self):
        # GPIO.output(self.write_pin, GPIO.LOW)
        self.start_alarm()


if __name__ == '__main__':
    print "Lul, wut?"

    sensor = GasSensor(DEFAULT_READ_GPIO_PIN, DEFAULT_WRITE_GPIO_PIN)

    print "Sensor:" + str(sensor.is_gas_present())

    sensor.start_alarm()
    time.sleep(1)
    sensor.stop_alarm()
