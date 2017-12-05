"""
Module to abstract handling and updating
the Fona in a thread safe way.
"""

import threading
import time
from multiprocessing import Queue as MPQueue

import lib.local_debug as local_debug
import lib.fona as fona
from lib.recurring_task import RecurringTask


class FonaManager(object):
    """
    Object to handle the Fona board and abstract
    away all the upkeep tasks associated with the board.

    Keeps message sending & reception on a single thread.

    Handles updating the signal strength, battery state,
    and other monitoring of the device.
    """

    CHECK_SIGNAL = "SIGNAL"
    CHECK_BATTERY = "BATTERY"
    CHECK_SIGNAL_INTERVAL = 60  # Once a minute
    CHECK_BATTERY_INTERVAL = 60 * 5  # Every five minutes
    DEFAULT_RETRY_ATTEMPTS = 4

    def is_power_on(self):
        """
        Is the Fona on?
        """

        return self.__fona__.is_power_on()

    def update(self):
        """
        Performs all of the processing of receiving,
        sending, and status....
        ... on a single thread...
        """

        self.__process_status_updates__()
        self.__process_send_messages__()

    def send_message(self,
                     phone_number,
                     text_message,
                     maximum_number_of_retries=DEFAULT_RETRY_ATTEMPTS):
        """
        Queues the message to be sent out.
        """

        self.__send_message_queue__.put(
            [phone_number, text_message, maximum_number_of_retries])

    def signal_strength(self):
        """
        Handles returning a cell signal status
        in a thread friendly manner.
        """

        return self.__current_signal_strength__

    def battery_condition(self):
        """
        Handles returning the battery status
        in a thread friendly manner.
        """

        return self.__current_battery_state__

    def is_message_waiting(self):
        """
        Is there a message waiting for us to unpack?
        """
        return self.__fona__.is_message_waiting()

    def get_messages(self):
        """
        Gets any messages from the Fona.
        """

        results = []
        try:
            results = self.__fona__.get_messages()
        except:
            exception_message = "ERROR fetching messages!"
            print exception_message
            self.__logger__.warning(exception_message)

        return results

    def delete_messages(self):
        """
        Deletes any messages from the Fona.
        """

        num_deleted = 0

        try:
            num_deleted = self.__fona__.delete_messages()
        except:
            exception_message = "ERROR deleting messages!"
            print exception_message
            self.__logger__.warning(exception_message)

        return num_deleted

    def delete_message(self, message_to_delete):
        """
        Deletes any messages from the Fona.
        """

        try:
            self.__fona__.delete_message(message_to_delete)
        except:
            exception_message = "ERROR deleting message!"
            print exception_message
            self.__logger__.warning(exception_message)

    def __update_battery_state__(self):
        """
        Updates the battery state.
        """
        self.__current_battery_state__ = self.__fona__.get_current_battery_condition()

    def __update_signal_strength__(self):
        """
        Updates the battery state.
        """

        self.__current_signal_strength__ = self.__fona__.get_signal_strength()

    def __process_status_updates__(self):
        """
        Handles updating the cell signal
        and battery status.
        """

        # Only perform these checks once per
        # update. This lets us clear the thread
        # faster and prevents redundant work.
        battery_checked = False
        signal_checked = False

        try:
            while not self.__update_status_queue__.empty():
                command = self.__update_status_queue__.get()

                if self.CHECK_BATTERY in command and not battery_checked:
                    self.__update_battery_state__()
                    battery_checked = True
                if self.CHECK_SIGNAL in command and not signal_checked:
                    self.__update_signal_strength__()
                    signal_checked = True
        except:
            exception_message = "ERROR updating signal & battery status!"
            print exception_message
            self.__logger__.warning(exception_message)


    def __process_send_messages__(self):
        """
        Handles sending any pending messages.
        """

        messages_to_retry = []
        try:
            while not self.__send_message_queue__.empty():
                message_to_send = self.__send_message_queue__.get()

                try:
                    self.__fona__.send_message(
                        message_to_send[0], message_to_send[1])
                except:
                    self.__logger__.warning(
                        "Exception servicing outgoing message.")

                    message_to_send[3] -= 1
                    if message_to_send[3] > 0:
                        messages_to_retry.append(message_to_send)
        except:
            self.__logger__.warning("Exception servicing outgoing queue")

        for message_to_retry in messages_to_retry:
            self.__logger__.warning(
                "Adding message back for up to" + str(message_to_retry[3]) + " more retries.")
            self.__send_message_queue__.put(message_to_retry)

    def __trigger_check_battery__(self):
        """
        Triggers the battery state to be checked.
        """

        self.__update_status_queue__.put(self.CHECK_BATTERY)

    def __trigger_check_signal__(self):
        """
        Triggers the signal to be checked.
        """

        self.__update_status_queue__.put(self.CHECK_SIGNAL)

    def __init__(self,
                 logger,
                 serial_connection,
                 power_status_pin,
                 ring_indicator_pin):
        """
        Initializes the Fona.
        """

        self.__logger__ = logger
        self.__fona__ = fona.Fona(serial_connection,
                                  power_status_pin,
                                  ring_indicator_pin)
        self.__current_battery_state__ = None
        self.__current_signal_strength__ = None
        self.__update_status_queue__ = MPQueue()
        self.__send_message_queue__ = MPQueue()

        # Update the status now as we dont
        # know how long it will be until
        # the queues are serviced.
        self.__update_battery_state__()
        self.__update_signal_strength__()

        RecurringTask("check_battery",
                      self.CHECK_BATTERY_INTERVAL,
                      self.__trigger_check_battery__,
                      self.__logger__)

        RecurringTask("check_signal",
                      self.CHECK_SIGNAL_INTERVAL,
                      self.__trigger_check_signal__,
                      self.__logger__)


if __name__ == '__main__':
    import serial

    PHONE_NUMBER = "2061234567"

    if local_debug.is_debug():
        SERIAL_CONNECTION = None
    else:
        SERIAL_CONNECTION = serial.Serial('/dev/ttyUSB0', 9600)

    FONA_MANAGER = FonaManager(None,
                               SERIAL_CONNECTION,
                               fona.DEFAULT_POWER_STATUS_PIN,
                               fona.DEFAULT_RING_INDICATOR_PIN)

    if not FONA_MANAGER.is_power_on():
        print "Power is off.."
        exit()

    # fona.get_carrier()
    BATTERY_CONDITION = FONA_MANAGER.battery_condition()
    FONA_MANAGER.send_message(PHONE_NUMBER,
                              "Time:" + str(time.time()) + "\nPCT:"
                              + str(BATTERY_CONDITION.battery_percent)
                              + "\nmAH:" + str(BATTERY_CONDITION.milliamp_hours))
    # print "Signal strength:"
    SIGNAL_STRENGTH = FONA_MANAGER.signal_strength()
    print "Signal:" + SIGNAL_STRENGTH.classify_strength()

    while True:
        print "W?:" + str(FONA_MANAGER.is_message_waiting())
        BATTERY_CONDITION = FONA_MANAGER.battery_condition()
        FONA_MANAGER.update()
        time.sleep(1)
    # print fona.get_module_name()
    # print fona.get_sim_card_number()
