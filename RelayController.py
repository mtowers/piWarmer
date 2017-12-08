""" Module to control a Relay by SMS """

# encoding: UTF-8

# TODO - Make sure strings can handle unicode
# TODO - Make commands and help response customizable for Localization
# TODO - Make "Quit" work
# TODO - Add support for LCD status screen
# TODO - Add documentation on all of "pip installs" required
# TODO - Rename this to HangarBuddy or HangarRat
# TODO - Create a "HeaterManager" class
# TODO - Create an "AutoUpdate" feature. Can probably be in the rc.local
# TODO - Figure out a way to kill rc.local
# TODO - Document rc.local
# TODO - Break apart the status command into smaller command/responses
# TODO - Stop pulling/acting on messages whehn one changes that state of
#        the system (ON/OFF)
# TODO - Clear the messages when a reboot or QUIT is encountered
# TODO - Use a map/dictionary to trigger a message processing request
# TODO - Move the command processing into "message_processor".
#        Have relay controller be a member of MessageProcessor

import sys
import time
import Queue
from multiprocessing import Queue as MPQueue
import serial  # Requires "pyserial"
import lib.local_debug as local_debug
import lib.utilities as utilities
from lib.relay import PowerRelay
from lib.recurring_task import RecurringTask
from fona_manager import FonaManager
import command_processor
from Sensors import Sensors


OFF = "Off"
ON = "On"
MAX_TIME = "MAX_TIME"
GAS_WARNING = "Gas warning"
GAS_OK = "OK"

SYSTEM_START_TIME = time.time()



class RelayController(object):
    """
    Class to command and control the power relay.
    """

    def On(self):
        """
        Tells the heater to turn on.
        """

        if not self.get_status():
            self.heater_queue.put(ON)
            return True

        return False
    
    def Off(self):
        """
        Tells the heater to turn off.
        """
        if self.get_status():
            self.heater_queue.put(OFF)
            return True

        return False

    def get_status(self):
        """
        Get the status of the relay.
        True is "ON"
        False is "OFF"
        """

        return self.heater_relay.get_status() == 1


    def get_heater_time_remaining(self):
        """
        Returns a string saying how much time is left
        for the heater.
        """

        self.logger.log_info_message("get_heater_time_remaining()")

        time_remaining = ""

        if self.__heater_shutoff_timer__ is not None:
            self.logger.log_info_message("timer is not None")
            delta_time = self.__heater_shutoff_timer__ - time.time()
            self.logger.log_info_message("Got the delta")
            time_remaining = utilities.get_time_text(delta_time)
            self.logger.log_info_message("Got the text")
        else:
            self.logger.log_info_message("No time")
            time_remaining = "No time"

        self.logger.log_info_message("adding remaining")
        time_remaining += " remaining."

        self.logger.log_info_message("Done")

        return time_remaining

    def update(self):
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
            self.logger.log_warning_message(
                "Heater should not be on, but the PIN is still active... attempting shutdown.")
            self.heater_queue.put(OFF)

        # check the queue to deal with various issues,
        # such as Max heater time and the gas sensor being tripped
        while not self.heater_queue.empty():
            try:
                status_queue = self.heater_queue.get_nowait()

                if ON in status_queue:
                    if self.__on_callback__ is not None:
                        self.__on_callback__()
                    self.__start_heater__()

                if OFF in status_queue:
                    if self.__off_callback__ is not None:
                        self.__off_callback__()
                    # self.queue_message_to_all_numbers("Heater turned off.")
                    self.__stop_heater__()

                if MAX_TIME in status_queue:
                    if self.__max_time_callback__ is not None:
                        self.__max_time_callback__()
                    # self.queue_message_to_all_numbers(
                    #    "Max time reached. Heater turned OFF")
                    self.__stop_heater__()
            except Queue.Empty:
                pass


    def __init__(self,
                 configuration,
                 logger,
                 heater_on_callback,
                 heater_off_callback,
                 heater_max_time_callback):
        """ Initialize the object. """

        self.configuration = configuration
        self.logger = logger
        self.__on_callback__ = heater_on_callback
        self.__off_callback__ = heater_off_callback
        self.__max_time_callback__ = heater_max_time_callback

        # create heater relay instance
        self.heater_relay = PowerRelay(
            "heater_relay", configuration.heater_pin)
        self.heater_queue = MPQueue()

        # create queue to hold heater timer.
        self.__heater_shutoff_timer__ = None

        # make sure and turn heater off
        self.heater_relay.switch_low()

    def __stop_heater__(self):
        """
        Stops the heater.
        """
        self.logger.log_info_message("__stop_heater__::switch_low()")
        self.heater_relay.switch_low()
        self.logger.log_info_message("__stop_heater__::stop_heater_timer()")
        self.__stop_heater_timer__()

    def __start_heater__(self):
        """
        Starts the heater.
        """
        self.logger.log_info_message("__start_heater__::switch_high()")
        self.heater_relay.switch_high()
        self.logger.log_info_message("__start_heater__::start_heater_timer()")
        self.__start_heater_timer__()
    
    def __stop_heater_timer__(self):
        """
        Stops the heater timer.
        """

        self.logger.log_info_message("Cancelling the heater shutoff timer.")
        self.__heater_shutoff_timer__ = None

    def __start_heater_timer__(self):
        """
        Starts the shutdown timer for the heater.
        """
        self.logger.log_info_message("Starting the heater shutoff timer.")
        self.__heater_shutoff_timer__ = time.time(
        ) + (self.configuration.max_minutes_to_run * 60)

        return True

class CommandProcessor(object):
    """ Class to control a power relay based on SMS commands. """

    def __clear_existing_messages__(self):
        """ Clear all of the existing messages off tdhe SIM card.
        Send a message if we did. """
        # clear out all the text messages currently stored on the SIM card.
        # We don't want old messages being processed
        # dont send out a confirmation to these numbers because we are
        # just deleting them and not processing them
        num_deleted = self.fona_manager.delete_messages()
        if num_deleted > 0:
            for phone_number in self.configuration.allowed_phone_numbers:
                self.queue_message(phone_number,
                                   "Old or unprocessed message(s) found on SIM Card."
                                   + " Deleting...")
            self.logger.log_info_message(
                str(num_deleted) + " old message cleared from SIM Card")

    

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
        cbc = self.fona_manager.battery_condition()
        signal = self.fona_manager.signal_strength()

        status = "Signal strength is " + str(signal.get_signal_strength()) + "(" + signal.classify_strength() + ")" \
                 + ", battery at " + str(cbc.battery_percent) + "%, "

        if not cbc.is_battery_ok():
            status += "LOW BATTERY."

        return status

    def __get_gas_sensor_status__(self):
        """
        Returns the status text for the gas sensor.
        """

        if self.__sensors__.current_gas_sensor_reading is None \
                or not self.configuration.is_mq2_enabled:
            return "Gas sensor NOT enabled."

        status_text = "Gas sensor enabled, current reading=" + \
            str(self.__sensors__.current_gas_sensor_reading.current_value)

        if self.__sensors__.current_gas_sensor_reading.is_gas_detected:
            status_text += ". DANGER! GAS DETECTED!"
        else:
            status_text += "."

        return status_text

    def __get_temp_probe_status__(self):
        """
        Returns the status of the temperature probe.
        """

        if self.__sensors__.current_temperature_sensor_reading is not None:
            return "Temperature is " \
                   + str(self.__sensors__.current_temperature_sensor_reading) + "F"

        return "Temp probe not enabled."

    def __get_light_status__(self):
        """
        Classifies the hangar brightness.
        """

        if self.__sensors__.current_light_sensor_reading is not None:
            status = "Hangar has " + \
                     str(int(self.__sensors__.current_light_sensor_reading.lux)) + \
                     " lumens of light.\n"
            status += "Hangar is "
            brightness = "Bright. Did you leave the lights on?"

            if self.__sensors__.current_light_sensor_reading.lux <= self.configuration.hangar_dark:
                brightness = "dark."
            elif self.__sensors__.current_light_sensor_reading.lux <= self.configuration.hangar_dim:
                brightness = "dim."
            elif self.__sensors__.current_light_sensor_reading.lux <= self.configuration.hangar_lit:
                brightness = "lit."

            status += brightness

            return status

        return "Light sensor not enabled."

    def __get_status__(self):
        """
        Returns the status of the piWarmer.
        """

        uptime = time.time() - SYSTEM_START_TIME

        status = self.__get_heater_status__() + "\n"
        status += self.__get_gas_sensor_status__() + "\n"
        status += self.__get_light_status__() + "\n"
        status += self.__get_temp_probe_status__() + "\n"
        status += self.__get_fona_status__()

        if uptime > 60:
            status += "\nSystem has been up for " + \
                utilities.get_time_text(uptime)

        return status

    def __init__(self, configuration, logger):
        """ Initialize the object. """

        self.configuration = configuration
        self.logger = logger
        self.gas_detected = False
        self.__sensors__ = Sensors(configuration)

        serial_connection = self.initialize_modem()
        if serial_connection is None and not local_debug.is_debug():
            print "Nope"
            sys.exit()

        self.fona_manager = FonaManager(self.logger,
                                        serial_connection,
                                        self.configuration.cell_power_status_pin,
                                        self.configuration.cell_ring_indicator_pin)

        # create heater relay instance
        self.relay_controller = RelayController(configuration, logger)
        self.gas_sensor_queue = MPQueue()

        self.logger.log_info_message("Starting SMS monitoring and heater service")
        self.__clear_existing_messages__()

        self.logger.log_info_message("Begin monitoring for SMS messages")
        self.queue_message_to_all_numbers("piWarmer monitoring started."
                                          + "\n" + self.__get_help_status__())
        self.queue_message_to_all_numbers(self.__get_status__())

    def __get_help_status__(self):
        """
        Returns the message for help.
        """
        return "To control the piWarmer text ON, OFF, STATUS, HELP, QUIT, RESTART, or SHUTDOWN"

    def queue_message(self, phone_number, message):
        """
        Puts a request to send a message into the queue.
        """
        if self.fona_manager is not None and phone_number is not None and message is not None:
            self.logger.log_info_message(
                "MSG - " + phone_number + " : " + utilities.escape(message))
            self.fona_manager.send_message(phone_number, message)

            return True

        return False

    def queue_message_to_all_numbers(self, message):
        """
        Puts a request to send a message to all numbers into the queue.
        """

        for phone_number in self.configuration.allowed_phone_numbers:
            self.queue_message(phone_number, message)

        return message



    def is_gas_detected(self):
        """ Returns True if gas is detected. """
        if self.__sensors__.current_gas_sensor_reading is not None:
            return self.__sensors__.current_gas_sensor_reading.is_gas_detected

        return False

    def is_allowed_phone_number(self, phone_number):
        """ Returns True if the phone number is allowed in the whitelist. """

        if phone_number is None:
            return False

        for allowed_number in self.configuration.allowed_phone_numbers:
            self.logger.log_info_message(
                "Checking " + phone_number + " against " + allowed_number)
            # Handle phone numbers that start with "1"... sometimes
            if allowed_number in phone_number or phone_number in allowed_number:
                self.logger.log_info_message(phone_number + " is allowed")
                return True

        self.logger.log_info_message(phone_number + " is denied")
        return False

    def handle_on_request(self, phone_number):
        """ Handle a request to turn on. """

        if phone_number is None:
            return command_processor.CommandResponse(command_processor.ERROR,
                                                     "Phone number was empty.")

        self.logger.log_info_message("Received ON request from " + phone_number)

        if self.relay_controller.get_status():
            return command_processor.CommandResponse(command_processor.NOOP,
                                                     "Heater is already ON, "
                                                     + self.get_heater_time_remaining())

        if self.is_gas_detected():
            return command_processor.CommandResponse(command_processor.HEATER_OFF,
                                                     "Gas warning. Not turning heater on")

        return command_processor.CommandResponse(command_processor.HEATER_ON,
                                                 "Heater turning on for "
                                                 + str(self.configuration.max_minutes_to_run)
                                                 + " minutes.")

    def handle_off_request(self, phone_number):
        """ Handle a request to turn off. """

        self.logger.log_info_message("Received OFF request from " + phone_number)

        if self.relay_controller.get_status():
            try:
                return command_processor.CommandResponse(command_processor.HEATER_OFF,
                                                         "Turning heater off with "
                                                         + self.get_heater_time_remaining())
            except:
                return command_processor.CommandResponse(command_processor.ERROR,
                                                         "Issue turning Heater OFF")

        return command_processor.CommandResponse(command_processor.NOOP,
                                                 "Heater is already OFF")

    def handle_status_request(self, phone_number):
        """
        Handle a status request.
        """
        self.logger.log_info_message(
            "Received STATUS request from " + phone_number)

        return command_processor.CommandResponse(command_processor.STATUS, self.__get_status__())

    def handle_help_request(self, phone_number):
        """
        Handle a help request.
        """
        self.logger.log_info_message(
            "Received HELP request from " + phone_number)

        return command_processor.CommandResponse(command_processor.STATUS,
                                                 self.__get_help_status__())

    # TODO - Move as much of this into command_processor as possible.
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
        elif "restart" in message:
            self.logger.log_info_message("Go restart request")
            return command_processor.CommandResponse(command_processor.PI_WARMER_RESTART,
                                                     "Restart request from " + phone_number)
        elif "shutdown" in message:
            return command_processor.CommandResponse(command_processor.PI_WARMER_OFF,
                                                     "Received SHUTDOWN request from " \
                                                     + phone_number)

        return command_processor.CommandResponse(command_processor.HELP,
                                                 "COMMANDS: ON, OFF, STATUS, QUIT, SHUTDOWN")

    def execute_command(self, command_response):
        """ Executes the action the controller has determined. """
        # The commands "Help", "Status", and "NoOp"
        # only send responses back to the caller
        # and do not change the heater relay
        # or the Pi
        if command_response.get_command() == command_processor.PI_WARMER_OFF:
            try:
                self.queue_message_to_all_numbers(
                    "Shutting down Raspberry Pi.")
                self.shutdown()

                return True
            except:
                self.logger.log_warning_message(
                    "CR: Issue shutting down Raspberry Pi")
        elif command_response.get_command() == command_processor.PI_WARMER_RESTART:
            try:
                self.queue_message_to_all_numbers("Attempting restart")
                self.restart()

                return True
            except:
                self.logger.log_warning_message(
                    "CR: Issue restarting")
        elif command_response.get_command() == command_processor.HEATER_OFF:
            self.logger.log_info_message("CR: Turning heater OFF")
            self.heater_queue.put(OFF)

            return True
        elif command_response.get_command() == command_processor.HEATER_ON:
            self.log_info_message("CR: Turning heater ON")
            self.heater_queue.put(ON)

        return False

    def process_message(self, message, phone_number):
        """
        Process a SMS message/command.
        """

        # TODO - Figure out what LOCAL time the message was sent
        #        and ignore it if it is too old.

        message = message.lower()
        self.logger.log_info_message("Processing message:" + message)

        phone_number = utilities.get_cleaned_phone_number(phone_number)

        # check to see if this is an allowed phone number
        if not self.is_allowed_phone_number(phone_number):
            unauth_message = "Received unauthorized SMS from " + phone_number
            return self.queue_message_to_all_numbers(unauth_message)

        if len(phone_number) < 7:
            invalid_number_message = "Attempt from invalid phone number " + \
                phone_number + " received."
            return self.queue_message_to_all_numbers(invalid_number_message)

        message_length = len(message)
        if message_length < 1 or message_length > 32:
            invalid_message = "Message was invalid length."
            self.queue_message(
                phone_number, invalid_message)
            return self.logger.log_warning_message(invalid_message)

        command_response = self.get_command_response(
            message, phone_number)
        self.logger.log_info_message("Got command response")
        state_changed = self.execute_command(command_response)
        self.logger.log_info_message("executed command.")

        self.queue_message(
            phone_number, command_response.get_message())
        self.logger.log_info_message(
            "Sent message: " + command_response.get_message() + " to " + phone_number)

        return command_response.get_message(), state_changed

    def restart(self):
        """
        Restarts the Pi
        """
        self.logger.log_info_message("RESTARTING. Turning off relay")
        self.heater_relay.switch_low()
        utilities.restart()

    def shutdown(self):
        """
        Shuts down the Pi
        """
        self.logger.log_info_message("SHUTDOWN: Turning off relay.")
        self.heater_relay.switch_low()

        self.logger.log_info_message("SHUTDOWN: Shutting down piWarmer.")
        utilities.shutdown()

    def clear_queue(self, queue):
        """
        Clears a given queue.
        """
        if queue is None:
            return False

        while not queue.empty():
            self.logger.log_info_message("cleared message from queue.")
            queue.get()

    def monitor_gas_sensor(self):
        """
        Monitor the Gas Sensors. Sends a warning message if gas is detected.
        """

        # Since it is not enabled... then no reason to every
        # try again during this run
        if self.__sensors__.current_gas_sensor_reading is None:
            return

        detected = self.__sensors__.current_gas_sensor_reading.is_gas_detected
        current_level = self.__sensors__.current_gas_sensor_reading.current_value

        self.logger.log_info_message("Detected: " + str(detected) +
                              ", Level=" + str(current_level))

        # If gas is detected, send an immediate warning to
        # all of the phone numberss
        if detected:
            self.clear_queue(self.gas_sensor_queue)

            status = "WARNING!! GAS DETECTED!!! Level = " + \
                str(current_level)

            if self.relay_controller.get_status():
                status += ", TURNING HEATER OFF."
                # clear the queue if it has a bunch of no warnings in it

            self.logger.log_warning_message(status)
            self.gas_sensor_queue.put(
                GAS_WARNING + ", level=" + str(current_level))
            self.logger.heater_queue.put(OFF)
            self.queue_message_to_all_numbers(status)
        else:
            self.logger.log_info_message("Sending OK into queue", False)
            self.gas_sensor_queue.put(GAS_OK + ", level=" + str(current_level))

    def initialize_modem(self, retries=4, seconds_between_retries=10):
        """
        Attempts to initialize the modem over the serial port.
        """

        serial_connection = None

        if local_debug.is_debug():
            return None

        while retries > 0 and serial_connection is None:
            try:
                self.logger.log_info_message(
                    "Opening on " + self.configuration.cell_serial_port)

                serial_connection = serial.Serial(
                    self.configuration.cell_serial_port,
                    self.configuration.cell_baud_rate)
            except:
                self.logger.log_warning_message(
                    "SERIAL DEVICE NOT LOCATED."
                    + " Try changing /dev/ttyUSB0 to different USB port"
                    + " (like /dev/ttyUSB1) in configuration file or"
                    + " check to make sure device is connected correctly")

                # wait 60 seconds and check again
                time.sleep(seconds_between_retries)

            retries -= 1

        return serial_connection



    def service_gas_sensor_queue(self):
        """
        Runs the service code for messages coming
        from the gas sensor.
        """

        try:
            while not self.gas_sensor_queue.empty():
                gas_sensor_status = self.gas_sensor_queue.get()

                if gas_sensor_status is None:
                    self.logger.log_warning_message("Gas sensor was None.")
                else:
                    self.logger.log_info_message("Q:" + gas_sensor_status, False)

                # print "QUEUE: " + myLEDqstatus
                if GAS_WARNING in gas_sensor_status:

                    if not self.gas_detected:
                        gas_status = gas_sensor_status

                        if self.relay_controller.get_status():
                            gas_status += "SHUTTING HEATER DOWN"

                        self.queue_message_to_all_numbers(gas_status)
                        self.logger.log_warning_message("Turning detected flag on.")
                        self.gas_detected = True

                    # Force the heater off command no matter
                    # what we think the status is.
                    self.heater_queue.put(OFF)
                elif GAS_OK in gas_sensor_status:
                    if self.gas_detected:
                        cleared_message = "Gas warning cleared. " + gas_sensor_status
                        self.queue_message_to_all_numbers(cleared_message)
                        self.logger.log_info_message("Turning detected flag off.")
                        self.gas_detected = False
        except Queue.Empty:
            pass

        return self.gas_detected


    def process_pending_text_messages(self):
        """
        Processes any messages sitting on the sim card.
        """
        # Check to see if the RI pin has been
        # tripped, or is it is time to poll
        # for messages.
        if not self.fona_manager.is_message_waiting():
            return False

        # Get the messages from the sim card
        messages = self.fona_manager.get_messages()
        total_message_count = len(messages)
        messages_processed_count = 0

        # TODO - Do I really want to process all of the pending
        #        messages? Should we check to see if a mesage
        #        changes the status of the system and then
        #        break the processing so the queue can then
        #        actually change the state?
        if total_message_count > 0:
            # TODO - Sort these messages so they are processed
            #        in the order they were sent.
            #        The order of reception by the GSM
            #        chip can be out of order.
            # TODO - Ignore really old messages
            for message in messages:
                messages_processed_count += 1
                self.fona_manager.delete_message(message)
                response, state_changed = self.process_message(
                    message.message_text, message.sender_number)
                self.logger.log_info_message(response)

                # If the command did something to the unit
                # stop processing other commands
                if state_changed:
                    break

            self.logger.log_info_message(
                "Found " + str(total_message_count)
                + " messages, processed " + str(messages_processed_count))

        return total_message_count > 0


    def monitor_fona_health(self):
        """
        Check to make sure the Fona battery and
        other health signals are OK.
        """

        cbc = self.fona_manager.battery_condition()

        self.logger.log_info_message("GSM Battery=" + str(cbc.get_percent_battery()) + "% Volts=" +
                              str(cbc.get_capacity_remaining()))

        if not cbc.is_battery_ok():
            low_battery_message = "WARNING: LOW BATTERY for Fona. Currently " + \
                str(cbc.get_percent_battery()) + "%"
            self.queue_message_to_all_numbers(low_battery_message)
            self.logger.log_warning_message(low_battery_message)

    def run_servicer(self, service_callback, service_name):
        """
        Calls and handles something with a servicer.
        """

        if service_callback is None:
            self.logger.log_warning_message("Unable to service " + service_name)

        try:
            service_callback()
        except KeyboardInterrupt:
            print "Stopping due to CTRL+C"
            exit()
        except:
            self.logger.log_warning_message(
                "Exception while servicing " + service_name)
            print "Error:", sys.exc_info()[0]

    def run_pi_warmer(self):
        """
        Service loop to run the PiWarmer
        """
        self.logger.log_info_message('Press Ctrl-C to quit.')

        # This can be safely used off the main thread.
        # and writes into the MPqueue...
        # It kicks off every 30 seconds

        RecurringTask("monitor_gas_sensor", 30,
                      self.monitor_gas_sensor, self.logger)

        RecurringTask("battery_check", 60 * 5,
                      self.monitor_fona_health, self.logger)

        while True:
            self.run_servicer(self.service_gas_sensor_queue,
                              "Gas sensor queue")
            self.relay_controller.update()
            self.run_servicer(self.process_pending_text_messages,
                              "Incoming request queue")
            self.fona_manager.update()


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

    CONTROLLER = CommandProcessor(CONFIG, logging.getLogger("Controller"))

    CONTROLLER.run_pi_warmer()

    print "Tests finished"
    exit()
