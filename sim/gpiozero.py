"""Minimal gpiozero stand-in. Buttons never fire by themselves; in simulation
the GUI window maps keyboard keys to the same actions (see buttons.py)."""

class Button(object):
  def __init__(self, pin, **kwargs):
    self.pin = pin
    self.when_pressed = None
    self.when_released = None

  def press(self):
    if self.when_pressed:
      self.when_pressed()
