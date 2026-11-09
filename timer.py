"""Switches the machine on and off at the times set in the timer menu.

Polled from the heat loop; each clock minute is acted on once, so a manual
press during that minute is not undone. Turning on is refused while a fault
is latched (see buttons.set_power).
"""
from datetime import datetime
import logging

import buttons

logger = logging.getLogger('silvia.timer')


class Timer(object):
  def __init__(self, state):
    self._state = state
    self._last_minute = None

  def check(self):
    state = self._state
    now = datetime.now().strftime('%H:%M')
    if now == self._last_minute:
      return
    self._last_minute = now
    if not state.get('timer_enabled'):
      return
    if now == state['timer_on']:
      logger.info('Timer: %s, turning on', now)
      buttons.set_power(state, True, 'timer')
    elif now == state['timer_off']:
      logger.info('Timer: %s, turning off', now)
      buttons.set_power(state, False, 'timer')
