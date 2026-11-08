"""The four button actions, shared by the GPIO buttons (silvia-pi.py) and the
keyboard shortcuts of the simulated GUI (chart.py)."""
import os
from time import time
import logging

from simulation import SIM
from config import config

logger = logging.getLogger('silvia.buttons')

BACKLIGHT_ON = 800
BACKLIGHT_DIM = 100


def _backlight(level):
  if not SIM:
    os.system('gpio -g pwm 18 %d' % level)


def init_backlight():
  if not SIM:
    os.system('gpio -g mode 18 pwm | gpio pwmc 1000 | gpio -g pwm 18 %d' % BACKLIGHT_ON)


def increase(state):
  logger.info("Increase button pressed")
  state['settemp'] += 0.2
  config.set_temp = state['settemp']
  config.save()


def decrease(state):
  logger.info("Decrease button pressed")
  state['settemp'] -= 0.2
  config.set_temp = state['settemp']
  config.save()


def toggle(state):
  logger.info("Toggle button pressed")
  state['on'] = not state['on']
  _backlight(BACKLIGHT_ON if state['on'] else BACKLIGHT_DIM)


def boost(state):
  logger.info("Heating for 5 seconds")
  state['boost'] = time() + 5
