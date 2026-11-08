#!/usr/bin/python

import time
import pygame
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.style.use("dark_background")
import matplotlib.backends.backend_agg as agg

import logging
logger = logging.getLogger('silvia.gui')

LCD_WIDTH = 320
LCD_HEIGHT = 240
LCD_SIZE = (LCD_WIDTH, LCD_HEIGHT)

# Strip on the right edge of the LCD, next to the 4 PiTFT tactile buttons.
LABEL_WIDTH = 56
CHART_WIDTH = LCD_WIDTH - LABEL_WIDTH
# Vertical centre of each physical button, top to bottom (GPIO 17, 22, 23, 27).
# Tweak these if the labels don't line up with the buttons on your screen.
BUTTON_Y = [48, 106, 164, 222]
FONT_SIZE = 17

class Chart(object):
  def __init__(self, refresh_rate, span, state):
    self._last_on_state = None
    logger.info('GUI constructor')
    self._state = state
    self._len = int(span / refresh_rate)
    #while self._state['temp'] == 0.0:
    #  time.sleep(0.1)
    self._data = [self._state['temp'] for x in range(self._len)]
    self._target = [self._state['settemp'] for x in range(self._len)]
    self._refresh_rate = refresh_rate
    self._font = pygame.font.Font(None, FONT_SIZE)

    self._figure = plt.figure(figsize=[CHART_WIDTH / 80., LCD_HEIGHT / 80.], dpi=80)
    self._axes = self._figure.add_subplot(111)
    self._axes.grid(linestyle='dotted')

    logger.info('Plotting initial data')
    self._data_plot, = self._axes.plot(self._data)
    self._target_plot, = self._axes.plot(self._target)
    self._figure.gca().get_xaxis().set_visible(False)
    logger.info('Constructor done')
    state['gui_on'] = True

  @staticmethod
  def start_pygame():
    os.putenv('SDL_FBDEV', '/dev/fb1')
    #os.putenv('SDL_MOUSEDRV', 'TSLIB')
    #os.putenv('SDL_MOUSEDEV', '/dev/input/touchscreen')
    pygame.init()
    pygame.display.set_mode(LCD_SIZE, pygame.DOUBLEBUF)
    pygame.mouse.set_visible(False)

  @staticmethod
  def stop_pygame():
    pygame.quit()

  def set_data(self, data):
    self._data = data

  def add_temp(self, temp):
    self._data.append(temp)
    self._target.append(self._state['settemp'])
    if len(self._data) > self._len:
      del self._data[0]
      del self._target[0]
    self.plot()

  def plot(self):
    self._data_plot.set_ydata(self._data)
    self._target_plot.set_ydata(self._target)
    avgtemp = self._state['avgtemp']
    settemp = self._state['settemp']
    self._axes.set_ylim(min(self._data+self._target)-3, max(self._data+self._target)+3)
    self._axes.autoscale_view()
    canvas = agg.FigureCanvasAgg(self._figure)
    canvas.draw()
    size = canvas.get_width_height()
    renderer = canvas.get_renderer()
    raw_data = renderer.tostring_rgb()
    surf = pygame.image.fromstring(raw_data, size, "RGB")
    screen = pygame.display.get_surface()
    screen.fill((0, 0, 0))
    screen.blit(surf, (0,0))
    self.draw_button_labels(screen)
    pygame.display.flip()

  def draw_button_labels(self, screen):
    on = self._state['on']
    grey = (160, 160, 160)
    labels = [
      ('TEMP +', grey),
      ('TEMP -', grey),
      ('BOOST',  (255, 170, 0)),
      ('ON' if on else 'OFF', (80, 220, 80) if on else (230, 70, 70)),
    ]
    x_right = LCD_WIDTH - 4
    pygame.draw.line(screen, (60, 60, 60), (CHART_WIDTH, 0), (CHART_WIDTH, LCD_HEIGHT))
    for (text, color), y in zip(labels, BUTTON_Y):
      rendered = self._font.render(text, True, color)
      rect = rendered.get_rect(midright=(x_right, y))
      screen.blit(rendered, rect)
      # small tick pointing at the physical button
      pygame.draw.line(screen, color, (LCD_WIDTH - 3, y), (LCD_WIDTH - 1, y))

  def run(self):
    crashed = False
    try:
      while not crashed:
        if self._last_on_state != self._state['on']:
          color = 'green' if self._state['on'] else 'red'
          self._target_plot.set_color(color)
          self._last_on_state = self._state['on']
        temp = self._state['temp']
        self.add_temp(temp)
        for event in pygame.event.get():
          if event.type == pygame.QUIT:
            crashed = True
        # Must be outside the event loop: with no events queued the old
        # placement never slept, so the GUI redrew flat out and ate a core.
        time.sleep(self._refresh_rate)
    except Exception:
      logger.exception('GUI loop crashed')
    except KeyboardInterrupt:
      logger.info('User interrupted process, exiting GUI')
    logger.info('GUI exiting run() loop')
