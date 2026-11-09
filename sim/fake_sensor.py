"""Boiler model standing in for the MAX31865 + PT100 when running off the Pi.

Reads state['heating'] (set by the heat process) and integrates a crude
first-order thermal model: the element adds heat, the boiler loses some to the
room in proportion to how hot it is. Numbers are rough but give a Silvia-like
warm-up of about a degree a second and a realistic overshoot to tune against.

Sensor failures can be injected to exercise the safeguards in heat.py and
sensor.py, starting SILVIA_SIM_FAULT_AFTER seconds in (default 30):

  SILVIA_SIM_FAULT=stuck    reading freezes at its current value
  SILVIA_SIM_FAULT=nan      reading becomes NaN
  SILVIA_SIM_FAULT=spikes   random +/-40 degree outliers, 5% of readings
  SILVIA_SIM_FAULT=runaway  reading climbs 2 degrees/s regardless of the element
  SILVIA_SIM_FAULT=cold     reading drops to 0 degrees
  SILVIA_SIM_FAULT=steam    not a fault: the steam switch (which bypasses our relay) takes the
                            boiler to ~140 degrees and holds it there, as on the real machine
"""
import os
import random
from time import sleep, time

AMBIENT = 22.0
START_TEMP = float(os.environ.get('SILVIA_SIM_START', 90))   # boiler temperature at launch
HEAT_RATE = 1.2       # degC per second with the element on
LOSS_RATE = 0.002     # fraction of (T - ambient) lost per second (~0.15 degC/s at 98, ~12% steady duty)
NOISE = 0.05          # degC of read noise

FAULT = os.environ.get('SILVIA_SIM_FAULT', '').strip().lower()
FAULT_AFTER = float(os.environ.get('SILVIA_SIM_FAULT_AFTER', 30))


class FakeSensor(object):
  def __init__(self, state):
    self._state = state
    self._temp = START_TEMP
    self._last = time()
    self._t0 = time()
    self._frozen = None

  def readTemp(self):
    sleep(0.1)  # the real chip needs ~100 ms per one-shot conversion
    now = time()
    dt = now - self._last
    self._last = now

    heating = bool(self._state.get('heating', False))
    if heating:
      self._temp += HEAT_RATE * dt
    self._temp -= LOSS_RATE * (self._temp - AMBIENT) * dt

    reading = self._temp + random.gauss(0, NOISE)
    if FAULT and now - self._t0 >= FAULT_AFTER:
      return self._faulty(reading, now)
    return reading

  def _faulty(self, reading, now):
    since = now - self._t0 - FAULT_AFTER
    if FAULT == 'stuck':
      if self._frozen is None:
        self._frozen = reading
      return self._frozen
    if FAULT == 'nan':
      return float('nan')
    if FAULT == 'spikes':
      if random.random() < 0.05:
        return reading + random.choice([-40.0, 40.0])
      return reading
    if FAULT == 'runaway':
      return reading + since * 2.0
    if FAULT == 'cold':
      return 0.0 + random.gauss(0, NOISE)
    if FAULT == 'steam':
      return min(reading + since * 1.2, 140.0 + random.gauss(0, 0.5))
    return reading
