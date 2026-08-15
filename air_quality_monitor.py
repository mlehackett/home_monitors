# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

"""
Example sketch to connect to PM2.5 sensor with either I2C or UART.
"""

import os
from os import getenv

import board
import pulseio
import time
from adafruit_ticks import ticks_ms, ticks_add, ticks_less

import adafruit_connection_manager
import adafruit_requests
import microcontroller
import wifi
from simpleio import map_range

import busio
from digitalio import DigitalInOut, Direction, Pull
import analogio

from adafruit_io.adafruit_io import IO_HTTP
from utilities import io_retry

from adafruit_pm25.i2c import PM25_I2C
import adafruit_ahtx0
import neopixel

SAMPLE_RATE = 10 # seconds between readings
ROLLING_RATE = 2*60 # seconds of history in rolling averages
UPDATE_RATE = 2*60 # seconds between internet updates
update_pulse = int(UPDATE_RATE/SAMPLE_RATE)

AQI_PIXELS = 6
CHARGER_PIXEL = 0
NETWORK_PIXEL = 1

red=(255, 0, 0)
green=(0, 255, 0)
blue=(0, 0, 255)
orange=(255, 69, 0)
yellow=(255, 255, 0)
maroon=(50, 0, 250)
purple=(150, 0, 150)
off = (0,0,0)

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

# Get or create feeds
def open_feeds():
    global aqi_group
    global log_feed
    global pm25_feed
    global pm10_feed
    global pm100_feed
    global temp_feed
    global humidity_feed
    global level_feed
    global details_feed
    aqi_group = io.get_group("aqi")
    log_feed = io.get_feed("aqi.log")
    pm25_feed = io.get_feed("aqi.pm25")
    pm10_feed = io.get_feed("aqi.pm10")
    pm100_feed = io.get_feed("aqi.pm100")
    temp_feed = io.get_feed("aqi.temp")
    humidity_feed = io.get_feed("aqi.humidity")
    level_feed = io.get_feed("aqi.level")
    details_feed = io.get_feed("aqi.details")

def open_or_create_feeds():
    try: 
        open_feeds()
    except:
        aqi_group = io.create_new_group("aqi", "data for air quality monitoring")
        
        # Create the feeds in the group
        print("Creating feeds inside group...")
        io.create_feed_in_group(aqi_group["key"], "log")
        io.create_feed_in_group(aqi_group["key"], "pm25")
        io.create_feed_in_group(aqi_group["key"], "pm10")
        io.create_feed_in_group(aqi_group["key"], "pm100")
        io.create_feed_in_group(aqi_group["key"], "temp")
        io.create_feed_in_group(aqi_group["key"], "humidity")
        io.create_feed_in_group(aqi_group["key"], "level")
        io.create_feed_in_group(aqi_group["key"], "details")
        
        open_feeds()

# Logging or posting functions
def send_to_log(message, feed):
    print(message)
    io.send_data(feed["key"], message)

def send_data(avg_pm25, avg_pm10, avg_pm100, temp, humidity, level):
    io.send_group_data(
        group_key=aqi_group["key"],
        feeds_and_data=[
            {"key": "pm25", "value": avg_pm25},
            {"key": "pm10", "value": avg_pm10},
            {"key": "pm100", "value": avg_pm100},
            {"key": "temp", "value": temp},
            {"key": "humidity", "value": humidity},
            {"key": "level", "value": level},
        ]
    )

def send_details(aqdata):
    summary = "\n".join([
        f"Particles > 0.3um / 0.1L air: {aqdata['particles 03um']}",
        f"Particles > 0.5um / 0.1L air: {aqdata['particles 05um']}",
        f"Particles > 1.0um / 0.1L air: {aqdata['particles 10um']}",
        f"Particles > 2.5um / 0.1L air: {aqdata['particles 25um']}",
        f"Particles > 5.0um / 0.1L air: {aqdata['particles 50um']}",
        f"Particles > 10 um / 0.1L air: {aqdata['particles 100um']}",
    ])
    io.send_data(details_feed["key"], summary)

def send_parameters_to_log():
    message = "\n".join([
        f"Seconds between samples: {SAMPLE_RATE}",
        f"Seconds of history in rolling average: {ROLLING_RATE}",
        f"Seconds between internet uploads: {UPDATE_RATE}",
    ])
    io.send_data(log_feed["key"], message)

def print_aq_data(aqdata):
    print()
    print("Concentration Units (standard)")
    print("---------------------------------------")
    print(
        "PM 1.0: %d\tPM2.5: %d\tPM10: %d"
        % (aqdata["pm10 standard"], aqdata["pm25 standard"], aqdata["pm100 standard"])
    )
    print("Concentration Units (environmental)")
    print("---------------------------------------")
    print(
        "PM 1.0: %d\tPM2.5: %d\tPM10: %d"
        % (aqdata["pm10 env"], aqdata["pm25 env"], aqdata["pm100 env"])
    )
    print("---------------------------------------")
    print("Particles > 0.3um / 0.1L air:", aqdata["particles 03um"])
    print("Particles > 0.5um / 0.1L air:", aqdata["particles 05um"])
    print("Particles > 1.0um / 0.1L air:", aqdata["particles 10um"])
    print("Particles > 2.5um / 0.1L air:", aqdata["particles 25um"])
    print("Particles > 5.0um / 0.1L air:", aqdata["particles 50um"])
    print("Particles > 10 um / 0.1L air:", aqdata["particles 100um"])
    print("---------------------------------------")

# Helper functions
def celsius_to_fahrenheit(c):
    return (c * 9/5) + 32

def get_brightness(pot):
    return (pot-2819)/59320

class runningAverage:
    def __init__(self, sample_size):
        self.data = []
        self.sample_size = sample_size

    def update(self, new_point):
        self.data.append(new_point)
        while len(self.data) > self.sample_size:
            del(self.data[0])
        return sum(self.data)/len(self.data)
        
# AQI Definitions
class epaLevel:
    def __init__(self, label, upper_limit, color, count):
        self.label = label
        self.upper_limit = upper_limit
        self.color = color
        self.count = count
        
EPA_LEVELS = [
    epaLevel("Good", 12.0, green, 1),
    epaLevel("Moderate", 35.0, yellow, 2),
    epaLevel("Unhealthy for Sensitive Groups", 55.0, orange, 3),
    epaLevel("Unhealthy", 150.0, red, 4),
    epaLevel("Very Unhealthy", 250.0, purple, 5),
    epaLevel("Hazardous", 9999.9, maroon, 6)
]

def find_epa_level(pm25):
    for level in EPA_LEVELS:
        if pm25 < level.upper_limit:
            return level
    return EPA_LEVELS[-1]

# Set up the hardware
pixels = neopixel.NeoPixel(board.D15, 8, brightness=0.4)

# Set up io
try:
    open_or_create_feeds()
except:  # wifi or AIO failure
    while True:
        pixels[NETWORK_PIXEL] = red
        time.sleep(0.5)
        pixels[NETWORK_PIXEL] = off
        time.sleep(0.5)



reset_pin = None

uart = busio.UART(board.TX, board.RX, baudrate=9600)
from adafruit_pm25.uart import PM25_UART
pm25 = PM25_UART(uart, reset_pin)

i2c = board.I2C()  # For using the built-in STEMMA QT connector on a microcontroller
sensor = adafruit_ahtx0.AHTx0(i2c)

pot = analogio.AnalogIn(board.A4)

pgood = DigitalInOut(board.D13)
pgood.direction = Direction.INPUT
pgood.pull = Pull.UP

charge = DigitalInOut(board.D12)
charge.direction = Direction.INPUT
charge.pull = Pull.UP

pm25_env = runningAverage(ROLLING_RATE/SAMPLE_RATE)
pm10_env = runningAverage(ROLLING_RATE/SAMPLE_RATE)
pm100_env = runningAverage(ROLLING_RATE/SAMPLE_RATE)

pixels[NETWORK_PIXEL] = blue  # health check that we've made it this far, and no upload has been done yet.
send_parameters_to_log()

while True:
    for i in range(update_pulse):
        print(f"iteration {i} of {update_pulse}")

        # Power management
        if not charge.value: # battery is charging
            pixels[CHARGER_PIXEL] = red
        elif not pgood.value: # battery is full, power connected
            pixels[CHARGER_PIXEL] = green
        else: # running off battery
            pixels[CHARGER_PIXEL] = off 

        # Temp and Humidity    
        temp_f = celsius_to_fahrenheit(sensor.temperature)
        humidity = sensor.relative_humidity
        print("\nTemperature: %0.1f F" % temp_f)
        print("Humidity: %0.1f %%" % humidity)
    
        # AQI
        try:
            aqdata = pm25.read()
            print_aq_data(aqdata)
            avg_pm25 = pm25_env.update(aqdata["pm25 env"])
            avg_pm10 = pm10_env.update(aqdata["pm10 env"])
            avg_pm100 = pm100_env.update(aqdata["pm100 env"])
            level = find_epa_level(avg_pm25)
            print(level.label, "(", avg_pm25, ")")
            pixels[8 - AQI_PIXELS:] = [off]*AQI_PIXELS
            pixels[8 - level.count:] = [level.color]*level.count
            # pixels[:AQI_PIXELS] = [off]*AQI_PIXELS
            # pixels[:level.count] = [level.color]*level.count
        except RuntimeError:
            print("Unable to read from sensor, retrying...")

        boot_time = ticks_ms()
        next_check = ticks_add(boot_time, SAMPLE_RATE * 1000)
        
        # Manual controls
        while ticks_less(ticks_ms(), next_check):
            pixels.brightness = get_brightness(pot.value)

    # Post the data
    print("Sending data...")
    pixels[NETWORK_PIXEL] = off
    try:
        send_data(avg_pm25, avg_pm10, avg_pm100, temp_f, humidity, level.label)
        send_details(aqdata)
    except Exception as e:
        print('**** ERROR writing ****')
        print('→', e)
        pixels[NETWORK_PIXEL] = red


