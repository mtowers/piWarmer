"""
Module to abstract having a light sensor.
Handy for know if you left the door open or the lights on.
"""

# https://pimylifeup.com/raspberry-pi-light-sensor/
import time
import RPi.GPIO as GPIO

DEFAULT_GPIO_PIN = 7


class LightSensor(object):
    """
    Object to handle the light sensor.
    Uses a charge/discharge timing technique to get
    a value without an ADC.
    """

    def __init__(self, light_sensor_gpio_pin=DEFAULT_GPIO_PIN):
        """
        Creats a new light sensor.
        """

        self.light_sensor_gpio_pin = light_sensor_gpio_pin

    def get_rc_time(self, light_sensor_gpio_pin=DEFAULT_GPIO_PIN):
        """
        Determines how quickly the sensor changes state,
        which in turn correlates to how much light there is.
        """

        count = 0

        # Output on the pin for
        GPIO.setup(light_sensor_gpio_pin, GPIO.OUT)
        GPIO.output(light_sensor_gpio_pin, GPIO.LOW)
        time.sleep(0.1)

        # Change the pin back to input
        GPIO.setup(light_sensor_gpio_pin, GPIO.IN)

        # Count until the pin goes high
        while GPIO.input(light_sensor_gpio_pin) == GPIO.LOW:
            count += 1

        return count


# Catch when script is interrupted, cleanup correctly
if __name__ == '__main__':
    try:
        SENSOR = LightSensor()
        # Main loop
        while True:
            print SENSOR.get_rc_time()
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()
