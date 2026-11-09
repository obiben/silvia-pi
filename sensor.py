import sys
from time import sleep, time
from math import isnan
from simulation import SIM
import PID as PID
from config import config as conf

import logging
logger = logging.getLogger('silvia.sensor')

def c_to_f(c):
  return c * 9.0 / 5.0 + 32.0

def f_to_c(f):
  return (f-32) * 5. / 9.

class Sensor(object):
  def __init__(self, state):
    if SIM:
      from fake_sensor import FakeSensor
      self._sensor = FakeSensor(state)
    else:
      from max31865 import max31865
      self._sensor = max31865(conf.CS, conf.MISO, conf.MOSI, conf.SCK)
    self._state = state
    self._pid = PID.PID(conf.Pc, conf.Ic, conf.Dc, conf.Sc)
    self._pid.SetPoint = self._state['settemp']
    self._pid.setSampleTime(conf.sample_time)
    self._pid.setWindup(conf.windup)

    self._nan_count = 0
    self._outlier_count = 0
    self._last_good = None   # last accepted reading, in C
    self._flat_value = None  # flatline detector: identical readings for too long
    self._flat_since = 0
    self._i=0
    self._pidhist = [0.,0.,0.,0.,0.,0.,0.,0.,0.,0.]
    self._avgpid = 0.
    self._temphist = [0.,0.,0.,0.,0.]
    self._avgtemp = 0.
    self._lastsettemp = state['settemp']
    self._lasttime = time()
    self._sleeptime = 0

  def run(self, verbose=False):
    logger.info('PID loop started')
    while True:
      tempc = self._sensor.readTemp()
      if not self.validate_temp(tempc):
        if verbose:
          print('Invalid temp: {}'.format(tempc))
        continue

      if self._i == 0:
        self._temphist = [tempc for x in range(len(self._temphist))]

      temp = self.convert_if_needed(tempc)
      self.update_temp_hist_and_average(temp)
      self.update_target_temp()
      self.update_pid()
      self.update_state(temp)

      if verbose:
        print(self._state)
      self.sleep()

  MAX_NAN = 1000           # consecutive NaN/zero readings before giving up on the sensor
  MAX_OUTLIERS = 100       # consecutive outliers before latching a fault
  OUTLIER_DELTA = 15.0     # degC jump from the last accepted reading that cannot be real
  INVALID_BEFORE_ZERO = 5  # consecutive invalid readings before the PID output is zeroed
  FLATLINE_SECONDS = 60    # bit-identical readings for this long = stuck sensor (a live PT100 always wanders)

  def _fault(self, reason):
    if self._state.get('fault'):
      return
    logger.error('FAULT, heating disabled until toggled back on: %s', reason)
    self._state['fault'] = reason
    self._state['on'] = False
    self._state['pidval'] = 0
    self._state['avgpid'] = 0

  def check_flatline(self, tempc):
    now = time()
    if tempc != self._flat_value:
      self._flat_value, self._flat_since = tempc, now
    elif now - self._flat_since >= self.FLATLINE_SECONDS:
      self._fault('sensor reading frozen at %.2f for %.0f s' % (tempc, now - self._flat_since))

  def _invalid(self):
    """Called for every rejected reading: don't leave a stale PID output driving the relay."""
    if self._nan_count + self._outlier_count >= self.INVALID_BEFORE_ZERO:
      self._state['pidval'] = 0
      self._state['avgpid'] = 0

  def validate_temp(self, tempc):
    if isnan(tempc) or tempc == 0.0:
      self._nan_count += 1
      self._invalid()
      if self._nan_count > self.MAX_NAN:
        self._state['on'] = False
        logger.error('%d consecutive NaN/zero readings from sensor', self.MAX_NAN)
        raise Exception('%d consecutive NaN/zero readings from sensor' % self.MAX_NAN)
      return False

    # A real boiler cannot jump 15 degrees between two readings: reject it.
    # Compared against the last *accepted* reading, so outliers can't poison the reference.
    if self._last_good is not None and abs(tempc - self._last_good) > self.OUTLIER_DELTA:
      self._outlier_count += 1
      self._invalid()
      logger.info('Outlier rejected: %.2f (last good %.2f)', tempc, self._last_good)
      if self._outlier_count > self.MAX_OUTLIERS:
        self._fault('%d consecutive outliers from sensor' % self.MAX_OUTLIERS)
      return False

    self._outlier_count = 0
    self._nan_count = 0
    self._last_good = tempc
    self.check_flatline(tempc)
    return True

  def convert_if_needed(self, tempc):
    if conf.celsius:
      temp = tempc
    else:
      temp = c_to_f(tempc)
    return temp

  def update_temp_hist_and_average(self, temp):
    self._temphist[self._i % len(self._temphist)] = temp
    self._avgtemp = sum(self._temphist)/float(len(self._temphist))

  def update_target_temp(self):
    if self._state['settemp'] != self._lastsettemp:
      self._pid.SetPoint = self._state['settemp']
      self._lastsettemp = self._state['settemp']

  def update_pid(self):
    self._pid.update(self._avgtemp)
    hist_length = len(self._pidhist)
    self._pidhist[self._i % hist_length] = self._pid.output
    self._avgpid = sum(self._pidhist) / hist_length

  def update_state(self, temp):
    self._state['i'] = self._i
    self._state['temp'] = round(temp, 2)
    self._state['avgtemp'] = round(self._avgtemp, 2)
    self._state['last_update'] = time()   # heat.py withholds heat if this goes stale
    diff = self._lastsettemp - self._avgtemp

    # Be aggressive on machine startup
    if diff > 15.0:
      self._state['boost'] = time() + 1

    # And no need for a PID to tell me whether or not to heat up 1 degree passed our target
    if temp == 0.0:  # sensor dead
      self._state['pidval'] = 0
      self._state['avgpid'] = 0
    elif diff <= -1:
      self._state['pidval'] = 0
      self._state['avgpid'] = 0
    else:
      self._state['pidval'] = min(round(self._pid.output, 2), 999.0)  #formatting matters
      self._state['avgpid'] = round(self._avgpid, 2)

    self._state['pterm'] = round(self._pid.PTerm, 2)
    self._state['iterm'] = round(self._pid.ITerm * conf.Ic, 2)
    self._state['dterm'] = round(self._pid.DTerm * conf.Dc, 2)
    self._state['sterm'] = min(round(self._pid.STerm, 2), 999.0)  # Also a question of formatting

  def sleep(self):
    sleeptime = max(self._lasttime+conf.sample_time-time(), 0)
    sleep(sleeptime)
    self._i += 1
    self._lasttime = time()

  def cleanup(self):
    self._pid.clear()
    # Make sure heating stops if there was a problem
    self._state['pidval'] = 0
    self._state['avgpid'] = 0


if __name__ == "__main__":
  pid = Sensor({ 'settemp': conf.set_temp })
  pid.run(verbose=True)
