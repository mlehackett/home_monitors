import time
import board
import supervisor
import adafruit_adxl34x

import pwmio
from adafruit_motor import servo

import os
from os import getenv

import adafruit_connection_manager
import adafruit_requests
import microcontroller
import wifi
import neopixel

from adafruit_io.adafruit_io import IO_HTTP
from digitalio import DigitalInOut

# Get WiFi details and Adafruit IO keys, ensure these are setup in settings.toml
ssid = getenv("CIRCUITPY_WIFI_SSID")
password = getenv("CIRCUITPY_WIFI_PASSWORD")
aio_username = getenv("ADAFRUIT_AIO_USERNAME")
aio_key = getenv("ADAFRUIT_AIO_KEY")

### WiFi ###
status_pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
ssl_context = adafruit_connection_manager.get_radio_ssl_context(wifi.radio)
requests = adafruit_requests.Session(pool, ssl_context)

# Initialize an Adafruit IO HTTP API object
io = IO_HTTP(aio_username, aio_key, requests)

feed = io.get_feed("wakes.seconds")

FLAG_ANGLE = 100
FLAG_UP_FOR = 15*1000
SAMPLE_RATE = 1
SENSITIVITY = 18 # motion sensitivity
SWING = 10 # acceleration sensitivity

pwm = pwmio.PWMOut(board.D5, frequency=50)
servo = servo.Servo(pwm, min_pulse=750, max_pulse=2250)
servo.angle = 0

i2c = board.I2C()
accelerometer = adafruit_adxl34x.ADXL343(i2c)

accelerometer.enable_motion_detection(threshold=SENSITIVITY)

flag_time = supervisor.ticks_ms()
rocking = 0

def raise_flag(angle=FLAG_ANGLE, step_size=1):
    while abs(servo.angle - angle) > step_size:
        servo.angle +=step_size
        time.sleep(0.01)

def lower_flag():
    servo.angle = 0

def max_abs(seq):
    return max(abs(x) for x in seq)

while True:
    print("{} {} {}".format(*accelerometer.acceleration))
    if accelerometer.events["motion"] or max_abs(accelerometer.acceleration) > SWING:
        flag_time = supervisor.ticks_ms() + FLAG_UP_FOR
        rocking += SAMPLE_RATE
        raise_flag()

    if supervisor.ticks_ms() > flag_time:
        lower_flag()
        if rocking > 0:
            io.send_data(feed["key"], rocking)
            print("Rocked for ", rocking, "s.")
            rocking = 0

    time.sleep(SAMPLE_RATE)
