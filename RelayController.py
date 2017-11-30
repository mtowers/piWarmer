""" Module to control a Relay by SMS """
# TODO - Wire the status, and button pins
# TODO - Make sure the modem commands are happening only on a single thread
# TODO - Figure out the toggle issue
# TODO - Make it runnable/debuggable under Mac
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
import lib.local_debug as local_debug


OFF = "Off"
ON = "On"
MAX_TIME = "MAX_TIME"
GAS_WARNING = "gas_warning"
GAS_OK = "no_warning"


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
                self.send_message(phone_number,
                                  "Old or unprocessed message(s) found on SIM Card."
                                  + " Deleting...")
            self.log_info_message(
                str(num_deleted) + " old message cleared from SIM Card")

    def __get_gas_sensor_status__(self):
        """
        Returns the status text for the gas sensor.
        """

        if self.mq2_sensor is None or not self.configuration.is_mq2_enabled:
            return "Gas sensor NOT enabled."

        gas_detected = self.mq2_sensor.update()
        status_text = "MQ2 sensor enabled, reading " + \
            str(self.mq2_sensor.current_value)

        if gas_detected:
            status_text += ". DANGER! GAS DETECTED!"
        else:
            status_text += ". Environment OK."

        return status_text

    def __get_temp_probe_status__(self):
        """
        Returns the status of the temperature probe.
        """

        if self.configuration.is_temp_probe_enabled:
            sensor_readings = temp_probe.read_sensors()
            if sensor_readings is None or len(sensor_readings) < 1:
                return "Temp probe enabled, but not found."

            return "Temperature is " + str(sensor_readings[0]) + "F"

        return "Temp probe not enabled."

    def __get_heater_status__(self):
        """
        Returns the status of the heater/relay.
        """
        if self.heater_relay is None:
            return "Relay not detected."

        status_text = "Heater is "

        if self.heater_relay.get_status() == 1:
            status_text += "ON"
        else:
            status_text += "OFF"

        status_text += "."

        return status_text

    def __get_fona_status__(self):
        """
        Returns the status of the Fona.
        ... both the signal and battery ...
        """
        if self.fona is None:
            return "Fona not found."

        cbc = self.fona.get_current_battery_condition()
        signal = self.fona.get_signal_strength()

        status = "Cell signal is " + signal.classify_strength() + ", battery at " + \
            str(cbc.battery_percent) + "%, "

        if cbc.is_battery_ok():
            status += "OK."
        else:
            status += "LOW BATTERY."

        return status

    def __get_status__(self):
        """
        Returns the status of the piWarmer.
        """

        status = self.__get_heater_status__() + "\n" + self.__get_gas_sensor_status__() + "\n"
        status += self.__get_temp_probe_status__() + "\n" + self.__get_fona_status__()

        return status

    def __start_gas_sensor__(self):
        """
        Initializes the gas sensor.
        """

        try:
            return gas_sensor.GasSensor()
        except:
            return None

    def __init__(self, configuration, logger):
        """ Initialize the object. """
        self.ready_for_service = False
        self.configuration = configuration
        self.logger = logger
        self.last_number = None
        self.gas_detected = False
        serial_connection = self.initialize_modem()
        if serial_connection is None and not local_debug.is_debug():
            print "Nope"
            exit()

        self.fona = Fona.Fona("fona", serial_connection,
                              self.configuration.allowed_phone_numbers)

        # create heater relay instance
        self.heater_relay = PowerRelay(
            "heater_relay", configuration.heater_gpio_pin)
        self.heater_queue = MPQueue()

        # create queue to hold heater timer.
        self.mq2_sensor = self.__start_gas_sensor__()

        self.log_info_message("Starting shutoff_timer_process in __init__")
        self.shutoff_timer_process = None
        self.start_heater_timer()

        if self.fona is None and not local_debug.is_debug():
            self.log_warning_message("Uable to initialize, quiting.")
            exit()

        # make sure and turn heater off
        self.heater_relay.switch_low()
        self.log_info_message("Starting SMS monitoring and heater service")
        self.__clear_existing_messages__()

        self.log_info_message("Begin monitoring for SMS messages")
        self.send_message_to_all_numbers("piWarmer monitoring started."
                                         + "\n" + self.__get_help_status__())
        self.send_message_to_all_numbers(self.__get_status__())

        if not self.start_monitoring_gas_sensor():
            gas_disabled = "Unable to initialize gas sensor or thread. Disabling."
            self.log_warning_message(gas_disabled)
            self.send_message_to_all_numbers(gas_disabled)
            self.mq2_sensor = None

        self.ready_for_service = True

    def __get_help_status__(self):
        """
        Returns the message for help.
        """
        return "To control the piWarmer text ON, OFF, STATUS, HELP, or SHUTDOWN"

    def send_message(self, phone_number, message):
        """
        Sends a message to the given phone number.
        """
        try:
            if self.fona is not None:
                self.log_info_message(phone_number + ":" + message)
                if self.configuration.test_mode is None or not self.configuration.test_mode:
                    self.fona.send_message(phone_number, message)
                return True
        except:
            self.log_warning_message("Error while attemting to send message.")

        return False

    def send_message_to_all_numbers(self, message):
        """ Sends a message to ALL of the numbers in the configuration. """
        if message is None:
            return False

        self.log_info_message("Sending messages to all: " + message)

        for phone_number in self.configuration.allowed_phone_numbers:
            self.send_message(phone_number, message)

        if (self.configuration.push_notification_number
                not in self.configuration.allowed_phone_numbers):
            self.send_message(
                self.configuration.push_notification_number, message)

        return True

    def log_info_message(self, message_to_log):
        """ Log and print at Info level """
        print "LOG:" + message_to_log.replace("\n", "\\n").replace("\r", "\\r")
        self.logger.info(message_to_log)

        return message_to_log

    def log_warning_message(self, message_to_log):
        """ Log and print at Warning level """
        print "WARN:" + message_to_log
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

        for allowed_number in self.configuration.allowed_phone_numbers:
            self.log_info_message(
                "Checking " + phone_number + " against " + allowed_number)
            # Handle phone numbers that start with "1"... sometimes
            if allowed_number in phone_number or phone_number in allowed_number:
                return True

    def handle_on_request(self, phone_number):
        """ Handle a request to turn on. """

        if phone_number is None:
            return CommandResponse.CommandResponse(CommandResponse.ERROR, "Phone number was empty.")

        self.log_info_message("Received ON request from " + phone_number)

        if self.heater_relay.get_status() == 1:
            return CommandResponse.CommandResponse(CommandResponse.NOOP,
                                                   "Heater is already ON")

        if self.is_gas_detected():
            return CommandResponse.CommandResponse(CommandResponse.HEATER_OFF,
                                                   "Gas warning. Not turning heater on")

        return CommandResponse.CommandResponse(CommandResponse.HEATER_ON,
                                               "Heater turning on for "
                                               + str(self.configuration.max_minutes_to_run)
                                               + " minutes.")

    def handle_off_request(self, phone_number):
        """ Handle a request to turn off. """

        self.log_info_message("Received OFF request from " + phone_number)

        if self.heater_relay.get_status() == 1:
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

    def handle_status_request(self, phone_number):
        """
        Handle a status request.
        """
        self.log_info_message(
            "Received STATUS request from " + phone_number)

        return CommandResponse.CommandResponse(CommandResponse.STATUS, self.__get_status__())

    def handle_help_request(self, phone_number):
        """
        Handle a help request.
        """
        self.log_info_message(
            "Received HELP request from " + phone_number)

        return CommandResponse.CommandResponse(CommandResponse.STATUS, self.__get_help_status__())

    def get_command_response(self, message, phone_number):
        """ returns a command response based on the message. """
        if "on" in message:
            return self.handle_on_request(phone_number)
        elif "off" in message:
            return self.handle_off_request(phone_number)
        elif "status" in message:
            return self.handle_status_request(phone_number)
        elif "help" in message:
            return self.handle_help_request(phone_number)
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
        """
        Process a SMS message/command.
        """

        message = message.lower()
        self.log_info_message("Processing message:" + message)

        phone_number = Fona.get_cleaned_phone_number(phone_number)

        # check to see if this is an allowed phone number
        if not self.is_allowed_phone_number(phone_number):
            unauth_message = "Received unauthorized SMS from " + phone_number
            self.send_message(
                self.push_notification_number, unauth_message)
            return self.log_warning_message(unauth_message)

        command_response = self.get_command_response(
            message, phone_number)
        self.execute_command(command_response)

        if phone_number:
            self.last_number = phone_number

        if phone_number is not None:
            self.send_message(
                phone_number, command_response.get_message())
            self.log_info_message(
                "Sent message: " + command_response.get_message() + " to " + phone_number)
        else:
            self.log_warning_message(
                "Phone number missing, unable to send response:" + command_response.get_message())

        return command_response.get_message()

    def shutdown(self):
        """
        Shuts down the Pi
        """
        self.log_info_message("Assigning shutdown_timer_process in shutdown()")
        self.heater_relay.switch_low()
        subprocess.Popen(["sudo shutdown -P now " + str(self.configuration.heater_gpio_pin)],
                         shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)

    # for safety, this thread starts a timer for when the heater was turned on
    # and turns it off when reached
    def start_heater_shutoff_timer(self):
        """
        Starts a timer to turn off the heater.
        """
        self.log_info_message("Starting Heater Timer. Max Time is " +
                              str(self.configuration.max_minutes_to_run) + " minutes")
        time.sleep(self.configuration.max_minutes_to_run * 60)
        self.heater_queue.put(MAX_TIME)
        return

    def clear_queue(self, queue):
        """
        Clears a given queue.
        """
        if queue is None:
            return False

        while not queue.empty():
            print "cleared message from queue."
            queue.get()

    def monitor_gas_sensor(self):
        """
        Monitor the Gas Sensors. Sends a warning message if gas is detected.
        """

        self.log_info_message("Starting gas sensor loop.")

        while True:
            detected = self.is_gas_detected()
            current_level = self.mq2_sensor.current_value

            print "Detected: " + str(detected) + ", Level=" + str(current_level)

            # If gas is detected, send an immediate warning to
            # all of the phone numberss
            if detected:
                self.clear_queue(self.gas_sensor_queue)

                status = "WARNING!! GAS DETECTED!!! Level = " + \
                    str(current_level)

                if self.heater_relay.get_status() == 1:
                    status += ", TURNING HEATER OFF."
                    # clear the queue if it has a bunch of no warnings in it

                self.log_warning_message(status)
                print "Shoving command into queue"
                self.gas_sensor_queue.put(GAS_WARNING)
                self.heater_queue.put(OFF)
                self.heater_relay.switch_low()

                if not local_debug.is_debug():
                    time.sleep(60)
            else:
                print "Sending OK into queue"
                self.gas_sensor_queue.put(GAS_OK)

            time.sleep(2)

    def initialize_modem(self, retries=4, seconds_between_retries=10):
        """
        Attempts to initialize the modem over the serial port.
        """

        serial_connection = None

        if local_debug.is_debug():
            return None

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
        """
        Initializes and enables the MQ2 Gas Sensor
        """
        self.gas_sensor_queue = MPQueue()

        if self.configuration.is_mq2_enabled:
            self.log_info_message("MQ2 Gas Sensor enabled")
            # setup MQ2 GPIO PINS
            # create queue to hold MQ2 LED status
            # start sub process to monitor actual MQ2 sensor
            gas_sensor_process = Process(target=self.monitor_gas_sensor)

            if gas_sensor_process is None:
                self.log_warning_message("Failed to create gas sensor thread.")
                exit()

            gas_sensor_process.start()

            return True
        else:
            self.log_info_message("MQ2 Sensor not enabled")

        return False

    def start_heater_timer(self):
        """
        Starts the shutdown timer for the heater.
        """
        self.log_info_message("Attempting to start heater shutoff timer.")
        if self.shutoff_timer_process is not None:
            self.log_warning_message(
                "Turn off process already existed. Stopping.")
            self.shutoff_timer_process.terminate()
        self.shutoff_timer_process = Process(
            target=self.start_heater_shutoff_timer)
        if self.shutoff_timer_process is None:
            self.log_warning_message("FAILED to create shutoff timer.")

            return False

        try:
            self.shutoff_timer_process.start()
            self.log_info_message("Shutoff timer created")

            return True
        except:
            self.log_warning_message(
                "Error trying to start the shutoff timer!")

        return False

    def service_gas_sensor_queue(self):
        """
        Runs the service code for messages coming
        from the gas sensor.
        """

        if not self.configuration.is_mq2_enabled:
            return False

        try:
            while not self.gas_sensor_queue.empty():
                gas_sensor_status = self.gas_sensor_queue.get_nowait()

                if gas_sensor_status is None:
                    print "Nope"
                else:
                    print "Q:" + gas_sensor_status

                print "has_been_detected=" + str(self.gas_detected)

                self.mq2_sensor.update()

                # print "QUEUE: " + myLEDqstatus
                if GAS_WARNING in gas_sensor_status:

                    if not self.gas_detected:
                        gas_status = "GAS DETECTED. Level=" + \
                            str(self.mq2_sensor.current_value)

                        if self.heater_relay.get_status() == 1:
                            gas_status += "SHUTTING HEATER DOWN"

                        self.log_warning_message(gas_status)

                        # TODO - Figure out why the toggle isnt
                        # self.send_message_to_all_numbers(gas_status)
                        print "Would have called. Flag=" + str(self.gas_detected)
                        self.gas_detected = True
                        print "Now the flag is..." + str(self.gas_detected)

                    # Force the heater off command no matter
                    # what we think the status is.
                    self.heater_relay.switch_low()
                elif GAS_OK in gas_sensor_status:
                    if self.gas_detected:
                        gas_status = "Gas warning cleared with Level=" + \
                            str(self.mq2_sensor.current_value)
                        self.log_warning_message(gas_status)
                        self.send_message_to_all_numbers(gas_status)
                        print "Flag goes off"
                        self.gas_detected = False
        except Queue.Empty:
            pass

        return self.gas_detected

    def service_heater_queue(self):
        """
        Services the queue from the heater service thread.
        """
        # check the queue to deal with various issues,
        # such as Max heater time and the gas sensor being tripped
        try:
            status_queue = self.heater_queue.get_nowait()

            if ON in status_queue:
                self.log_info_message(
                    "Creating shutoff_timer_process for ON queue event.")
                self.start_heater_timer()
                self.log_info_message(
                    "Starting shutoff_timer_process for ON event.")
            if OFF in status_queue:
                self.log_info_message(
                    "Attempting to handle OFF queue event.")
                if self.shutoff_timer_process is not None:
                    self.shutoff_timer_process.terminate()
                else:
                    self.log_warning_message(
                        "self.shutoff_timer_process was None in queue handler.")
            if MAX_TIME in status_queue:
                self.log_info_message(
                    "Max time reached. Heater turned OFF")
                self.heater_relay.switch_low()
                self.send_message(
                    self.push_notification_number(),
                    "Heater was turned off due to max time being reached")
        except Queue.Empty:
            pass

    def process_pending_text_messages(self):
        """
        Processes any messages sitting on the sim card.
        """
        # get messages on SIM Card
        messages = self.fona.get_messages()
        total_message_count = len(messages)
        messages_processed_count = 0

        if total_message_count > 0:
            for message in messages:
                messages_processed_count += 1
                self.fona.delete_message(message)
                response = self.process_message(
                    message.message_text, message.sender_number)
                self.log_info_message(response)

            self.log_info_message(
                "Found " + str(total_message_count)
                + " messages, processed " + str(messages_processed_count))

        return total_message_count > 0

    def run_pi_warmer(self):
        """
        Service loop to run the PiWarmer
        """
        self.log_info_message('Press Ctrl-C to quit.')

        while not self.ready_for_service:
            print "."
            time.sleep(1)

        while True:
            try:
                self.service_gas_sensor_queue()
            except:
                self.log_warning_message(
                    "Exception captured while servicing the Gas Sensor Queue.")

            try:
                self.service_heater_queue()
            except:
                self.log_warning_message(
                    "Exception captured while servicing the Heater/Relay Queue.")

            try:
                self.process_pending_text_messages()
            except:
                self.log_warning_message(
                    "Exception captured while processing pending messages.")


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

    CONTROLLER.run_pi_warmer()

    print "Tests finished"
    exit()
