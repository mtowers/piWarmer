""" Module to help with tha AdaFruit Fona modules """
import time

SECONDS_TO_WAIT_AFTER_SEND = 5


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
        self.serial_connection = ser
        self.allowednumbers = allowednumbers

    def send_command(self, com):
        """ send a command to the modem """
        self.serial_connection.write(com + "\r\r\n ")
        time.sleep(2)
        ret = []

        print "Starting read/wait"
        while self.serial_connection.inWaiting() > 0:
            msg = self.serial_connection.readline().strip()
            msg = msg.replace("\r", "")
            msg = msg.replace("\n", "")
            if msg != "":
                print msg
                ret.append(msg)
        return ret

    def enable_verbose_errors(self):
        return self.send_command("AT+CMEE=2")

    def get_carrier(self):
        return self.send_command("AT+COPS?")

    def get_signal_strength(self):
        return self.send_command("AT+CSQ")

    def get_battery_state(self):
        return self.send_command("AT+CBC")

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

    def send_message(self, message_num, text):
        """ send a message to the specified phone number """

        print "Starting send_message(" + message_num + ", " + text + ")"

        if message_num is None or text is None:
            return

        if not message_num.startswith('"+'):
            print "Adding AT command to number"
            message_num = '"+' + message_num + '"'

        self.set_sms_mode()
        print "Setting receiving number..."
        print self.send_command('AT+CMGS='
                                + message_num
                                + '\r\r\n'
                                + text
                                + "\x1a")
        # print "Sending text body"
        # print self.send_command(text + chr(26))
        print "sent."
        time.sleep(SECONDS_TO_WAIT_AFTER_SEND)
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
    allowed_numbers = {'2066795094', '18558655971'}
    serial_connection = serial.Serial('/dev/ttyUSB0', 9600)
    fona = Fona("Fona", serial_connection, allowed_numbers)
    print fona.enable_verbose_errors()
    print fona.get_carrier()
    print fona.get_battery_state()
    print fona.get_signal_strength()
    print fona.get_module_name()
    print fona.get_sim_card_number()
    print fona.get_all_messages()

    # for message in fona.get_messages():
    #    print "ID:" + message.message_id
    #    print "Date:" + message.message_date
    #    print "Time:" + message.message_time
    #    print "Num:" + message.sender_number
    #    print "Stat:" + message.message_status
    #    print "SMS:" + message.message_text

#   fona.get_messages(False)
#   print fona.send_message('2066795094', 'test')
