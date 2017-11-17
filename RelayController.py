""" Module to control a Relay by SMS """
import time
import subprocess
import Queue
from multiprocessing import Queue as MPQueue
from multiprocessing import Process
import serial  # Requires "pyserial"
import CommandResponse
import RPi.GPIO as GPIO
from lib.fona import Fona
from lib.relay import PowerRelay


def get_cleaned_phone_number(phone_number_to_clean):
    """ Returns a cleaned version of the phone number... safely. """
    if phone_number_to_clean:
        return phone_number_to_clean.replace('"', '').replace("+", '')

    return None


OFF = "Off"
ON = "On"


class RelayController(object):
    """ Class to control a power relay based on SMS commands. """

    def __clear_existing_messages__(self):
        """ Clear all of the existing messages off tdhe SIM card.
        Send a message if we did. """
        # clear out all the text messages currently stored on the SIM card.
        # We don't want old messages being processed
        # dont send out a confirmation to these numbers because we are
        # just deleting them and not processing them
        num_deleted = self.fona.delete_messages()
        if num_deleted > 0:
            for phone_number in self.configuration.allowed_phone_numbers:
                self.fona.send_message(phone_number,
                                       "Old or unprocessed message(s) found on SIM Card."
                                       + " Deleting...")
            self.log_info_message(
                str(num_deleted) + " old message cleared from SIM Card")

    def ___send_message_to_all_numbers__(self, message):
        """ Sends a message to all phone numbers. """
        for phone_number in self.configuration.allowed_phone_numbers:
            self.fona.send_message(phone_number, message)
            self.log_info_message(message + " sent to " + phone_number)

    def __initialize_gas_sensor__(self):
        """ Initializes the gas sensor. Returns TRUE if gas is detected.
        Sends an alert if gas is detected. """

        initialization_message = ""
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
        # create heater relay instance
        self.heater_relay = PowerRelay(
            "heater_relay", configuration.heater_gpio_pin)
        self.heater_queue = MPQueue()

        # create queue to hold heater timer.
        self.gas_sensor_queue = self.initialize_gas_sensor()

        self.shutoff_timer_process = Process(target=self.start_heater_shutoff_timer,
                                             args=())

        self.serial_connection = self.initialize_modem()

        if self.serial_connection is None:
            self.log_warning_message("Serial Device not connected, quiting.")
            exit()

        self.fona = Fona(name="fona", ser=self.serial_connection,
                         allowednumbers=self.configuration.allowed_phone_numbers)

        # make sure and turn heater off
        self.heater_relay.switch_low()
        self.log_info_message("Starting SMS monitoring and heater service")
        self.send_message_to_all_numbers(
            "piWarmer powered on. Initializing. Wait to send messages...")
        self.__clear_existing_messages__()
        self.__initialize_gas_sensor__()

        self.log_info_message("Begin monitoring for SMS messages")
        self.send_message_to_all_numbers(
            "piWarmer monitoring started. Ok to send messages now."
            + " Text ON,OFF,STATUS or SHUTDOWN to control heater")

    def send_message_to_all_numbers(self, message):
        """ Sends a message to ALL of the numbers in the configuration. """
        if message is None:
            return

        for phone_number in self.configuration.allowed_phone_numbers:
            self.fona.send_message(phone_number, message)

        if (self.configuration.push_notification_number
                not in self.configuration.allowed_phone_numbers):
            self.fona.send_message(
                self.configuration.push_notification_number, message)

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
        """ Returns a phone number to return command responses back to. """
        if self.last_number is not None:
            return self.last_number

        if self.configuration.push_notification_number is not None:
            return self.configuration.push_notification_number

        if self.configuration.push_notification_number is not None:
            return self.configuration.push_notification_number[0]

        return None

    def get_mq2_status(self):
        """ Returns the state of the gas detector """
        input_state = GPIO.input(self.configuration.mq2_gpio_pin)
        if input_state == 1:
            return OFF
        if input_state == 0:
            return "on"

    def is_gas_detected(self):
        """ Returns True if gas is detected. """
        if self.configuration.is_mq2_enabled and self.get_mq2_status() == "on":
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
            return CommandResponse.CommandResponse(False, False, "Phone number was empty.")

        self.log_info_message("Received ON request from " + phone_number)

        if status == "1":
            return CommandResponse.CommandResponse(False,
                                                   False,
                                                   "Heater is already ON")

        if self.is_gas_detected():
            return CommandResponse.CommandResponse(False,
                                                   True,
                                                   "Gas warning. Not turning heater on")

        return CommandResponse.CommandResponse(True, False,
                                               "Heater turning on for "
                                               + str(self.configuration.max_minutes_to_run)
                                               + " minutes.")

    def handle_off_request(self, status, phone_number):
        """ Handle a request to turn off. """

        self.log_info_message("Received OFF request from " + phone_number)

        if status == "1":
            try:
                self.heater_relay.switch_low()
                message_response = "Heater turned OFF"
                self.heater_queue.put(OFF)
            except:
                message_response = self.log_warning_message(
                    "Issue turning Heater OFF")
        else:
            message_response = "Heater is already OFF"

        return message_response

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
        return message_response

    def process_message(self, message, phone_number=False):
        """ Process a SMS message/command. """

        status = self.heater_relay.get_status()
        message = message.lower()
        self.log_info_message("Processing message:" + message)

        message_response = ""
        phone_number = get_cleaned_phone_number(phone_number)

        # check to see if this is an allowed phone number
        if not self.is_allowed_phone_number(phone_number):
            unauth_message = "Received unauthorized SMS from " + phone_number
            self.fona.send_message(
                self.push_notification_number, unauth_message)
            return self.log_warning_message(unauth_message)

        if "on" in message:
            actions = self.handle_on_request(status, phone_number)
            message_response = actions.get_messages()

            if actions.should_power_on():
                try:
                    self.heater_relay.switch_high()
                    self.log_info_message("Heater turned ON")
                    self.heater_queue.put("On")
                    if phone_number:
                        self.last_number = '"+' + phone_number + '"'
                except:
                    message_response = self.log_warning_message(
                        "Issue turning on Heater")
        elif "off" in message:
            message_response = self.handle_off_request(status, phone_number)
        elif "status" in message:
            message_response = self.handle_status_request(status, phone_number)
        elif "shutdown" in message:
            message_response = self.log_info_message(
                "Received SHUTDOWN request from " + phone_number)

            try:
                self.shutdown()
            except:
                message = self.log_warning_message(
                    "Issue shutting down Raspberry Pi")
        else:
            message_response = self.log_info_message(
                "Please text ON,OFF,STATUS or SHUTDOWN to control heater")

        if phone_number is not None:
            self.fona.send_message(phone_number, message_response)
            self.log_info_message(
                "Sent message: " + message_response + " to " + phone_number)

            return message_response
        else:
            self.log_warning_message(
                "Phone number missing, unable to send response:" + message_response)

        return message_response

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
        self.heater_queue.put("max_time")
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

    def initialize_modem(self,
                         timeout=.1,
                         rtscts=0,
                         retries=4,
                         seconds_between_retries=60):
        """ Attempts to initialize the modem over the serial port. """

        serial_connection = None

        while retries > 0 and serial_connection != None:
            try:
                serial_connection = serial.Serial(
                    self.configuration.cell_serial_port,
                    self.configuration.cell_baud_rate, timeout, rtscts)
            except:
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

    def initialize_gas_sensor(self):
        """ Initializes and enables the MQ2 Gas Sensor """
        if self.configuration.is_mq2_enabled:
            self.log_info_message("MQ2 Gas Sensor enabled")
            # setup MQ2 GPIO PINS
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.configuration.mq2_gpio_pin, GPIO.IN)
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

                if "On" in status_queue:
                    self.shutoff_timer_process = Process(
                        target=self.start_heater_shutoff_timer, args=())
                    self.shutoff_timer_process.start()
                if OFF in status_queue:
                    self.shutoff_timer_process.terminate()
                if "max_time" in status_queue:
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
                    message[2], message[1])
                self.log_info_message(response)
