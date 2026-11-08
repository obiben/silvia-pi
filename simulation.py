"""Hardware simulation switch.

Import this before any RPi.GPIO / gpiozero import. When SIM is true the stub
modules in sim/ shadow the real hardware libraries, the sensor is replaced by a
simple boiler model and the GUI opens in a normal window with keyboard buttons.

Enabled automatically when not on Linux, or explicitly with SILVIA_SIM=1.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SIM = bool(os.environ.get('SILVIA_SIM')) or not sys.platform.startswith('linux')

if SIM:
  sim_dir = os.path.join(BASE_DIR, 'sim')
  if sim_dir not in sys.path:
    sys.path.insert(0, sim_dir)
