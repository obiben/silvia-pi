"""The four button actions, shared by the GPIO buttons (silvia-pi.py) and the
keyboard shortcuts of the simulated GUI (chart.py).

Normally: up/down nudge the target, boost heats for 5 s, power toggles the machine.
Holding the power button for HOLD_SECONDS opens the timer menu, where the same
buttons become +15 min / -15 min / next field / save and exit. The menu's last
row, update, pulls new code and restarts the service when the + button is pressed.
"""
import os
from time import time
import logging

from simulation import SIM
from config import config

logger = logging.getLogger('silvia.buttons')

BACKLIGHT_ON = 800
BACKLIGHT_DIM = 100

HOLD_SECONDS = 1.0                      # power button held this long opens the timer menu
STEP_MINUTES = 15
MENU_FIELDS = ['timer_on', 'timer_off', 'timer_enabled', 'update']   # state['menu'] indexes this


def _backlight(level):
  if not SIM:
    os.system('gpio -g pwm 18 %d' % level)


def init_backlight():
  if not SIM:
    os.system('gpio -g mode 18 pwm | gpio pwmc 1000 | gpio -g pwm 18 %d' % BACKLIGHT_ON)


def in_menu(state):
  return state.get('menu') is not None


def add_minutes(hhmm, delta):
  h, m = [int(x) for x in hhmm.split(':')]
  total = (h * 60 + m + delta) % (24 * 60)
  return '%02d:%02d' % (total // 60, total % 60)


def _menu_adjust(state, direction):
  field = MENU_FIELDS[state['menu']]
  if field == 'update':
    if direction > 0 and not state.get('update_request') and state.get('update_status') != 'updating...':
      logger.info('Update requested from the menu')
      state['update_request'] = True   # the main process does the pull (update.py)
    return
  if field == 'timer_enabled':
    state[field] = not state[field]
  else:
    state[field] = add_minutes(state[field], direction * STEP_MINUTES)
  logger.info('Timer menu: %s = %s', field, state[field])


def menu_save(state):
  config.timer_on = state['timer_on']
  config.timer_off = state['timer_off']
  config.timer_enabled = state['timer_enabled']
  config.save()
  state['menu'] = None
  logger.info('Timer saved: on at %s, off at %s, %s', state['timer_on'], state['timer_off'],
              'enabled' if state['timer_enabled'] else 'disabled')


def set_power(state, on, source='button'):
  """Turn the machine on or off, from the button or the timer."""
  if bool(on) == bool(state['on']):
    return
  if on and state.get('fault'):
    if source != 'button':
      logger.warning('%s: not turning on, a fault is latched: %s', source, state['fault'])
      return
    logger.warning('Fault cleared by toggle button: %s', state['fault'])
    state['fault'] = None
  state['on'] = bool(on)
  logger.info('Machine %s (%s)', 'on' if on else 'off', source)
  _backlight(BACKLIGHT_ON if on else BACKLIGHT_DIM)


def increase(state):
  if in_menu(state):
    return _menu_adjust(state, +1)
  logger.info("Increase button pressed")
  state['settemp'] += 0.2
  config.set_temp = state['settemp']
  config.save()


def decrease(state):
  if in_menu(state):
    return _menu_adjust(state, -1)
  logger.info("Decrease button pressed")
  state['settemp'] -= 0.2
  config.set_temp = state['settemp']
  config.save()


def toggle(state):
  logger.info("Toggle button pressed")
  set_power(state, not state['on'])


def boost(state):
  if in_menu(state):
    state['menu'] = (state['menu'] + 1) % len(MENU_FIELDS)
    return
  logger.info("Heating for 5 seconds")
  state['boost'] = time() + 5


# The power button acts on release so a press can be told from a hold:
# gpiozero fires when_held after HOLD_SECONDS, then when_released on letting go.
_held = False


def power_held(state):
  """Long press: open the timer menu."""
  global _held
  _held = True
  if not in_menu(state):
    state['menu'] = 0
    state['update_status'] = None
    logger.info('Timer menu opened')


def power_released(state):
  """Short press: toggle the machine, or save and leave the menu."""
  global _held
  if _held:
    _held = False
    return
  if in_menu(state):
    menu_save(state)
  else:
    toggle(state)
