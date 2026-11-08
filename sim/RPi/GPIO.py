"""Minimal RPi.GPIO stand-in. Remembers pin levels, does nothing else."""

BCM = 11
BOARD = 10
OUT = 0
IN = 1
HIGH = 1
LOW = 0

_levels = {}

def setwarnings(flag):
  pass

def setmode(mode):
  pass

def setup(pin, direction, **kwargs):
  _levels.setdefault(pin, LOW)

def output(pin, level):
  _levels[pin] = 1 if level else 0

def input(pin):
  return _levels.get(pin, LOW)

def cleanup(*args):
  _levels.clear()
