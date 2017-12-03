""" Module to control a Relay by SMS """

# encoding: UTF-8

# TODO - Make sure strings can handle unicode
# TODO - Make commands and help response customizable for Localization
# TODO - Separate logs for the sensors
# TODO - Add a restart command
# TODO - Make "Quit" work

import sys
import time
import threading
import subprocess
import Queue
from multiprocessing import Queue as MPQueue
import serial  # Requires "pyserial"
import CommandResponse
import lib.gas_sensor as gas_sensor
import lib.fona as Fona
from lib.relay import PowerRelay
import lib.temp_probe as temp_probe
import lib.local_debug as local_debug
from lib.light_sensor import LightSensor, LightSensorResult


OFF = "Off"
ON = "On"
MAX_TIME = "MAX_TIME"
GAS_WARNING = "gas_warning"
GAS_OK = "no_warning"


class MessageSendRequest(object):
    """
    Object to use for queuing message requests.
    """

    def is_valid(self):
        """
        Is the message valid.
        """
        return self.phone_number is not None and self.message is not None

    def __init__(self, phone_number, message):
        self.phone_number = phone_number
        self.message = message


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
                self.queue_message(phone_number,
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
        status_text = "Gas sensor enabled, current reading=" + \
            str(self.mq2_sensor.current_value)

        if gas_detected:
            status_text += ". DANGER! GAS DETECTED!"
        else:
            status_text += "."

        return status_text

    def __get_temp_probe_status__(self):
        """
        Returns the status of the temperature probe.
        """

        if self.configuration.is_temp_probe_enabled:
            sensor_readings = temp_probe.read_sensors()
            if sensor_readings is None or len(sensor_readings) < 1:
                return "Temp probe enabled, but not found."

            return "Temperature is " + str(int(sensor_readings[0])) + "F"

        return "Temp probe not enabled."

    def get_time_text(self, number_of_seconds):
        """
        Returns the amount of time in the appropriate unit.
        """

        self.log_info_message("Total=" + str(number_of_seconds))

        if number_of_seconds < 60:
            self.log_info_mesasge("Returning seconds")
            return str(int(number_of_seconds)) + " seconds"

        self.log_info_message("Checking minutes")
        number_of_minutes = number_of_seconds / 60

        self.log_info_message("Total=" + str(number_of_minutes))

        if number_of_minutes < 60:
            return str(int(number_of_minutes)) + " minutes"

        self.log_info_message("Checking hours")
        number_hours = number_of_minutes / 60
        self.log_info_message("Total=" + str(number_of_hours))

        if number_of_hours < 24:
            return str(number_of_hours) + " hours"

        number_days = number_of_hours / 24

        return str(number_of_days) + " days"

    def get_heater_time_remaining(self):
        """
        Returns a string saying how much time is left
        for the heater.
        """

        self.log_info_message("get_heater_time_remaining()")

        time_remaining = ""

        if self.__heater_shutoff_timer__ is not None:
            self.log_info_message("timer is not None")
            delta_time = self.__heater_shutoff_timer__ - time.time()
            self.log_info_message("Got the delta")
            time_remaining = self.get_time_text(delta_time)
            self.log_info_message("Got the text")
        else:
            selof.log_info_message("No time")
            time_remaining = "No time"


        self.log_info_message("adding remaining")
        time_remaining += " remaining."

        self.log_info_message("Done")
        return time_remaining


    def __get_heater_status__(self):
        """
        Returns the status of the heater/relay.
        """
        if self.heater_relay is None:
            return "Relay not detected."

        status_text = "Heater is "

        if self.heater_relay.get_status() == 1:
            status_text += "ON. "
            status_text += self.get_heater_time_remaining()
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

        if not cbc.is_battery_ok():
            status += "LOW BATTERY."

        return status

    def __get_light_status__(self):
        """
        Classifies the hangar brightness.
        """

        if self.light_sensor is not None:
            results = LightSensorResult(self.light_sensor)

            status = "Hangar has " + str(int(results.lux)) + " lumens of light.\n"
            status += "Hangar is "
            brightness = "Bright. Did you leave the lights on?"

            if results.lux <= self.configuration.hangar_dark:
                brightness = "dark."
            elif results.lux <= self.configuration.hangar_dim:
                brightness = "dim."
            elif results.lux <= self.configuration.hangar_lit:
                brightness = "lit."

            status += brightness

            return status
                
        
        return "Light sensor not enabled."

    def __get_status__(self):
        """
        Returns the status of the piWarmer.
        """

        uptime = time.time() - self.__system_start_time__

        status = self.__get_heater_status__() + "\n"
        status += self.__get_gas_sensor_status__() + "\n"
        status += self.__get_light_status__() + "\n"
        status += self.__get_temp_probe_status__() + "\n"
        status += self.__get_fona_status__()

        if uptime > 60:
            status += "\nSystem has been up for " + self.get_time_text(uptime)

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
        self.__system_start_time__ = time.time()
        self.configuration = configuration
        self.logger = logger
        self.gas_detected = False
        self.light_sensor = None
        if self.configuration.is_light_sensor_enabled:
            self.light_sensor = LightSensor()

        serial_connection = self.initialize_modem()
        if serial_connection is None and not local_debug.is_debug():
            print "Nope"
            sys.exit()

        self.fona = Fona.Fona(serial_connection,
                              self.configuration.cell_power_status_pin,
                              self.configuration.cell_ring_indicator_pin,
                              self.configuration.allowed_phone_numbers)

        # create heater relay instance
        self.heater_relay = PowerRelay(
            "heater_relay", configuration.heater_pin)
        self.heater_queue = MPQueue()
        self.gas_sensor_queue = MPQueue()
        self.message_send_queue = MPQueue()

        # create queue to hold heater timer.
        self.mq2_sensor = self.__start_gas_sensor__()
        self.__heater_shutoff_timer__ = None
        self.__fona_battery_check_timer__ = time.time()

        if self.fona is None and not local_debug.is_debug():
            self.log_warning_message("Uable to initialize, quiting.")
            sys.exit()

        # make sure and turn heater off
        self.heater_relay.switch_low()
        self.log_info_message("Starting SMS monitoring and heater service")
        self.__clear_existing_messages__()

        self.log_info_message("Begin monitoring for SMS messages")
        self.queue_message_to_all_numbers("piWarmer monitoring started."
                                          + "\n" + self.__get_help_status__())
        self.queue_message_to_all_numbers(self.__get_status__())

    def __get_help_status__(self):
        """
        Returns the message for help.
        """
        return "To control the piWarmer text ON, OFF, STATUS, HELP, or SHUTDOWN"

    def queue_message(self, phone_number, message):
        """
        Puts a request to send a message into the queue.
        """
        if self.message_send_queue is not None and phone_number is not None and message is not None:
            self.log_info_message("MSG - " + phone_number + " : " + Fona.escape(message))
            self.message_send_queue.put(
                MessageSendRequest(phone_number, message))

            return True

        return False

    def queue_message_to_all_numbers(self, message):
        """
        Puts a request to send a message to all numbers into the queue.
        """

        for phone_number in self.configuration.allowed_phone_numbers:
            self.queue_message(phone_number, message)

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

    def log_info_message(self, message_to_log, print_to_screen=True):
        """ Log and print at Info level """
        if print_to_screen:
            print "LOG:" + Fona.escape(message_to_log)
        self.logger.info(Fona.escape(message_to_log))

        return message_to_log

    def log_warning_message(self, message_to_log):
        """ Log and print at Warning level """
        print "WARN:" + message_to_log
        self.logger.warning(Fona.escape(message_to_log))

        return message_to_log

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
                self.log_info_message(phone_number + " is allowed")
                return True

        self.log_info_message(phone_number + " is denied")
        return False

    def handle_on_request(self, phone_number):
        """ Handle a request to turn on. """

        if phone_number is None:
            return CommandResponse.CommandResponse(CommandResponse.ERROR, "Phone number was empty.")

        self.log_info_message("Received ON request from " + phone_number)

        if self.heater_relay.get_status() == 1:
            return CommandResponse.CommandResponse(CommandResponse.NOOP,
                                                   "Heater is already ON, " + self.get_heater_time_remaining())

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
                return CommandResponse.CommandResponse(CommandResponse.HEATER_OFF,
                                                       "Turning heater off with " + self.get_heater_time_remaining())
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
        elif "quit" in message:
            sys.exit()
        elif "status" in message:
            return self.handle_status_request(phone_number)
        elif "help" in message:
            return self.handle_help_request(phone_number)
        elif "shutdown" in message:
            return CommandResponse.CommandResponse(CommandResponse.PI_WARMER_OFF,
                                                   "Received SHUTDOWN request from " + phone_number)

        return CommandResponse.CommandResponse(CommandResponse.HELP,
                                               "COMMANDS: ON, OFF, STATUS, QUIT, SHUTDOWN")

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
                    "CR: Issue shutting down Raspberry Pi")
        elif command_response.get_command() == CommandResponse.HEATER_OFF:
            try:
                self.log_info_message("CR: Turning heater OFF")
                self.heater_queue.put(OFF)
            except:
                self.log_warning_message(
                    "CR: Issue turning off Heater")
        elif command_response.get_command() == CommandResponse.HEATER_ON:
            try:
                self.log_info_message("CR: Turning heater ON")
                self.heater_queue.put(ON)
            except:
                self.log_warning_message(
                    "Issue turning on Heater")

    def process_message(self, message, phone_number):
        """
        Process a SMS message/command.
        """

        message = message.lower()
        self.log_info_message("Processing message:" + message)

        phone_number = Fona.get_cleaned_phone_number(phone_number)

        # check to see if this is an allowed phone number
        if not self.is_allowed_phone_number(phone_number):
            unauth_message = "Received unauthorized SMS from " + phone_number
            self.queue_message_to_all_numbers(unauth_message)
            return self.log_warning_message(unauth_message)

        if len(phone_number) < 7:
            invalid_number_message = "Attempt from invalid phone number " + phone_number + " received."
            self.queue_message_to_all_numbers(invalid_number_message)
            return self.log_warning_message(invalid_number_message)

        message_length = len(message)
        if message_length < 1 or message_length > 32:
            invalid_message = "Message was invalid length."
            self.queue_message(
                phone_number, invalid_message)
            return self.log_warning_message(invalid_message)

        command_response = self.get_command_response(
            message, phone_number)
        self.execute_command(command_response)

        self.queue_message(
            phone_number, command_response.get_message())
        self.log_info_message(
            "Sent message: " + command_response.get_message() + " to " + phone_number)

        return command_response.get_message()

    def shutdown(self):
        """
        Shuts down the Pi
        """
        self.log_info_message("SHUTDOWN: Turning off relay.")
        self.heater_relay.switch_low()

        self.log_info_message("SHUTDOWN: Shutting down piWarmer.")
        if not local_debug.is_debug():
            subprocess.Popen(["sudo shutdown -P now " + str(self.configuration.heater_pin)],
                             shell=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)

    def clear_queue(self, queue):
        """
        Clears a given queue.
        """
        if queue is None:
            return False

        while not queue.empty():
            self.login_info_message("cleared message from queue.")
            queue.get()

    def monitor_gas_sensor(self):
        """
        Monitor the Gas Sensors. Sends a warning message if gas is detected.
        """

        # Since it is not enabled... then no reason to every
        # try again during this run
        if self.mq2_sensor is not None and self.configuration.is_mq2_enabled:
            return

        detected = self.is_gas_detected()
        current_level = self.mq2_sensor.current_value

        self.log_info_message("Detected: " + str(detected) + ", Level=" + str(current_level))

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
            self.gas_sensor_queue.put(GAS_WARNING)
            self.heater_queue.put(OFF)
        else:
            self.log_info_message("Sending OK into queue", False)
            self.gas_sensor_queue.put(GAS_OK)

        threading.Timer(30, self.monitor_gas_sensor).start()

    def initialize_modem(self, retries=4, seconds_between_retries=10):
        """
        Attempts to initialize the modem over the serial port.
        """

        serial_connection = None

        if local_debug.is_debug():
            return None

        while retries > 0 and serial_connection is None:
            try:
                self.log_info_message("Opening on " + self.configuration.cell_serial_port)

                serial_connection = serial.Serial(
                    self.configuration.cell_serial_port,
                    self.configuration.cell_baud_rate)
            except:
                self.log_warning_message(
                    "SERIAL DEVICE NOT LOCATED."
                    + " Try changing /dev/ttyUSB0 to different USB port"
                    + " (like /dev/ttyUSB1) in configuration file or"
                    + " check to make sure device is connected correctly")

                # wait 60 seconds and check again
                time.sleep(seconds_between_retries)

            retries -= 1

        return serial_connection

    def stop_heater_timer(self):
        """
        Stops the heater timer.
        """

        self.log_info_message("Cancelling the heater shutoff timer.")
        self.__heater_shutoff_timer__ = None

    def start_heater_timer(self):
        """
        Starts the shutdown timer for the heater.
        """
        self.log_info_message("Starting the heater shutoff timer.")
        self.__heater_shutoff_timer__ = time.time(
        ) + (self.configuration.max_minutes_to_run * 60)

        return True

    def service_gas_sensor_queue(self):
        """
        Runs the service code for messages coming
        from the gas sensor.
        """

        if not self.configuration.is_mq2_enabled:
            return False

        try:
            while not self.gas_sensor_queue.empty():
                gas_sensor_status = self.gas_sensor_queue.get()

                if gas_sensor_status is None:
                    self.log_warning_message("Gas sensor was None.")
                else:
                    self.log_info_message("Q:" + gas_sensor_status, False)

                self.mq2_sensor.update()
                self.log_info_message("mq_2_level=" + str(self.mq2_sensor.current_value) + ", has_been_detected=" + \
                    str(self.gas_detected), self.gas_detected)

                # print "QUEUE: " + myLEDqstatus
                if GAS_WARNING in gas_sensor_status:

                    if not self.gas_detected:
                        gas_status = "GAS DETECTED. Level=" + \
                            str(self.mq2_sensor.current_value)

                        if self.heater_relay.get_status() == 1:
                            gas_status += "SHUTTING HEATER DOWN"

                        self.log_warning_message(gas_status)

                        self.queue_message_to_all_numbers(gas_status)
                        self.log_warning_message("Turning detected flag on.")
                        self.gas_detected = True

                    # Force the heater off command no matter
                    # what we think the status is.
                    self.heater_queue.put(OFF)
                elif GAS_OK in gas_sensor_status:
                    if self.gas_detected:
                        gas_status = "Gas warning cleared with Level=" + \
                            str(self.mq2_sensor.current_value)
                        self.log_warning_message(gas_status)
                        self.queue_message_to_all_numbers(gas_status)
                        self.log_info_message("Turning detected flag off.")
                        self.gas_detected = False
        except Queue.Empty:
            pass

        return self.gas_detected

    def __stop_heater__(self):
        """
        Stops the heater.
        """
        self.log_info_message("__stop_heater__::switch_low()")
        self.heater_relay.switch_low()
        self.log_info_message("__stop_heater__::stop_heater_timer()")
        self.stop_heater_timer()

    def __start_heater__(self):
        """
        Starts the heater.
        """
        self.log_info_message("__start_heater__::switch_high()")
        self.heater_relay.switch_high()
        self.log_info_message("__start_heater__::start_heater_timer()")
        self.start_heater_timer()

    def service_heater_queue(self):
        """
        Services the queue from the heater service thread.
        """

        # Check to see if the timer has expired.
        # If so, then add it to the action.
        if self.__heater_shutoff_timer__ is not None \
                and self.__heater_shutoff_timer__ < time.time():
            self.heater_queue.put(MAX_TIME)
        elif self.__heater_shutoff_timer__ is None \
                and self.heater_relay.get_status() == 1:
            self.log_warning_message(
                "Heater should not be on, but the PIN is still active... attempting shutdown.")
            self.heater_queue.put(OFF)

        # check the queue to deal with various issues,
        # such as Max heater time and the gas sensor being tripped
        while not self.heater_queue.empty():
            try:
                status_queue = self.heater_queue.get_nowait()

                if ON in status_queue:
                    self.__start_heater__()

                if OFF in status_queue:
                    self.log_info_message("Attempting to handle OFF queue event.")
                    self.queue_message_to_all_numbers("Heater turned off.")
                    self.log_info_message("STOP MSG queued, stopping.")
                    self.__stop_heater__()

                if MAX_TIME in status_queue:
                    self.log_info_message("Max time reached. Heater turned OFF")
                    self.queue_message_to_all_numbers(
                        "Heater was turned off due to max time being reached")
                    self.log_info_message("MAX MSG queued, stopping")
                    self.__stop_heater__()
            except Queue.Empty:
                pass

    def process_pending_text_messages(self):
        """
        Processes any messages sitting on the sim card.
        """
        # Check to see if the RI pin has been
        # tripped, or is it is time to poll
        # for messages.
        if not self.fona.is_message_waiting():
            return False

        # Get the messages from the sim card
        messages = self.fona.get_messages("process_pending_text_messages")
        total_message_count = len(messages)
        messages_processed_count = 0

        # TODO - Do I really want to process all of the pending
        #        messages? Should we check to see if a mesage
        #        changes the status of the system and then
        #        break the processing so the queue can then
        #        actually change the state?
        if total_message_count > 0:
            # TODO - Sort these messages so they are processed
            # in the order they were sent.
            # The order of reception by the GSM
            # chip can be out of order.
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

    def process_message_send_requests(self):
        """
        Process all of the requests to send messages.
        """

        if self.message_send_queue is None:
            return False

        is_success = True

        while not self.message_send_queue.empty():
            try:
                send_request = self.message_send_queue.get_nowait()

                self.send_message(send_request.phone_number,
                                  send_request.message)
            except:
                self.log_warning_message(
                    "Error while processing sending queue!")
                is_success = False

        return is_success

    def monitor_fona_health(self):
        """
        Check to make sure the Fona battery and
        other health signals are OK.
        """

        if time.time() > self.__fona_battery_check_timer__:
            self.log_info_message("monitor_fona_health")
            cbc = self.fona.get_current_battery_condition()

            self.log_info_message("GSM Battery=" + str(cbc.get_percent_battery()) + "% Volts=" + \
                str(cbc.get_capacity_remaining()))

            if cbc.is_battery_ok():
                # All is OK. Check again in 15 minutes
                self.log_info_message("Battery is OK.")
                self.__fona_battery_check_timer__ = time.time() + 15 * 60
            else:
                low_battery_message = "WARNING: LOW BATTERY for Fona. Currently " + \
                    str(cbc.get_percent_battery()) + "%"
                self.queue_message_to_all_numbers(low_battery_message)
                self.log_warning_message(low_battery_message)

                # Check again in an hour
                self.__fona_battery_check_timer__ = time.time() + 60 * 60

    def run_servicer(self, service_callback, service_name):
        """
        Calls and handles something with a servicer.
        """

        if service_callback is None:
            self.log_warning_message("Unable to service " + service_name)

        try:
            service_callback()
        except KeyboardInterrupt:
            print "Stopping due to CTRL+C"
            exit()
        except:
            self.log_warning_message("Exception while servicing " + service_name)
            print "Error:", sys.exc_info()[0]

    def run_pi_warmer(self):
        """
        Service loop to run the PiWarmer
        """
        self.log_info_message('Press Ctrl-C to quit.')

        # This can be safely used off the main thread.
        # and writes into the MPqueue...
        # It kicks off every 30 seconds
        self.monitor_gas_sensor()

        while True:
            self.run_servicer(self.monitor_fona_health, "Battery check")
            self.run_servicer(self.service_gas_sensor_queue, "Gas sensor queue")
            self.run_servicer(self.service_heater_queue, "Heater request queue")
            self.run_servicer(self.process_pending_text_messages, "Incoming request queue")
            self.run_servicer(self.process_message_send_requests, "Outgoing requeust queue")


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
