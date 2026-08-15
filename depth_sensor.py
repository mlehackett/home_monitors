import os
from os import getenv

import board
import pulseio
import time

import adafruit_connection_manager
import adafruit_requests
import microcontroller
import wifi
from simpleio import map_range

import neopixel
import adafruit_dht

from adafruit_io.adafruit_io import IO_HTTP
from digitalio import DigitalInOut

from utilities import io_retry

# Connect PW (pin 2 on sensor) to D12 or any digital input
pulse_in = pulseio.PulseIn(board.D25, maxlen=1)
pulse_in.pause()
pulse_in.clear()
pulse_in.resume()

dht_sensor = adafruit_dht.DHT11(board.D8)

US_PER_FEET = 58 * 30.48 # datasheet = 58/cm
SENSOR_CALIBRATION = 0.5 # empirically determined systematic error


MAX_VALID_PULSE = 60000
MIN_VALID_PULSE = 0
SAMPLE_INTERVAL = 1.0  # seconds
UPLOAD_INTERVAL = 10.0 # seconds
BUFFER_SIZE = int(SAMPLE_INTERVAL * UPLOAD_INTERVAL)



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

try: 
    depth_group = io.get_group("depth")
    log_feed = io.get_feed("depth.log")
    depth_feed = io.get_feed("depth.height")
    temp_feed = io.get_feed("depth.temp")
except:
    depth_group = io.create_new_group("depth", "a group of wake details")
    
    # Create the feeds in the group
    print("Creating feeds inside group...")
    io.create_feed_in_group(depth_group["key"], "height")
    io.create_feed_in_group(depth_group["key"], "temp")
    io.create_feed_in_group(depth_group["key"], "log")
    io.create_feed_in_group(depth_group["key"], "depth")
    
    depth_group = io.get_group("depth")
    log_feed = io.get_feed("depth.log")
    depth_feed = io.get_feed("depth.height")
    temp_feed = io.get_feed("depth.temp")

@io_retry("(LOG)", status_pixel)
def send_to_log(message, feed):
    print(message)
    io.send_data(feed["key"], message)

@io_retry("(DATA)", status_pixel, blink_delay=0.5)
def send_data(height, temp):
    io.send_group_data(
        group_key=depth_group["key"],
        feeds_and_data=[
            {"key": "height", "value": height},
            {"key": "temp", "value": temp}
        ]
    )

readings = []

def trimmed_mean(pulses, trim_ratio=0.05):
    n = len(pulses)
    if n == 0:
        return None
    pulses.sort()
    trim = int(n * trim_ratio)
    trimmed = pulses[trim : n - trim]
    if not trimmed:
        return None
    return sum(trimmed) / len(trimmed)

def read_pulse():
    try:
        pulse = pulse_in[0]
        print(pulse)
        return pulse
    except:
        return None

def read_temperature():
    try:
        temperature = dht_sensor.temperature * 9 / 5 + 32
        return temperature
    except RuntimeError as e:
        print("DHT read error:", e.args[0])
        return None
        
while True:
    readings = []
    while len(readings) < BUFFER_SIZE:
        time.sleep(SAMPLE_INTERVAL)
        readings.append(read_pulse())
    pulse_in.pause()
    readings = [p for p in readings if (p != None and p < MAX_VALID_PULSE)]
    avg_pulse = trimmed_mean(readings)
    try:
        height = (avg_pulse / US_PER_FEET) + SENSOR_CALIBRATION 
        send_to_log(f"{UPLOAD_INTERVAL} avg (trimmed): {height:.2f} ft ({len(readings)} samples used)\n", log_feed)
        temp = read_temperature()
        send_data(height, temp)
    except TypeError:
        send_to_log(f"No valid readings in last {UPLOAD_INTERVAL} seconds.", log_feed)
    pulse_in.clear()
    pulse_in.resume()
