""" Module to control a Relay by SMS """
import time
import subprocess
import Queue
from multiprocessing import Queue as MPQueue
from multiprocessing import Process
import serial  # Requires "pyserial"
import CommandResponse
import lib.gas_sensor as gas_sensor
import lib.fona as Fona
from lib.relay import PowerRelay
import lib.temp_probe as temp_probe


OFF = "Off"
ON = "On"
MAX_TIME = "MAX_TIME"


class RelayController(object):
    """ Class to control a power relay based on SMS commands. """

    def __clear_existing_messages__(self):
        """ Clear all of the existing messages off tdhe SIM card.
        Send a message if we did. """
        # clear out all the text messages currently stored on the SIM card.
        # We don't want old messages being processed
        # dont send out a confirmation to these numbers because we are
        # just deleting them and not processing them
        num_deleted = self.fona.delete_messages(False)
        if num_deleted > 0:
            for phone_number in self.configuration.allowed_phone_numbers:
                self.fona.send_message(phone_number,
                                       "Old or unprocessed message(s) found on SIM Card."
                                       + " Deleting...")
            self.log_info_message(
                str(num_deleted) + " old message cleared from SIM Card")

    def __start_gas_sensor__(self):
        """ Starts the gas sensor. Returns TRUE if gas is detected.
        Sends an alert if gas is detected. """

        initialization_message = ""
        try:
            self.mq2_sensor = gas_sensor.GasSensor()
        except:
            self.mq2_sensor = None

        is_detected = self.is_gas_detected()

        if self.configuration.is_mq2_enabled:
            initialization_message += "MQ2 sensor detected and enabled."

            if is_detected:
                initialization_message += " GAS DETECTED!"
        else:
            initialization_message += "Starting without MQ2 enabled."

        self.send_message_to_all_numbers(initialization_message)

        return is_detected

    def __init__(self, configuration, logger):
        """ Initialize the object. """
        self.configuration = configuration
        self.logger = logger
        self.last_number = None
        serial_connection = self.initialize_modem()
        if serial_connection is None:
            print "Nope"
            exit()

        self.fona = Fona.Fona("fona", serial_connection,
                              self.configuration.allowed_phone_numbers)

        self.mq2_sensor = None
        if self.configuration.is_temp_probe_enabled:
            temp_message = "Temp sensor enabled and reporting " + \
                str(temp_probe.read_sensors()[0]) + "F"
            self.send_message_to_all_numbers(temp_message)

        # create heater relay instance
        self.heater_relay = PowerRelay(
            "heater_relay", configuration.heater_gpio_pin)
        self.heater_queue = MPQueue()

        # create queue to hold heater timer.
        self.gas_sensor_queue = self.start_monitoring_gas_sensor()

        self.shutoff_timer_process = Process(target=self.start_heater_shutoff_timer,
                                             args=())

        if self.fona is None:
            self.log_warning_message("Uable to initialize, quiting.")
            exit()

        # make sure and turn heater off
        self.heater_relay.switch_low()
        self.log_info_message("Starting SMS monitoring and heater service")
        self.send_message_to_all_numbers(
            "piWarmer powered on. Initializing. Wait to send messages...")
        self.__clear_existing_messages__()
        self.__start_gas_sensor__()

        self.log_info_message("Begin monitoring for SMS messages")
        self.send_message_to_all_numbers(
            "piWarmer monitoring started. Ok to send messages now."
            + " Text ON,OFF,STATUS or SHUTDOWN to control heater")

    def send_message_to_all_numbers(self, message):
        """ Sends a message to ALL of the numbers in the configuration. """
        if message is None:
            return False

        self.log_info_message("Sending messages to all: " + message)

        for phone_number in self.configuration.allowed_phone_numbers:
            self.fona.send_message(phone_number, message)

        if (self.configuration.push_notification_number
                not in self.configuration.allowed_phone_numbers):
            self.fona.send_message(
                self.configuration.push_notification_number, message)

        return True

    def log_info_message(self, message_to_log):
        """ Log and print at Info level """
        print message_to_log
        self.logger.info(message_to_log)

        return message_to_log

    def log_warning_message(self, message_to_log):
        """ Log and print at Warning level """
        print message_to_log
        self.logger.warning(message_to_log)

        return message_to_log

    def push_notification_number(self):
        """
        Returns a phone number to return command responses back to.
        """
        if self.last_number is not None:
            return self.last_number

        if self.configuration.push_notification_number is not None:
            return self.configuration.push_notification_number

        if self.configuration.push_notification_number is not None:
            return self.configuration.push_notification_number[0]

        return None

    def get_mq2_status(self):
        """ Returns the state of the gas detector """

        if self.mq2_sensor is not None and self.mq2_sensor.update():
            return ON

        return OFF

    def is_gas_detected(self):
        """ Returns True if gas is detected. """
        if self.configuration.is_mq2_enabled and self.get_mq2_status() == ON:
            return True

        return False

    def is_allowed_phone_number(self, phone_number):
        """ Returns True if the phone number is allowed in the whitelist. """

        if phone_number is None:
            return False

        return phone_number in self.configuration.allowed_phone_numbers

    def handle_on_request(self, status, phone_number):
        """ Handle a request to turn on. """

        if phone_number is None:
            return CommandResponse.CommandResponse(CommandResponse.ERROR, "Phone number was empty.")

        self.log_info_message("Received ON request from " + phone_number)

        if status == "1":
            return CommandResponse.CommandResponse(CommandResponse.NOOP,
                                                   "Heater is already ON")

        if self.is_gas_detected():
            return CommandResponse.CommandResponse(CommandResponse.HEATER_OFF,
                                                   "Gas warning. Not turning heater on")

        return CommandResponse.CommandResponse(CommandResponse.HEATER_ON,
                                               "Heater turning on for "
                                               + str(self.configuration.max_minutes_to_run)
                                               + " minutes.")

    def handle_off_request(self, status, phone_number):
        """ Handle a request to turn off. """

        self.log_info_message("Received OFF request from " + phone_number)

        if status == "1":
            try:
                self.heater_relay.switch_low()
                self.heater_queue.put(OFF)
                return CommandResponse.CommandResponse(CommandResponse.HEATER_OFF,
                                                       "Heater turned OFF")
            except:
                return CommandResponse.CommandResponse(CommandResponse.ERROR,
                                                       "Issue turning Heater OFF")

        return CommandResponse.CommandResponse(CommandResponse.NOOP,
                                               "Heater is already OFF")

    def handle_status_request(self, status, phone_number):
        """ Handle a status request. """
        self.log_info_message(
            "Received STATUS request from " + phone_number)

        if status == "1":
            message_response = "Heater is ON"
        elif status == "0":
            message_response = "Heater is OFF"

        if self.is_gas_detected():
            message_response += ". GAS DETECTED"

        # $TODO - Add GAS & TEMP status into response
        return CommandResponse.CommandResponse(CommandResponse.STATUS, message_response)

    def get_command_response(self, message, status, phone_number):
        """ returns a command response based on the message. """
        if "on" in message:
            return self.handle_on_request(status, phone_number)
        elif "off" in message:
            return self.handle_off_request(status, phone_number)
        elif "status" in message:
            return self.handle_status_request(status, phone_number)
        elif "shutdown" in message:
            return CommandResponse.CommandResponse(CommandResponse.PI_WARMER_OFF,
                                                   "Received SHUTDOWN request from " + phone_number)

        return CommandResponse.CommandResponse(CommandResponse.HELP,
                                               "Please text ON,OFF,STATUS or"
                                               + " SHUTDOWN to control heater")

    def execute_command(self, command_response):
        """ Executes the action the controller has determined. """

        # The commands "Help", "Status", and "NoOp"
        # only send responses back to the caller
        # and do not change the heater relay
        # or the Pi
        if command_response.get_command() == CommandResponse.PI_WARMER_OFF:
            try:
                self.shutdown()
            except:
                self.log_warning_message(
                    "Issue shutting down Raspberry Pi")
        elif command_response.get_command() == CommandResponse.HEATER_OFF:
            try:
                self.heater_relay.switch_low()
                self.log_info_message("Heater turned OFF")
                self.heater_queue.put(OFF)
            except:
                self.log_warning_message(
                    "Issue turning off Heater")
        elif command_response.get_command() == CommandResponse.HEATER_ON:
            try:
                self.heater_relay.switch_high()
                self.log_info_message("Heater turned ON")
                self.heater_queue.put(ON)

            except:
                self.log_warning_message(
                    "Issue turning on Heater")

    def process_message(self, message, phone_number=False):
        """ Process a SMS message/command. """

        status = self.heater_relay.get_status()
        message = message.lower()
        self.log_info_message("Processing message:" + message)

        phone_number = Fona.get_cleaned_phone_number(phone_number)

        # check to see if this is an allowed phone number
        if not self.is_allowed_phone_number(phone_number):
            unauth_message = "Received unauthorized SMS from " + phone_number
            self.fona.send_message(
                self.push_notification_number, unauth_message)
            return self.log_warning_message(unauth_message)

        command_response = self.get_command_response(
            message, status, phone_number)
        self.execute_command(command_response)

        if phone_number:
            self.last_number = phone_number

        if phone_number is not None:
            self.fona.send_message(
                phone_number, command_response.get_message())
            self.log_info_message(
                "Sent message: " + command_response.get_message() + " to " + phone_number)
        else:
            self.log_warning_message(
                "Phone number missing, unable to send response:" + command_response.get_message())

        return command_response.get_message()

    def shutdown(self):
        """ Shuts down the Pi """
        self.shutoff_timer_process = subprocess.Popen(["sudo shutdown -P now "
                                                       + str(self.configuration.heater_gpio_pin)],
                                                      shell=True, stdout=subprocess.PIPE,
                                                      stderr=subprocess.STDOUT)

    # for safety, this thread starts a timer for when the heater was turned on
    # and turns it off when reached
    def start_heater_shutoff_timer(self):
        """ Starts a timer to turn off the heater. """
        self.log_info_message("Starting Heater Timer. Max Time is " +
                              str(self.configuration.max_minutes_to_run) + " minutes")
        time.sleep(self.configuration.max_minutes_to_run * 60)
        self.heater_queue.put(MAX_TIME)
        return

    def monitor_gas_sensor(self):
        """ Monitor the Gas Sensors. Sends a warning message if gas is detected. """
        while True:
            detected = self.is_gas_detected()

            # print LED_status
            if detected and self.heater_relay.get_status() == "1":
                # clear the queue if it has a bunch of no warnings in it
                while not self.gas_sensor_queue.empty():
                    self.gas_sensor_queue.get()
                self.gas_sensor_queue.put("gas_warning")
                self.heater_queue.put(OFF)
                self.heater_relay.switch_low()

                self.fona.send_message(
                    self.push_notification_number, "GAS DETECTED")
                time.sleep(60)
            else:
                self.gas_sensor_queue.put("no_warning")
            time.sleep(2)

    def initialize_modem(self, retries=4, seconds_between_retries=10):
        """ Attempts to initialize the modem over the serial port. """

        serial_connection = None

        while retries > 0 and serial_connection is None:
            try:
                print "Opening on " + self.configuration.cell_serial_port

                serial_connection = serial.Serial(
                    self.configuration.cell_serial_port,
                    self.configuration.cell_baud_rate)
            except:
                print "ERROR"
                self.log_info_message(
                    self.log_warning_message(
                        "SERIAL DEVICE NOT LOCATED."
                        + " Try changing /dev/ttyUSB0 to different USB port"
                        + " (like /dev/ttyUSB1) in configuration file or"
                        + " check to make sure device is connected correctly"))

                # wait 60 seconds and check again
                time.sleep(seconds_between_retries)

            retries -= 1

        return serial_connection

    def start_monitoring_gas_sensor(self):
        """ Initializes and enables the MQ2 Gas Sensor """
        if self.configuration.is_mq2_enabled:
            self.log_info_message("MQ2 Gas Sensor enabled")
            # setup MQ2 GPIO PINS
            # create queue to hold MQ2 LED status
            mq2_queue = MPQueue()
            # start sub process to monitor actual MQ2 sensor
            Process(target=self.monitor_gas_sensor, args=()).start()

            self.heater_queue.put(OFF)

            return mq2_queue
        else:
            self.log_info_message("MQ2 Sensor not enabled")

        return None

    def run_pi_warmer(self):
        """ Service loop to run the PiWarmer """
        self.log_info_message('Press Ctrl-C to quit.')
        flag = 0

        while True:
            if self.configuration.is_mq2_enabled and not self.gas_sensor_queue is None:
                try:
                    gas_sensor_status = self.gas_sensor_queue.get_nowait()

                    # print "QUEUE: " + myLEDqstatus
                    if "gas_warning" in gas_sensor_status:
                        if flag == 0:
                            flag = 1
                            self.log_warning_message(
                                "GAS DETECTED.HEATER TURNED OFF")
                            # heater.switchLow()
                            self.fona.send_message(
                                self.push_notification_number(), "Gas Warning. Heater turned OFF")
                            flag = 1
                    if gas_sensor_status == "no_warning":
                        if flag == 1:
                            self.log_warning_message("GAS WARNING CLEARED")
                            self.fona.send_message(
                                self.push_notification_number(),
                                "Gas Warning CLEARED. Send ON message to restart")
                            flag = 0

                except Queue.Empty:
                    pass

            # check the queue to deal with various issues,
            # such as Max heater time and the gas sensor being tripped
            try:
                status_queue = self.heater_queue.get_nowait()

                if ON in status_queue:
                    self.shutoff_timer_process = Process(
                        target=self.start_heater_shutoff_timer, args=())
                    self.shutoff_timer_process.start()
                if OFF in status_queue:
                    self.shutoff_timer_process.terminate()
                if MAX_TIME in status_queue:
                    self.log_info_message(
                        "Max time reached. Heater turned OFF")
                    self.heater_relay.switch_low()
                    self.fona.send_message(
                        self.push_notification_number(),
                        "Heater was turned off due to max time being reached")
            except Queue.Empty:
                pass
            # get messages on SIM Card
            messages = self.fona.get_messages()
            for message in messages:
                response = self.process_message(
                    message.message_text, message.sender_number)
                self.log_info_message(response)


#############
# SELF TEST #
#############
if __name__ == '__main__':
    import doctest
    import logging
    import PiWarmerConfiguration

    print "Starting tests."

    doctest.testmod()
    CONFIG = PiWarmerConfiguration.PiWarmerConfiguration()

    CONTROLLER = RelayController(CONFIG, logging.getLogger("Controller"))

    print "Tests finished"
