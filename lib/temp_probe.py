""" Module to deal with the SunFounder temperature probe. """

import os
import time

#----------------------------------------------------------------
#	Note:
#		ds18b20's data pin must be connected to pin7.
#
# The following steps must be taken from the kernel to make sure
# probe is ready for use.
# sudo modprobe w1-gpio
# sudo modprobe w1-therm
#----------------------------------------------------------------

# Modified from SunFounder's page at
# https://www.sunfounder.com/learn/Sensor-Kit-v1-0-for-Raspberry-Pi/lesson-17-ds18b20-temperature-sensor-sensor-kit-v1-0-for-pi.html

def read_sensor(sensor_id):
    """ Reads temperature from sensor and prints to stdout
    id is the id of the sensor. """
    tfile = open("/sys/bus/w1/devices/" + sensor_id + "/w1_slave")
    text = tfile.read()
    tfile.close()
    secondline = text.split("\n")[1]
    temperaturedata = secondline.split(" ")[9]
    temperature = float(temperaturedata[2:])
    temperature = temperature / 1000
    print "Sensor: " + sensor_id + " - Current temperature : %0.3f C" % temperature

    return temperature

def read_sensors():
    """ Reads temperature from all sensors found in /sys/bus/w1/devices/
    starting with "28-... """
    temperature_probe_values = []

    for driver_file in os.listdir("/sys/bus/w1/devices/"):
        if driver_file.startswith("28-"):
            try:
                temperature_probe_values.append(read_sensor(driver_file))
            except:
                print "Failed to read sensor"

    if temperature_probe_values.count == 0:
        print "No sensors found! Check connection"

    return temperature_probe_values

def loop():
    """ read temperature every second for all connected sensors """
    while True:
        read_sensors()
        time.sleep(1)

# Nothing to cleanup
def destroy():
    """ Tears down the  object. """
    pass


# Main starts here
if __name__ == "__main__":
    try:
        loop()
    except KeyboardInterrupt:
        destroy()
