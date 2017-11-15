""" Module to help with tha AdaFruit Fona modules """
import time


class Fona(object):
    """Class that send messages with an Adafruit Fona
    SERIAL_PORT, BAUDRATE, timeout=.1, rtscts=0
    Attributes:
    unauthorize numbers
    """

    def __init__(self, name, ser, allowednumbers):
        self.name = name
        self.ser = ser
        self.allowednumbers = allowednumbers

    def send_command(self, com):
        """ send a command to the modem """
        self.ser.write(com + "\r\n")
        time.sleep(2)
        ret = []
        while self.ser.inWaiting() > 0:
            msg = self.ser.readline().strip()
            msg = msg.replace("\r", "")
            msg = msg.replace("\n", "")
            if msg != "":
                ret.append(msg)
        return ret

    def send_message(self, message_num, text):
        """ send a message to the specified phone number """
        self.send_command("AT+CMGF=1")
        self.send_command('AT+CMGS=' + message_num)
        self.send_command(text + chr(26))
        time.sleep(5)

    def get_messages(self, confirmation=True):
        """ reads text messages on the SIM card and returns
		a list of messages with three fields: id, num, message """
        # put into SMS mode
        self.send_command("AT+CMGF=1")
        # get all text messages currently on SIM Card
        self.ser.write('AT+CMGL="ALL"\r')
        time.sleep(3)
        messages = []
        while self.ser.inWaiting() > 0:
            line = self.ser.readline().strip()
            if "+CMGL:" in line:
                message_details = []
                metadata_list = line.split(",")
                message_id = metadata_list[0]
                message_id = message_id.rpartition(":")[2].strip()
                message_num = metadata_list[2]

                message_details.append(message_id)
                message_details.append(message_num)
                message_line = self.ser.readline().strip()
                message_details.append(message_line)
                messages.append(message_details)

                # now that we read the message,remove it from the SIM card
                # self.sendCommand("AT+CMGD="+str(message_id))
                time.sleep(1)
        # now delete the messages since they have been read
        for message in messages:
            self.send_command("AT+CMGD=" + str(message[0]))
            if confirmation is True:
                phone_number = message[1].replace('"', '')
                phone_number = phone_number.replace("+", '')
                print phone_number
                if phone_number in self.allowednumbers:
                    self.send_message(
                        message[1], "Message Received: " + message[2])
        return messages

    def delete_messages(self):
        """ Deletes any messages. """
        messages = self.get_messages(confirmation=False)
        return len(messages)
