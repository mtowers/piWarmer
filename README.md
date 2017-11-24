# piWarmer
This is a Python scipt that controls an AC/DC relay attached to a Raspberry Pi with a space heater plugged in. There is an adafruit GSM Board that receives text messages using a Ting SIM card connected to the Raspberry Pi. When the Pi receives a text messgae it will turn the AC/DC relay on or off accordingly, thus powering the heater on or off. The following are a list of commands that can be sent to the Pi that will control the heater:

SMS Message | Action
------------ | -------------
ON | Turn the Relay/Heater on
OFF | Turn the Relay/Heater off
STATUS | Return status of the Relay/Heater (on or off)
SHUTDOWN | Shutdown the Pi


There is a configuration file, piWarmer.config that must be edited that contains phone numbers that are allowed to control the heater and a maximum time that the heater can run for if a "off" text messages is not received. Text messages can be upper or lowercase.

Use the piWarmer image (https://github.com/mdegrazia/piWarmer/releases)  for easy installation. See the Wiki (https://github.com/mdegrazia/piWarmer/wiki) for parts needed, assembly instructions and software installation instructions.

****piWarmer is to be used at your own risk****

## Additional Links And Setup Notes
** The MQ-2 needs to be installed with an analog-to-digital converted **
You need to enable I2C using `raspi-config`
You need to modprobe two modules for the temperature sensor to work `w1-gpio` and `w1-therm`

### MQ-2 Sensdor
https://tutorials-raspberrypi.com/configure-and-read-out-the-raspberry-pi-gas-sensor-mq-x/
http://www.learningaboutelectronics.com/Articles/MQ-2-smoke-sensor-circuit-with-raspberry-pi.php

### Temp Sensore
https://www.sunfounder.com/learn/Sensor-Kit-v1-0-for-Raspberry-Pi/lesson-17-ds18b20-temperature-sensor-sensor-kit-v1-0-for-pi.html

### Fona
https://learn.adafruit.com/adafruit-fona-808-cellular-plus-gps-breakout?view=all
https://learn.adafruit.com/adafruit-fona-mini-gsm-gprs-cellular-phone-module?view=all
https://learn.adafruit.com/adafruit-fona-mini-gsm-gprs-cellular-phone-module/handy-commands
https://cdn-learn.adafruit.com/downloads/pdf/adafruit-fona-mini-gsm-gprs-cellular-phone-module.pdf
