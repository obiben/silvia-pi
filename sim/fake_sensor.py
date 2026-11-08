"""Boiler model standing in for the MAX31865 + PT100 when running off the Pi.

Reads state['heating'] (set by the heat process) and integrates a crude
first-order thermal model: the element adds heat, the boiler loses some to the
room in proportion to how hot it is. Numbers are rough but give a Silvia-like
warm-up of about a degree a second and a realistic overshoot to tune against.
"""
import random
from time import sleep, time

AMBIENT = 22.0
HEAT_RATE = 1.2       # degC per second with the element on
LOSS_RATE = 0.012     # fraction of (T - ambient) lost per second
NOISE = 0.05          # degC of read noise
OUTLIER_CHANCE = 0.0  # set e.g. 0.01 to exercise the outlier filter


class FakeSensor(object):
  def __init__(self, state):
    self._state = state
    self._temp = 90
    self._last = time()

  def readTemp(self):
    sleep(0.1)  # the real chip needs ~100 ms per one-shot conversion
    now = time()
    dt = now - self._last
    self._last = now

    heating = bool(self._state.get('heating', False))
    if heating:
      self._temp += HEAT_RATE * dt
    self._temp -= LOSS_RATE * (self._temp - AMBIENT) * dt

    if OUTLIER_CHANCE and random.random() < OUTLIER_CHANCE:
      return self._temp + random.choice([-40.0, 40.0])
    return self._temp + random.gauss(0, NOISE)
