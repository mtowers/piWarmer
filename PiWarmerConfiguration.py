""" Module to abstract and hide configuration. """

from sys import platform
from ConfigParser import SafeConfigParser

# read in configuration settings


def is_local_debug():
    """ returns True if this should be run as a local debug (Mac or Windows). """
    return platform in ["win32", "darwin"]


def get_confile_file_location():
    """ Get the location of the configuration file. """
    if is_local_debug():
        return './piWarmer.config'

    return '/home/pi/Desktop/piWarmer.config'


class PiWarmerConfiguration(object):
    """ Object to handle configuration of the piWarmer. """

    def get_log_filename(self):
        """ returns the location of the logfile to use. """

        if is_local_debug():
            return self.config_parser.get('SETTINGS', 'DEBUGGING_LOGFILE')

        return self.config_parser.get('SETTINGS', 'LOGFILE')

    def __init__(self):
        self.config_parser = SafeConfigParser()
        self.config_parser.read(get_confile_file_location())
        self.cell_serial_port = self.config_parser.get(
            'SETTINGS', 'SERIAL_PORT')
        self.cell_baud_rate = self.config_parser.get('SETTINGS', 'BAUDRATE')
        self.heater_gpio_pin = self.config_parser.getint(
            'SETTINGS', 'HEATER_GPIO_PIN')
        self.is_mq2_enabled = self.config_parser.getboolean('SETTINGS', 'MQ2')
        self.is_temp_probe_enabled = self.config_parser.getboolean('SETTINGS', 'TEMP')
        self.mq2_gpio_pin = self.config_parser.getint(
            'SETTINGS', 'MQ2_GPIO_PIN')
        self.allowed_phone_numbers = self.config_parser.get(
            'SETTINGS', 'ALLOWED_PHONE_NUMBERS')
        self.push_notification_number = self.config_parser.get('SETTINGS',
                                                               'PUSH_NOTIFICATION_NUMBER')
        self.allowed_phone_numbers = self.allowed_phone_numbers.split(',')
        self.max_minutes_to_run = self.config_parser.getint(
            'SETTINGS', 'MAX_HEATER_TIME')
        self.log_filename = self.get_log_filename()
