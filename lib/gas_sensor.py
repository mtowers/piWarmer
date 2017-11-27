""" Module to help with the gas sensor. """

import time
import smbus

DEFAULT_IC2_BUS = 1
DEFAULT_IC2_ADDRESS = 0x48
DEVICE_REG_MODW1 = 0x00
DEFAULT_CHANNEL_READ_OFFSET = 0x40
DEFAULT_DEVICE_CHANNEL = 0
DEFAULT_TRIGGER_THRESHOLD = 230
DEFAULT_ALL_CLEAR_THRESHOLD = 220


class GasSensor(object):
    """
    Class to help with the gas sensor.
    """
    def __init__(self,
                sensor_trigger_threshold = DEFAULT_TRIGGER_THRESHOLD,
                sensor_all_clear_threshold = DEFAULT_ALL_CLEAR_THRESHOLD):
        print "Starting init"
        self.ic2_bus = smbus.SMBus(DEFAULT_IC2_BUS)
        self.is_gas_detected = False
        self.sensor_trigger_threshold = sensor_trigger_threshold
        self.sensor_all_clear_threshold = sensor_all_clear_threshold

    def read(self):
        """
        Read from the ic2 device.
        """
        self.ic2_bus.write_byte(DEFAULT_IC2_ADDRESS,
                                DEFAULT_CHANNEL_READ_OFFSET)

        return self.ic2_bus.read_byte(DEFAULT_IC2_ADDRESS)

    def update(self):
        """
        Attempts to look for gas.
        """

        current_value = self.read()

        if self.is_gas_detected:
            self.is_gas_detected = current_value <= self.sensor_all_clear_threshold

        self.is_gas_detected |= current_value >= self.sensor_trigger_threshold

        return self.is_gas_detected


if __name__ == '__main__':
    sensor = GasSensor()
    
    while True:
        print str(sensor.read())
        print str(sensor.update())
        time.sleep(1)


