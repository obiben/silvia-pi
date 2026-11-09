#!/usr/bin/python
"""Drives the heating element relay from the PID output.

This process is the last line of software defence against a stuck-on element,
so it refuses to close the relay unless the sensor data is fresh and plausible,
independently of whatever the PID asks for:

  * freshness   - no heat if the last valid reading is older than STALE_AFTER
  * steam       - no heat above STEAM_TEMP_C, no fault: the steam switch bypasses
                  this relay and takes the boiler to ~140 C, so a reading up there
                  is normal. state['steam'] lights the icon on the chart.
  * floor       - no heat below MIN_TEMP_C (latched fault: sensor implausible)
  * rate of rise- near-full power for RISE_CHECK_SECONDS with less than
                  RISE_CHECK_MIN_DELTA of warming means a stuck sensor, dead
                  element or empty boiler (latched fault)

A latched fault sets state['fault'] and state['on'] = False and stays that way
until the toggle button clears it. The machine's own thermal cut-out remains the
final guard; this cannot catch a sensor that is stuck *near* the setpoint.
"""

from time import sleep, time
from datetime import datetime
import simulation  # must precede RPi import: swaps in the stub off the Pi
import RPi.GPIO as GPIO

from config import config
he_pins = config.he_pins
max_sleep = config.sample_time

import logging
logger = logging.getLogger('silvia.heat')

STALE_AFTER = 2.0            # seconds since the last valid reading before we stop heating
STEAM_TEMP_C = 105.0         # above this the boiler is steaming (or running away): relay stays open
MIN_TEMP_C = 5.0             # a reading this low means a broken sensor, not a cold kitchen
RISE_CHECK_SECONDS = 60.0    # at sustained power for this long...
RISE_CHECK_MIN_DELTA = 2.0   # ...the boiler must have warmed at least this much
RISE_CHECK_DROP = 1.0        # ...unless it cooled by this much (shot pulled, steam) - window restarts
RISE_CHECK_DUTY = 35.0       # "sustained power" = PID output at or above this percent (or boost).
                             # A Silvia holds temperature at 10-20%; 35% for a minute warms it by many degrees.


def _to_c(temp):
  return temp if config.celsius else (temp - 32.0) * 5.0 / 9.0


class Heat(object):
  def __init__(self, state):
    self._state = state
    self._stale_logged = False
    self._rise_window = None   # (start_time, start_temp) while at high duty
    self.setup()

  def setup(self):
    GPIO.setmode(GPIO.BCM)
    for pin in he_pins:
      GPIO.setup(pin, GPIO.OUT)
      GPIO.output(pin, 0)

  def cleanup(self):
    for pin in he_pins:
      GPIO.output(pin, 0)
    GPIO.cleanup()

  # ------------------------------------------------------------ safeguards

  def fault(self, reason):
    """Latch a fault: heat off, machine off, until the toggle button clears it."""
    if self._state.get('fault'):
      return
    logger.error('FAULT, heating disabled until toggled back on: %s', reason)
    self._state['fault'] = reason
    self._state['on'] = False
    self._rise_window = None

  def safe_to_heat(self, now):
    """False when the sensor data is missing, stale or implausible."""
    last = self._state.get('last_update') or 0
    if now - last > STALE_AFTER:
      if not self._stale_logged:
        if last:
          logger.warning('No valid sensor reading for %.1f s, heating withheld', now - last)
        else:
          logger.info('No sensor reading yet, heating withheld')
        self._stale_logged = True
      return False
    if self._stale_logged:
      logger.info('Sensor readings resumed')
      self._stale_logged = False

    temp_c = _to_c(self._state['temp'])
    steam = temp_c > STEAM_TEMP_C
    if steam != bool(self._state.get('steam')):
      self._state['steam'] = steam
      logger.info('Boiler %s %.0f C (%.1f C): relay %s', 'above' if steam else 'back below',
                  STEAM_TEMP_C, temp_c, 'held open' if steam else 'released')
    if steam:
      return False
    if temp_c < MIN_TEMP_C:
      self.fault('temperature %.1f C below %.0f C, sensor implausible' % (temp_c, MIN_TEMP_C))
      return False
    return True

  def check_rise(self, now, duty):
    """At high duty the boiler must keep warming; if it doesn't, something is wrong."""
    if duty < RISE_CHECK_DUTY:
      self._rise_window = None
      return
    temp = self._state['temp']
    if self._rise_window is None:
      self._rise_window = (now, temp)
      return
    t0, temp0 = self._rise_window
    if temp - temp0 >= RISE_CHECK_MIN_DELTA:
      self._rise_window = (now, temp)       # warming as expected, start a new window
    elif temp0 - temp >= RISE_CHECK_DROP:
      self._rise_window = (now, temp)       # cooling (shot, steam): the sensor is alive, restart
    elif now - t0 >= RISE_CHECK_SECONDS:
      self.fault('%.0f s at full power but only %.1f degrees of warming (stuck sensor, dead element or empty boiler?)'
                 % (now - t0, temp - temp0))

  # ------------------------------------------------------------------ relay

  def _relay(self, on):
    self._state['heating'] = bool(on)
    for pin in he_pins:
      GPIO.output(pin, 1 if on else 0)

  def run(self):
    logger.info('Heat control loop started')
    while True:
      now = time()

      # Check if snooze is over
      if self._state['snoozeon'] == True:
        dt = datetime.strptime(self._state['snooze'], '%H:%M')
        n = datetime.now()
        if dt.hour == n.hour and dt.minute == n.minute:
          self._state['snoozeon'] = False

      if self._state['snoozeon'] or not self._state['on']:
        self._relay(0)
        self._state['steam'] = False
        self._rise_window = None
        sleep(1)
        continue

      if not self.safe_to_heat(now):
        self._relay(0)
        self._rise_window = None
        sleep(max_sleep)
        continue

      boost = now < self._state['boost']
      duty = 100.0 if boost else max(0.0, min(100.0, float(self._state['pidval'] or 0.0)))
      self.check_rise(now, duty)
      if self._state.get('fault'):
        self._relay(0)
        continue

      if duty >= 100.0:
        self._relay(1)
        sleep(max_sleep)
      elif duty > 0.0:
        # Heat for duty% of the sample period, rest for the remainder
        self._relay(1)
        on_time = max_sleep * (duty / 100.0)
        sleep(on_time)
        self._relay(0)
        sleep(max_sleep - on_time)
      else:
        self._relay(0)
        sleep(max_sleep)
