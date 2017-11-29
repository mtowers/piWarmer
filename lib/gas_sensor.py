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
                 sensor_trigger_threshold=DEFAULT_TRIGGER_THRESHOLD,
                 sensor_all_clear_threshold=DEFAULT_ALL_CLEAR_THRESHOLD):
        print "Starting init"
        self.ic2_bus = smbus.SMBus(DEFAULT_IC2_BUS)
        self.is_gas_detected = False
        self.sensor_trigger_threshold = sensor_trigger_threshold
        self.sensor_all_clear_threshold = sensor_all_clear_threshold
        self.current_value = None

    def __read__(self, read_offset=DEFAULT_CHANNEL_READ_OFFSET):
        """
        Read from the ic2 device.
        """
        self.ic2_bus.write_byte(DEFAULT_IC2_ADDRESS,
                                read_offset)

        return self.ic2_bus.read_byte(DEFAULT_IC2_ADDRESS)

    def get_current_level(self):
        """
        Gets the current level from the sensor.
        """
        if self.current_value is None:
            self.update()

        return self.current_value

    def update(self, read_offset=DEFAULT_CHANNEL_READ_OFFSET):
        """
        Attempts to look for gas.
        """

        self.current_value = self.__read__(read_offset)

        if self.is_gas_detected:
            self.is_gas_detected = self.current_value <= self.sensor_all_clear_threshold

        self.is_gas_detected |= self.current_value >= self.sensor_trigger_threshold

        return self.is_gas_detected


if __name__ == '__main__':
    SENSOR = GasSensor()

    while True:
        print "------------"
        OFFSETS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]
        for offset in OFFSETS:
            print str(offset) + ":" + str(SENSOR.__read__(offset))
            # print str(sensor.update(offset))
        time.sleep(1)
