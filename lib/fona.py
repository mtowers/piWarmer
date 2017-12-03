"""
Module to help with tha AdaFruit Fona modules
"""
# TODO - Need to wire the GPIO to the Fona to turn itself on
# TODO - Could wire to the fona for a status/waiting bit
import time
import threading
import local_debug
from multiprocessing import Queue as MPQueue

if not local_debug.is_debug():
    import RPi.GPIO as GPIO

SECONDS_TO_WAIT_AFTER_SEND = 5
BATTERY_CRITICAL = 40
BATTERY_WARNING = 60
DEFAULT_RESPONSE_READ_TIMEOUT = 5

DEFAULT_RING_INDICATOR_PIN = 18 # (Physical... GPIO24)
DEFAULT_POWER_STATUS_PIN = 16 # (Physical ..GPIO23)


def escape(text):
    """
    Replaces escape sequences do they can be printed.
    """
    return text.replace('\r', '\\r').replace('\n', '\\n').replace('\x1a', '\\x1a')


def get_cleaned_phone_number(dirty_number):
    """
    Removes any text from the phone number that
    could cause the command to not work.

    >>> get_cleaned_phone_number('"2061234567"')
    '2061234567'
    >>> get_cleaned_phone_number('+2061234567')
    '2061234567'
    >>> get_cleaned_phone_number('""+2061234567')
    '2061234567'
    >>> get_cleaned_phone_number('2061234567')
    '2061234567'
    >>> get_cleaned_phone_number('(206) 123-4567')
    '2061234567'
    >>> get_cleaned_phone_number(None)
    """
    if dirty_number is not None:
        return dirty_number.replace('+',
                                    '').replace('(',
                                                '').replace(')',
                                                            '').replace('-',
                                                                        '').replace(' ',
                                                                                    '').replace('"',
                                                                                                '')
    return None


class BatteryCondition(object):
    """
    Class to keep the battery state.
    """

    def get_percent_battery(self):
        """
        Returns the remaining percentage of battery.
        """
        return self.battery_percent

    def get_capacity_remaining(self):
        """
        Returns the milliamp hours remaining.
        """
        return self.milliamp_hours

    def is_battery_ok(self):
        """
        Is the battery OK?
        """
        if self.error_state:
            return False

        return self.battery_percent > BATTERY_CRITICAL

    def __init__(self, command_result):
        """
        Initialize.
        """
        self.error_state = False

        if command_result is None or len(command_result) < 1:
            self.error_state = True
        else:
            tokens = command_result.split(':')

            if tokens is None or len(tokens) <= 1:
                print "Error attempting to process: " + command_result
                self.error_state = True
            else:
                results = tokens[1].split(',')

                if results is None or len(results) <= 2:
                    self.error_state = True

        if not self.error_state:
            self.charge_state = float(results[0])
            self.battery_percent = float(results[1])
            self.milliamp_hours = float(results[2]) / 10.0
        else:
            self.charge_state = 0
            self.battery_percent = 0
            self.milliamp_hours = 0


class SignalStrength(object):
    """
    Class to hold the signal strength.
    """

    def get_signal_strength(self):
        """
        Returns the signal strength.
        """
        return self.recieved_signal_strength

    def get_bit_error_rate(self):
        """
        Returns the bit error rate from the Fona.
        """
        return self.bit_error_rate

    def classify_strength(self):
        """
        Gets a human meaning to the rssi.
        """
        if self.recieved_signal_strength is None:
            return "Unknown"

        if self.recieved_signal_strength <= 9:
            return "Marginal"

        if self.recieved_signal_strength <= 14:
            return "OK"

        if self.recieved_signal_strength <= 19:
            return "Good"

        return "Excellent"

    def __init__(self, command_result):
        """
        Parses the command result.
        """
        try:
            tokens = command_result.split(':')
            tokens = tokens[1].split(',')
            self.recieved_signal_strength = int(tokens[0])
            self.bit_error_rate = int(tokens[1])
        except:
            self.recieved_signal_strength = 0
            self.bit_error_rate = 0


class SmsMessage(object):
    """
    Class to abstract a text message.
    """

    def get_sender_number(self):
        """
        Gets the sender's number.
        """
        if self.is_message_ok():
            return get_cleaned_phone_number(self.sender_number)

        return None

    def is_message_ok(self):
        """
        Is the message valid?
        """
        return not self.error_state

    def __init__(self,
                 message_header,
                 message_text):
        """
        Create the object.
        """
        self.message_id = None
        self.message_date = None
        self.message_time = None
        self.sender_number = None
        self.message_status = None
        self.message_text = None

        try:
            metadata_list = message_header.split(",")
            message_id = metadata_list[0]
            message_id = message_id.rpartition(":")[2].strip()
            message_status = metadata_list[1]
            sender_number = metadata_list[2]
            message_date = metadata_list[4]
            message_time = metadata_list[5]

            self.message_id = message_id
            self.message_date = message_date
            self.message_time = message_time
            self.sender_number = sender_number
            self.message_status = message_status
            self.message_text = message_text
            self.error_state = False
        except:
            self.error_state = True


class Fona(object):
    """
    Class that send messages with an Adafruit Fona
    SERIAL_PORT, BAUDRATE, timeout=.1, rtscts=0
    Attributes:
    unauthorize numbers
    """

    def __init__(self, ser, \
            power_status_pin, \
            ring_indicator_pin, \
            allowednumbers):
        self.command_history = []
        self.serial_connection = ser
        self.power_status_pin = power_status_pin
        self.ring_indicator_pin = ring_indicator_pin

        if self.serial_connection is not None:
            self.serial_connection.flushInput()
            self.serial_connection.flushOutput()

        self.allowednumbers = allowednumbers
        self.send_command("AT")
        # self.send_command("AE0")
        self.disable_verbose_errors()
        self.set_sms_mode()

        self.read_from_fona(10)

        self.__message_waiting_queue__ = MPQueue()
        self.__initialize_gpio_pins__()
        self.poll_for_messages()

    def __use_gpio_pins__(self):
        """
        Returns true if we should use the GPIO pins
        to tell status.
        """

        return self.power_status_pin is not None \
            and self.ring_indicator_pin is not None

    def __initialize_gpio_pins__(self):
        """
        Gets the Fona ready to be interacted with by the GPIO board.
        """

        if not self.__use_gpio_pins__():
            print "Skipping GPIO init."
            return False

        print "Setting GPIO input modes"

        # Set the RI pin to pulse low when
        # a text message is received
        self.send_command("AT+CFGRI=1")

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.ring_indicator_pin, GPIO.IN)
        GPIO.setup(self.power_status_pin, GPIO.IN)
        GPIO.add_event_detect(self.ring_indicator_pin, GPIO.RISING, self.ring_indicator_pulsed)


        return True

    def poll_for_messages(self):
        """
        Check for messages every 60 seconds.
        """
        self.__message_waiting_queue__.put("POLL")
        threading.Timer(60, self.poll_for_messages).start()

    def ring_indicator_pulsed(self, io_pin):
        """
        The RI went from LOW to HIGH.
        That means a message.
        """
        self.__message_waiting_queue__.put("RI:" + str(io_pin))

    def is_power_on(self):
        """
        Returns TRUE if the power is on.
        """

        print "is_power_on()"
        if self.__use_gpio_pins__():
            pin_value = GPIO.input(self.power_status_pin)
            print "Power... PIN=" + str(self.power_status_pin) + ", VAL=" + str(pin_value)
            return GPIO.input(self.power_status_pin) == GPIO.HIGH 

        # If we are not using the power pins
        # then use the existance of the serial
        # modem connection
        return self.ser is not None

    def write_to_fona(self,
                      text):
        """
        Write text to the Fona in a safe manner.
        """
        # print "Checking connection"
        if self.serial_connection is None:
            return "NO CON"

        # print "Writting to serial"
        num_bytes_written = self.serial_connection.write(text)
        self.serial_connection.flush()

        self.command_history.append(
            "self.write_to_fona(" + escape(text) + ")")

        # print "Checking return"
        # print "Wrote " + str(num_bytes_written) + ", expected " + str(len(text))

        self.wait_for_command_response()

        return num_bytes_written

    def read_from_fona(self, response_timeout=2):
        """
        Read back from the Fona in a safe manner.
        """
        read_buffer = ""
        start_time = time.time()

        self.command_history.append(
            "self.read_from_fona(" + str(response_timeout) + ")")

        if self.serial_connection is None:
            return "NOCON"

        # print "   starting read"
        while self.serial_connection.inWaiting() > 0:
            # print "******"
            read_buffer += self.serial_connection.read(1)
            time_elapsed = time.time() - start_time
            if time_elapsed > response_timeout:
                print "TIMEOUT"
                break

        # print "   done"
        return read_buffer

    def simple_terminal(self):
        """
        Simple interactive terminal to play with the Fona.
        """

        should_quit = False
        ret = []
        start_time = time.time()

        while not should_quit:
            try:
                command = str(input("READY:"))
                if command == "quit":
                    should_quit = True
                else:
                    ret.append(
                        "time.sleep(" + str(time.time() - start_time) + ")")
                    write_result = self.write_to_fona(command)
                    start_time = time.time()
                    print write_result

                    print self.read_from_fona(DEFAULT_RESPONSE_READ_TIMEOUT)
            except:
                print "ERROR"

        for command in self.command_history:
            print command

    def send_command(self, com, add_eol=True):
        """ send a command to the modem """
        command = com
        if add_eol:
            command += '\r\r\n '
        self.command_history.append(
            "self.send_command(" + escape(command) + ")")

        if self.serial_connection is not None:
            self.serial_connection.write(command)
            time.sleep(2)

        ret = []

        # print "Starting read/wait"
        while self.serial_connection is not None and self.serial_connection.inWaiting() > 0:
            msg = self.serial_connection.readline().strip()
            msg = msg.replace("\r", "")
            msg = msg.replace("\n", "")
            if msg != "":
                print msg
                ret.append(msg)
        return ret

    def disable_verbose_errors(self):
        """
        Disables verbose errors.
        Required for AT+CMGS to work.
        """
        return self.send_command("AT+CMEE=0")

    def enable_verbose_errors(self):
        """
        Enables trouble shooting errors.
        """
        return self.send_command("AT+CMEE=2")

    def get_carrier(self):
        """
        Returns the carrier.
        """
        return self.send_command("AT+COPS?")

    def get_signal_strength(self):
        """
        Returns an object representing the signal strength.
        """
        command_result = self.send_command("AT+CSQ")
        if command_result is None or len(command_result) < 2:
            command_result = None
        else:
            command_result = command_result[1]

        return SignalStrength(command_result)

    def get_current_battery_condition(self):
        """
        Returns an object representing the current battery state.
        """
        print "Sending CBC command"
        time.sleep(5)
        command_result = self.send_command("AT+CBC")

        for result in command_result:
            if "CBC:" in result:
                return BatteryCondition(result)

        return BatteryCondition(None)

    def get_module_name(self):
        """
        Returns the name of the GSM module.
        """
        return self.send_command("ATI")

    def get_sim_card_number(self):
        """
        Returns the id of the sim card.
        """
        return self.send_command("AT+CCID")

    def set_sms_mode(self):
        """
        Puts the card into SMS mode.
        """
        return self.send_command("AT+CMGF=1")

    def is_message_waiting(self):
        """
        Uses the GPIO pin to see if a message is waiting.
        """

        size = self.__message_waiting_queue__.qsize()

        if size > 0:
            print "qsize()=" + str(size)

        return size > 0

    def get_message(self, index):
        """
        Returns the message at the given index.
        """

        print "get_message(" + str(index) + ")"

        self.set_sms_mode()
        return self.send_command('AT+CMGL=' + index + '')

    def get_all_messages(self):
        """
        Returns the raw result of ALL the messages on the card.
        """

        print "get_all_messages()"

        self.set_sms_mode()
        return self.send_command('AT+CMGL="ALL"')

    def read_until_text(self, text):
        """
        Reads from the fona until the text is found.
        """

        read_text = ""
        start_time = time.time()

        while text not in read_text:
            self.wait_for_command_response()
            read_text += self.read_from_fona(2)
            elapsed_time = time.time() - start_time

            if elapsed_time > 10:
                print "TIMEOUT"
                break

        return read_text

    def wait_for_command_response(self):
        """
        Waits until the command has a response
        """
        self.command_history.append("self.wait_until_fona_command_response()")

        if self.serial_connection is None:
            return False

        start_time = time.time()
        while time.time() - start_time < 2 and self.serial_connection.inWaiting() < 1:
            time.sleep(0.5)

        return self.serial_connection.inWaiting() > 0

    def send_message(self, message_num, text):
        """
        Sends a message to the specified phone numbers.
        """

        cleaned_number = get_cleaned_phone_number(message_num)

        if cleaned_number is None or text is None:
            return

        print "Setting receiving number..."
        self.set_sms_mode()
        self.write_to_fona('\r\r\n')
        if self.wait_for_command_response:
            print self.read_from_fona(5)
        self.write_to_fona('AT+CMGS="' + cleaned_number + '"')
        self.wait_for_command_response()
        print self.read_from_fona(5)
        self.write_to_fona('\r')
        self.wait_for_command_response()
        print self.read_from_fona(5)
        print self.write_to_fona(text + '\x1a')
        self.wait_for_command_response()

        self.command_history.append("self.read_from_fona()")
        print self.read_from_fona(2)
        print "Check phone"

        return True

    def get_messages(self, source="UNKNOWN"):
        """
        Reads text messages on the SIM card and returns
        a list of messages with three fields: id, num, message.
        """

        if self.serial_connection is None:
            return []

        # put into SMS mode
        print "Checking for messages due to " + source

        self.set_sms_mode()
        # get all text messages currently on SIM Card
        self.serial_connection.write('AT+CMGL="ALL"\r')
        time.sleep(3)
        messages = []
        while self.serial_connection.inWaiting() > 0:
            message_header = self.serial_connection.readline().strip()
            if "+CMGL:" in message_header:
                message_text = self.serial_connection.readline().strip()

                new_message = SmsMessage(message_header,
                                         message_text)
                messages.append(new_message)

                time.sleep(1)

        self.__clear_messages_waiting_queue__()

        return messages

    def delete_message(self, message_to_delete, confirmation=True):
        """
        Deletes a message with the given Id.
        """
        self.send_command("AT+CMGD=" + str(message_to_delete.message_id))

        if confirmation is True:
            conf_number = get_cleaned_phone_number(
                message_to_delete.sender_number)

            if conf_number in self.allowednumbers:
                self.send_message(conf_number,
                                  "Message received: " + message_to_delete.message_text)

    def delete_messages(self, confirmation=True):
        """ Deletes any messages. """
        messages = self.get_messages("delete_messages")
        messages_deleted = 0
        for message_to_delete in messages:
            messages_deleted += 1
            self.delete_message(message_to_delete, confirmation)

        return messages_deleted

    def __clear_messages_waiting_queue__(self):
        """
        Clears the queue that tells us if we should check for
        messages.
        """

        events_cleared = 0
        while not self.__message_waiting_queue__.empty():
            print "Clearing queue."
            event = self.__message_waiting_queue__.get()
            events_cleared += 1
            print "Q:" + event

        return events_cleared


if __name__ == '__main__':
    import serial

    if not local_debug.is_debug():
        PHONE_NUMBER = "2066795094" # input("Phone number>")
    else:
        PHONE_NUMBER = "2061234567"

    if local_debug.is_debug():
        SERIAL_CONNECTION = None
    else:
        SERIAL_CONNECTION = serial.Serial('/dev/ttyUSB0', 9600)

    FONA = Fona(SERIAL_CONNECTION,
                DEFAULT_POWER_STATUS_PIN,
                DEFAULT_RING_INDICATOR_PIN,
                {PHONE_NUMBER})

    if not FONA.is_power_on():
        print "Power is off.."
        exit()

    # fona.get_carrier()
    BATTERY_CONDITION = FONA.get_current_battery_condition()
    # FONA.send_message(PHONE_NUMBER, "Time:" + str(time.time()) + "\nPCT:" +
    #                   str(BATTERY_CONDITION.battery_percent)
    #                   + "\nmAH:" + str(BATTERY_CONDITION.milliamp_hours))
    # print "Signal strength:"
    SIGNAL_STRENGTH = FONA.get_signal_strength()
    print "Signal:" + SIGNAL_STRENGTH.classify_strength()
    # print fona.get_module_name()
    # print fona.get_sim_card_number()

    while True:
        if FONA.is_message_waiting():
            print "Message waiting.."

            for message in FONA.get_messages("self_test"):
                print "ID:" + message.message_id
                print "Date:" + message.message_date
                print "Time:" + message.message_time
                print "Num:" + message.sender_number
                print "Stat:" + message.message_status
                print "SMS:" + message.message_text

            FONA.delete_messages(False)

    # fona.get_messages(False)
