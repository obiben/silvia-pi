#!/usr/bin/python

from time import sleep, time
from datetime import datetime, timedelta
import simulation  # must precede RPi import: swaps in the stub off the Pi
import RPi.GPIO as GPIO

from config import config
he_pins = config.he_pins
max_sleep = config.sample_time

import logging
logger = logging.getLogger('silvia.heat')

class Heat(object):
  def __init__(self, state):
    self._state = state
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

  def run(self):
    heating = False
    logger.info('Heat control loop started')
    while True:
      # Check if snooze is over
      if self._state['snoozeon'] == True :
        now = datetime.now()
        dt = datetime.strptime(self._state['snooze'],'%H:%M')
        if dt.hour == now.hour and dt.minute == now.minute :
          self._state['snoozeon'] = False

      # Sleep if snoozing
      if self._state['snoozeon'] or not self._state['on']:
        self._state['heating'] = False
        for pin in he_pins:
          GPIO.output(pin,0)
        sleep(1)
      elif time() < self._state['boost']:
        self._state['heating'] = True
        for pin in he_pins:
          GPIO.output(pin, 1)
          sleep(1)
      else:
        avgpid = self._state['pidval'] or 0.

        # Full heat
        if avgpid >= 100 :
          self._state['heating'] = True
          for pin in he_pins:
            GPIO.output(pin, 1)
          sleep(max_sleep)
        # Heat for avgpid/100 seconds, sleep the rest of the second
        elif avgpid > 0 and avgpid < 100:
          self._state['heating'] = True
          for pin in he_pins:
            GPIO.output(pin, 1)
          on_time = max_sleep * (avgpid/100.)
          sleep(on_time)
          for pin in he_pins:
            GPIO.output(pin, 0)
          sleep(max_sleep - on_time)
          self._state['heating'] = False
        # Don't heat
        else:
          for pin in he_pins:
            GPIO.output(pin, 0)
          self._state['heating'] = False
          sleep(max_sleep)
