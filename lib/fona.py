""" Module to help with tha AdaFruit Fona modules """
import time

SECONDS_TO_WAIT_AFTER_SEND = 5
BATTERY_CRITICAL = 40
BATTERY_WARNING = 60
DEFAULT_RESPONSE_READ_TIMEOUT = 5


class Battery_Condition:
    """
    Class to keep the battery state.
    """

    def is_battery_ok(self):
        """
        Is the battery OK?
        """
        return self.battery_percent

    def __init__(self, command_result):
        """
        Initialize.
        """
        self.error_state = False

        if command_result is None or len(command_result) < 1:
            self.error_state = True
        else:
            tokens = command_result.split(':')
        
            if tokens is None or len(tokens) <=1:
                self.error_state = True

            results = tokens[1].split(',')

            if results is None or len(results) <= 2:
                self.error_state = True

        if not self.error_state:
            self.charge_state = float(results[0])
            self.battery_percent =float(results[1])
            self.milliamp_hours = float(results[2]) / 10.0
        else:
            self.charge_state = 0
            self.battery_percent = 0
            self.milliamp_hours = 0

class Signal_Strength(object):
    """
    Class to hold the signal strength.
    """

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

        if self.received_signal_strength <= 19:
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
            self.received_signal_strength = 0
            self.bit_error_rate = 0

class Sms_Message(object):
    """
    Class to abstract a text message.
    """

    def __init__(self,
                 message_id,
                 message_status,
                 sender_number,
                 message_date,
                 message_time,
                 message_text):
        """
        Create the object.
        """

        self.message_id = message_id
        self.message_date = message_date
        self.message_time = message_time
        self.sender_number = sender_number
        self.message_status = message_status
        self.message_text = message_text


class Fona(object):
    """
    Class that send messages with an Adafruit Fona
    SERIAL_PORT, BAUDRATE, timeout=.1, rtscts=0
    Attributes:
    unauthorize numbers
    """

    def __init__(self, name, ser, allowednumbers):
        self.name = name
        self.command_history = []
        self.serial_connection = ser
        self.serial_connection.flushInput()
        self.serial_connection.flushOutput()
        self.allowednumbers = allowednumbers
        self.send_command("AT")
        #self.send_command("AE0")
        self.disable_verbose_errors()
        self.set_sms_mode()

        print self.read_from_fona(10)

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

        self.command_history.append("self.write_to_fona(" + self.escape(text) + ")")

        # print "Checking return"
        # print "Wrote " + str(num_bytes_written) + ", expected " + str(len(text))

        self.wait_until_fona_command_response()

        return num_bytes_written

    def read_from_fona(self, response_timeout=2):
        """
        Read back from the Fona in a safe manner.
        """
        read_buffer = ""
        start_time = time.time()

        self.command_history.append("self.read_from_fona(" + str(response_timeout) + ")")

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
                    ret.append("time.sleep(" + str(time.time() - start_time) + ")")
                    write_result = self.write_to_fona(command)
                    start_time = time.time()
                    print write_result

                    print self.read_from_fona(DEFAULT_RESPONSE_READ_TIMEOUT)
            except error:
                print "ERROR:" + str(error)
            
        for command in self.command_history:
            print command

    def escape(self, text):
        """
        Replaces escape sequences do they can be printed.
        """
        return text.replace('\r', '\\r').replace('\n', '\\n').replace('\x1a','\\x1a')


    def send_command(self, com, add_eol=True):
        """ send a command to the modem """
        command = com
        if add_eol:
            command += '\r\r\n '
        self.command_history.append("self.send_command(" + self.escape(command) + ")")
        self.serial_connection.write(command)
        time.sleep(2)
        ret = []

        # print "Starting read/wait"
        while self.serial_connection.inWaiting() > 0:
            msg = self.serial_connection.readline().strip()
            msg = msg.replace("\r", "")
            msg = msg.replace("\n", "")
            if msg != "":
                print msg
                ret.append(msg)
        return ret

    def disable_verbose_errors(self):
        return self.send_command("AT+CMEE=0")

    def enable_verbose_errors(self):
        return self.send_command("AT+CMEE=2")

    def get_carrier(self):
        return self.send_command("AT+COPS?")

    def get_signal_strength(self):
        command_result = self.send_command("AT+CSQ")
        if command_result is None or len(command_result) < 2:
            command_result = None
        else:
            command_result = command_result[1]

        return Signal_Strength(command_result)

    def get_current_battery_condition(self):
        command_result = self.send_command("AT+CBC")
        if command_result is None or len(command_result) < 2:
            command_result = None
        else:
            command_result = command_result[1]

        return Battery_Condition(command_result)

    def get_module_name(self):
        return self.send_command("ATI")

    def get_sim_card_number(self):
        return self.send_command("AT+CCID")

    def set_sms_mode(self):
        return self.send_command("AT+CMGF=1")

    def get_message(self, index):
        self.set_sms_mode()
        return self.send_command('AT+CMGL=' + index + '')

    def get_all_messages(self):
        self.set_sms_mode()
        return self.send_command('AT+CMGL="ALL"')

    def clean_phone_number(self, phone_number):
        """
        Removes any text from the phone number that
        could cause the command to not work.
        """
        if phone_number:
            return phone_number.replace('+', '').replace('(', '').replace(')',
                '').replace('-', '')

        return None

    def read_until_text(self, text):
        """
        Reads from the fona until the text is found.
        """

        read_text = ""
        start_time = time.time()

        while text not in read_text:
            self.wait_until_fona_command_response()
            read_text += self.read_from_fona(2)
            elapsed_time = time.time() - start_time

            if elapsed_time > 10:
                print "TIMEOUT"
                break

        return read_text

    def wait_until_fona_command_response(self):
        """
        Waits until the command has a response
        """
        self.command_history.append("self.wait_until_fona_command_response()")
        start_time = time.time()
        while time.time() - start_time < 2 and self.serial_connection.inWaiting() < 1:
            time.sleep(0.5)

        return self.serial_connection.inWaiting() > 0

    def send_message(self, message_num, text):
        """
        Sends a message to the specified phone numbers.
        """

        cleaned_number = self.clean_phone_number(message_num)

        if cleaned_number is None or text is None:
            return

        print "Setting receiving number..."
        self.set_sms_mode()
        self.write_to_fona('\r\r\n')
        if self.wait_until_fona_command_response:
            print self.read_from_fona(5)
        self.write_to_fona('AT+CMGS="' + cleaned_number + '"')
        self.wait_until_fona_command_response()
        print self.read_from_fona(5)
        self.write_to_fona('\r')
        self.wait_until_fona_command_response()
        print self.read_from_fona(5)
        print self.write_to_fona(text + '\x1a')
        self.wait_until_fona_command_response()

        self.command_history.append("self.read_from_fona()")
        print self.read_from_fona(2)
        print "Check phone"


        return True

    def get_messages(self):
        """
        Reads text messages on the SIM card and returns
        a list of messages with three fields: id, num, message.
        """

        # put into SMS mode
        self.set_sms_mode()
        # get all text messages currently on SIM Card
        self.serial_connection.write('AT+CMGL="ALL"\r')
        time.sleep(3)
        messages = []
        while self.serial_connection.inWaiting() > 0:
            line = self.serial_connection.readline().strip()
            if "+CMGL:" in line:
                message_details = []
                metadata_list = line.split(",")
                message_id = metadata_list[0]
                message_status = metadata_list[1]
                message_id = message_id.rpartition(":")[2].strip()
                message_num = metadata_list[2]
                message_date = metadata_list[4]
                message_time = metadata_list[5]

                message_details.append(message_id)
                message_details.append(message_num)
                message_line = self.serial_connection.readline().strip()
                message_details.append(message_line)

                new_message = Sms_Message(message_id,
                                          message_status,
                                          message_num,
                                          message_date,
                                          message_time,
                                          message_line)
                messages.append(new_message)

                time.sleep(1)
        return messages

    def delete_messages(self, confirmation=True):
        """ Deletes any messages. """
        messages = self.get_messages(confirmation=False)
        messages_deleted = 0
        for message in messages:
            messages_deleted += 1
            self.send_command("AT+CMGD=" + str(message.message_id))

            if confirmation is True:
                phone_number = message.sender_number.replace('"', '')
                phone_number = phone_number.replace("+", '')
                print phone_number
                if phone_number in self.allowednumbers:
                    self.send_message(
                            message.sender_number,
                            "Message Received: " + message.message_text)

        return messages_deleted


if __name__ == '__main__':
    import serial
    phone_number = input("Phone number>")
    allowed_numbers = {phone_number, '18558655971'}
    serial_connection = serial.Serial('/dev/ttyUSB0', 9600)
    fona = Fona("Fona", serial_connection, allowed_numbers)
    # fona.get_carrier()
    battery_condition = fona.get_current_battery_condition()
    # fona.send_message(phone_number, "Time:" + str(time.time())
    #                                + ", PCT:" + str(battery_condition.battery_percent)
    #                                + ", mAH:" + str(battery_condition.milliamp_hours))
    # print "Signal strength:"
    signal_strength = fona.get_signal_strength()
    print "Signal:" + signal_strength.classify_strength()
    # print fona.get_module_name()
    # print fona.get_sim_card_number()
    print fona.get_all_messages()

    for message in fona.get_messages():
        print "ID:" + message.message_id
        print "Date:" + message.message_date
        print "Time:" + message.message_time
        print "Num:" + message.sender_number
        print "Stat:" + message.message_status
        print "SMS:" + message.message_text

    # fona.get_messages(False)
