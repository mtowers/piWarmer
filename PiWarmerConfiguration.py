""" Module to abstract and hide configuration. """

from sys import platform
from ConfigParser import SafeConfigParser

# read in configuration settings


def is_local_debug():
    """
    returns True if this should be run as a local debug (Mac or Windows).

    >>> is_local_debug()
    True
    """
    return platform in ["win32", "darwin"]


def get_confile_file_location():
    """
    Get the location of the configuration file.

    >>> get_confile_file_location()
    './piWarmer.config'
    """
    if is_local_debug():
        return './piWarmer.config'

    return '/home/pi/Desktop/piWarmer.config'


class PiWarmerConfiguration(object):
    """ Object to handle configuration of the piWarmer. """

    def get_log_filename(self):
        """ returns the location of the logfile to use. """

        if is_local_debug():
            return self.__config_parser__.get('SETTINGS', 'DEBUGGING_LOGFILE')

        return self.__config_parser__.get('SETTINGS', 'LOGFILE')

    def __init__(self):
        self.__config_parser__ = SafeConfigParser()
        self.__config_parser__.read(get_confile_file_location())
        self.cell_serial_port = self.__config_parser__.get(
            'SETTINGS', 'SERIAL_PORT')
        self.cell_baud_rate = self.__config_parser__.get('SETTINGS', 'BAUDRATE')
        self.heater_gpio_pin = self.__config_parser__.getint(
            'SETTINGS', 'HEATER_GPIO_PIN')
        self.is_mq2_enabled = self.__config_parser__.getboolean('SETTINGS', 'MQ2')
        self.is_temp_probe_enabled = self.__config_parser__.getboolean('SETTINGS', 'TEMP')
        self.mq2_gpio_pin = self.__config_parser__.getint(
            'SETTINGS', 'MQ2_GPIO_PIN')
        self.allowed_phone_numbers = self.__config_parser__.get(
            'SETTINGS', 'ALLOWED_PHONE_NUMBERS')
        self.push_notification_number = self.__config_parser__.get('SETTINGS',
                                                               'PUSH_NOTIFICATION_NUMBER')
        self.allowed_phone_numbers = self.allowed_phone_numbers.split(',')
        self.max_minutes_to_run = self.__config_parser__.getint(
            'SETTINGS', 'MAX_HEATER_TIME')
        self.log_filename = self.get_log_filename()


##################
### UNIT TESTS ###
##################

def test_configuration():
    """ Test that the configuration is valid. """
    assert is_local_debug()
    
    config = PiWarmerConfiguration()

    assert config.allowed_phone_numbers is not None
    assert config.allowed_phone_numbers.count > 0
    assert config.cell_baud_rate == '9600'
    assert config.cell_serial_port is not None
    assert config.heater_gpio_pin is not None
    assert config.heater_gpio_pin >= 1
    assert config.heater_gpio_pin < 32
    assert config.is_mq2_enabled is not None
    assert config.is_temp_probe_enabled is not None
    assert config.log_filename is not None
    assert config.max_minutes_to_run == 60
    assert config.mq2_gpio_pin is not None
    assert config.push_notification_number is not None

if __name__ == '__main__':
    import doctest

    print "Starting tests."

    doctest.testmod()

    print "Tests finished"