""" Module to abstract and hide configuration. """

from sys import platform
from ConfigParser import SafeConfigParser

# read in configuration settings
class PiWarmerConfiguration(object):
    """ Object to handle configuration of the piWarmer. """
    IS_LOCAL_DEBUG = platform == "win32"

    def get_confile_file_location(self):
        """ Get the location of the configuration file. """
        if  PiWarmerConfiguration.IS_LOCAL_DEBUG:
            return './piWarmer.config'

        return '/home/pi/Desktop/piWarmer.config'

    def __init__(self):
        self.config_parser = SafeConfigParser()
        self.config_parser.read(self.get_confile_file_location())
        self.cell_serial_port = self.config_parser.get('SETTINGS', 'SERIAL_PORT')
        self.cell_baud_rate = self.config_parser.get('SETTINGS', 'BAUDRATE')
        self.heater_gpio_pin = self.config_parser.getint('SETTINGS', 'HEATER_GPIO_PIN')
        self.is_mq2_enabled = self.config_parser.getboolean('SETTINGS', 'MQ2')
        self.mq2_gpio_pin = self.config_parser.getint('SETTINGS', 'MQ2_GPIO_PIN')
        self.allowed_phone_numbers = self.config_parser.get('SETTINGS', 'ALLOWED_PHONE_NUMBERS')
        self.allowed_phone_numbers = self.allowed_phone_numbers.split(',')
        self.max_minutes_to_run = self.config_parser.getint('SETTINGS', 'MAX_HEATER_TIME')
        self.log_filename = self.config_parser.get('SETTINGS', 'LOGFILE')

        if PiWarmerConfiguration.IS_LOCAL_DEBUG:
            self.log_filename = self.config_parser.get('SETTINGS', 'DEBUGGING_LOGFILE')