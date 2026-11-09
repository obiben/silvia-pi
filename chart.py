#!/usr/bin/python
"""Seismograph-style temperature chart for the PiTFT.

Everything is drawn procedurally with pygame: a strip of old, creased chart
paper scrolls right-to-left while the tip of a long brass needle (hinged
somewhere off-screen) traces the boiler temperature in ink. The target is a
red ruled line and the four PiTFT buttons are labelled by hand down the
right-hand margin.
"""

import math
import os
import random
import time
import pygame
from simulation import SIM, BASE_DIR

import logging
logger = logging.getLogger('silvia.gui')

LCD_WIDTH = 320
LCD_HEIGHT = 240
LCD_SIZE = (LCD_WIDTH, LCD_HEIGHT)

# Vertical centre of each physical PiTFT button, top to bottom (GPIO 17, 22, 23, 27).
# Tweak these if the labels don't line up with the buttons on your screen.
BUTTON_Y = [48, 106, 164, 222]
BUTTON_LABELS = ['t+', 't-', 'boost', None]   # last one reads 'off' while on and 'on' while off

PEN_X = 250                                   # where the nib sits on the paper
PEN_PIVOT = (LCD_WIDTH + 260, LCD_HEIGHT // 2)  # hinge is well off-screen to the right, mid-height
SECONDS_PER_VLINE = 5

# Handwritten face: Daniel by Daniel Midgley (see fonts/Daniel Midgley.txt).
# FONT_PATH is the fallback weight; Bold is used for everything on screen.
FONT_PATH = os.path.join(BASE_DIR, 'fonts', 'Daniel-Regular.otf')
FONT_BOLD_PATH = os.path.join(BASE_DIR, 'fonts', 'Daniel-Bold.otf')
# Scrolling paper artwork (any width, 240 px high, grid baked in). If missing or
# unloadable, a paper texture is generated instead.
PAPER_PATH = os.path.join(BASE_DIR, 'media', 'fullpaper_pale.jpg')

# Palette
PAPER       = (212, 186, 134)
PAPER_LIGHT = (236, 218, 176)
PAPER_DARK  = (150, 116, 68)
INK         = (40, 28, 22)
INK_SOFT    = (98, 70, 52)
GRID        = (160, 118, 78)
GRID_FAINT  = (186, 152, 108)
RED_INK     = (150, 40, 32)
HEAT_RED    = (112, 22, 16)    # heater-on line along the bottom edge
RED_FAINT   = (196, 128, 118)
COFFEE      = (104, 62, 22)
WATER       = (132, 106, 62)
# PID terms: pale washes under the main trace, each with its own tiny label.
PID_TERMS = [
  ('P',   'pterm',  (60, 100, 200)),
  ('I',   'iterm',  (40, 150, 90)),
  ('D',   'dterm',  (150, 70, 180)),
  ('out', 'pidval', (210, 120, 30)),
]
PID_ALPHA = 95
PID_CLIP = 100.0   # terms beyond this run along the edge; keeps start-up spikes from flattening the view

STEEL       = (72, 74, 80)     # gunmetal needle
STEEL_DARK  = (28, 30, 34)
STEEL_LIGHT = (160, 166, 176)


def _font(size, path=FONT_PATH):
  if os.path.exists(path):
    try:
      return pygame.font.Font(path, size)
    except Exception:
      logger.exception('Could not load font %s, using the default', path)
  return pygame.font.Font(None, size)


def _nice_step(span, max_lines=7):
  """Grid spacing in degrees so that at most max_lines major lines show."""
  for step in (1, 2, 5, 10, 20, 50):
    if span / float(step) <= max_lines:
      return step
  return 100


def _wobbly_polygon(cx, cy, radius, points=28, wobble=0.22):
  pts = []
  for k in range(points):
    a = 2 * math.pi * k / points
    r = radius * (1 + wobble * (random.random() - 0.5) * 2)
    pts.append((int(cx + r * math.cos(a)), int(cy + r * math.sin(a))))
  return pts


class Chart(object):
  def __init__(self, refresh_rate, span, state):
    self._last_on_state = None
    logger.info('GUI constructor')
    self._state = state
    self._len = int(span / refresh_rate)
    self._data = [self._state['temp'] for x in range(self._len)]
    self._target = [self._state['settemp'] for x in range(self._len)]
    self._refresh_rate = refresh_rate
    self._samples = 0                      # total samples seen, drives paper scroll
    self._px_per_sample = PEN_X / float(self._len - 1)
    self._lo, self._hi = None, None        # current y range, smoothed
    self._terms = dict((key, [0.0] * self._len) for _, key, _ in PID_TERMS)
    self._heat = [False] * self._len       # heater on/off per sample
    self._tlo, self._thi = None, None      # PID terms share a separate, smoothed range
    self._overlay = pygame.Surface(LCD_SIZE, pygame.SRCALPHA)

    # Bold throughout: the Regular weight is too fine to read on the paper at 320x240.
    self._font_small = _font(15, FONT_BOLD_PATH)
    self._font_label = _font(19, FONT_BOLD_PATH)
    self._font_stamp = _font(30, FONT_BOLD_PATH)

    self._paper = self._load_paper()
    self._draw_rules = self._paper is None   # the artwork has its own grid
    if self._paper is None:
      logger.info('Building paper texture')
      random.seed(1842)
      self._paper = self._make_paper()
    self._period = self._paper.get_width()
    # Two pre-rendered sheets: the power button is labelled with what pressing it will do.
    self._labels_when_on = self._make_labels('off')
    self._labels_when_off = self._make_labels('on')
    logger.info('Constructor done')
    state['gui_on'] = True

  # ----------------------------------------------------------------- textures

  def _load_paper(self):
    """The paper artwork, followed by a mirrored copy so it loops without a seam."""
    if not os.path.exists(PAPER_PATH):
      return None
    try:
      img = pygame.image.load(PAPER_PATH).convert()
    except Exception:
      logger.exception('Could not load %s, falling back to generated paper', PAPER_PATH)
      return None
    w, h = img.get_size()
    if h != LCD_HEIGHT:
      img = pygame.transform.smoothscale(img, (max(1, int(w * LCD_HEIGHT / float(h))), LCD_HEIGHT))
      w = img.get_width()
    strip = pygame.Surface((2 * w, LCD_HEIGHT))
    strip.blit(img, (0, 0))
    strip.blit(pygame.transform.flip(img, True, False), (w, 0))
    logger.info('Loaded paper artwork %s (%dx%d)', PAPER_PATH, w, h)
    return strip.convert()

  def _blit_paper(self, screen):
    """Scroll the paper leftwards in step with the samples, wrapping forever."""
    offset = int(self._samples * self._px_per_sample) % self._period
    screen.blit(self._paper, (-offset, 0))
    if self._period - offset < LCD_WIDTH:
      screen.blit(self._paper, (self._period - offset, 0))

  def _make_paper(self):
    W, H = LCD_SIZE
    paper = pygame.Surface(LCD_SIZE)
    paper.fill(PAPER)

    # Fibre grain: a small noisy tile, repeated.
    tile = pygame.Surface((48, 48))
    for x in range(48):
      for y in range(48):
        d = random.randint(-10, 10)
        tile.set_at((x, y), (PAPER[0] + d, PAPER[1] + d, PAPER[2] + d - random.randint(0, 4)))
    for x in range(0, W, 48):
      for y in range(0, H, 48):
        paper.blit(tile, (x, y))

    overlay = pygame.Surface(LCD_SIZE, pygame.SRCALPHA)

    # Crumpling: soft patches of light and shade, built from faded rings.
    for _ in range(46):
      cx, cy = random.randint(-20, W + 20), random.randint(-20, H + 20)
      r = random.randint(22, 70)
      light = random.random() < 0.5
      col = PAPER_LIGHT if light else PAPER_DARK
      for k in range(5):
        pygame.draw.circle(overlay, col + (5,), (cx, cy), int(r * (1 - k * 0.17)))

    # Creases: slightly wandering fold lines, lit on one side, shaded on the other.
    for _ in range(11):
      if random.random() < 0.5:
        x0, y0, x1, y1 = random.randint(0, W), -5, random.randint(0, W), H + 5
      else:
        x0, y0, x1, y1 = -5, random.randint(0, H), W + 5, random.randint(0, H)
      pts = []
      for k in range(7):
        t = k / 6.0
        pts.append((int(x0 + (x1 - x0) * t + random.randint(-6, 6)),
                    int(y0 + (y1 - y0) * t + random.randint(-6, 6))))
      shade = [(x + 1, y + 1) for x, y in pts]
      pygame.draw.lines(overlay, PAPER_DARK + (70,), False, shade, 2)
      pygame.draw.lines(overlay, PAPER_LIGHT + (120,), False, pts, 1)

    # Water stains: a faint wash with a darker tide line around it.
    for _ in range(3):
      cx, cy = random.randint(20, W - 20), random.randint(20, H - 20)
      r = random.randint(26, 54)
      pts = _wobbly_polygon(cx, cy, r)
      pygame.draw.polygon(overlay, PAPER_LIGHT + (40,), pts)
      pygame.draw.polygon(overlay, WATER + (120,), pts, 2)
      pygame.draw.polygon(overlay, WATER + (60,), _wobbly_polygon(cx, cy, r * 0.9), 1)

    # Coffee: a couple of cup rings, one of them only a partial arc, plus a splash.
    for _ in range(2):
      cx, cy = random.randint(30, W - 30), random.randint(30, H - 30)
      r = random.randint(20, 32)
      for k, a in ((3, 55), (2, 90), (1, 120)):
        pygame.draw.circle(overlay, COFFEE + (a,), (cx, cy), r, k)
      pygame.draw.circle(overlay, COFFEE + (14,), (cx, cy), r - 3)
      for _ in range(6):   # droplets around the ring
        ang = random.random() * 2 * math.pi
        d = r + random.randint(3, 12)
        pygame.draw.circle(overlay, COFFEE + (70,), (int(cx + d * math.cos(ang)), int(cy + d * math.sin(ang))), random.randint(1, 2))
    cx, cy = random.randint(40, W - 40), random.randint(40, H - 40)
    pygame.draw.polygon(overlay, COFFEE + (34,), _wobbly_polygon(cx, cy, 16, 18, 0.5))
    pygame.draw.polygon(overlay, COFFEE + (90,), _wobbly_polygon(cx, cy, 16, 18, 0.5), 1)

    # Worn, darker edges.
    edge = 26
    for i in range(edge):
      a = int(90 * (1 - i / float(edge)) ** 2)
      c = PAPER_DARK + (a,)
      pygame.draw.line(overlay, c, (i, 0), (i, H))
      pygame.draw.line(overlay, c, (W - 1 - i, 0), (W - 1 - i, H))
      pygame.draw.line(overlay, c, (0, i), (W, i))
      pygame.draw.line(overlay, c, (0, H - 1 - i), (W, H - 1 - i))

    paper.blit(overlay, (0, 0))
    return paper

  def _make_labels(self, power_text):
    """Handwritten button labels, pre-rendered once per power state."""
    labels = pygame.Surface(LCD_SIZE, pygame.SRCALPHA)
    for text, y in zip(BUTTON_LABELS, BUTTON_Y):
      txt = self._font_label.render(text or power_text, True, INK)
      rect = txt.get_rect(midright=(LCD_WIDTH - 6, y))
      labels.blit(txt, rect)
      # a little hand-drawn arrow pointing at the button
      ax = LCD_WIDTH - 3
      pygame.draw.line(labels, INK, (ax - 2, y - 3), (ax, y))
      pygame.draw.line(labels, INK, (ax - 2, y + 3), (ax, y))
    return labels

  # ------------------------------------------------------------------- pygame

  @staticmethod
  def start_pygame():
    if not SIM:
      os.putenv('SDL_FBDEV', '/dev/fb1')
    pygame.init()
    pygame.display.set_mode(LCD_SIZE, pygame.DOUBLEBUF)
    if SIM:
      pygame.display.set_caption('silvia-pi SIM  [Up/Down: temp  B: boost  Space: on/off  S: screenshot]')
    else:
      pygame.mouse.set_visible(False)

  @staticmethod
  def stop_pygame():
    pygame.quit()

  # --------------------------------------------------------------------- data

  def set_data(self, data):
    self._data = data

  def add_temp(self, temp):
    self._data.append(temp)
    self._target.append(self._state['settemp'])
    self._heat.append(bool(self._state.get('heating', False)))
    if len(self._heat) > self._len:
      del self._heat[0]
    for _, key, _ in PID_TERMS:
      hist = self._terms[key]
      hist.append(max(-PID_CLIP, min(PID_CLIP, float(self._state.get(key) or 0.0))))
      if len(hist) > self._len:
        del hist[0]
    if len(self._data) > self._len:
      del self._data[0]
      del self._target[0]
    self._samples += 1
    self.plot()

  def _update_range(self):
    lo = min(self._data + self._target) - 3
    hi = max(self._data + self._target) + 3
    step = _nice_step(hi - lo)
    lo = math.floor(lo / step) * step
    hi = math.ceil(hi / step) * step
    if self._lo is None:
      self._lo, self._hi = lo, hi
    else:
      # Ease towards the new range so the paper doesn't jump.
      self._lo += (lo - self._lo) * 0.25
      self._hi += (hi - self._hi) * 0.25
    return _nice_step(self._hi - self._lo)

  def _y(self, temp):
    span = max(self._hi - self._lo, 0.1)
    return int(round((LCD_HEIGHT - 1) * (1 - (temp - self._lo) / span)))

  # ------------------------------------------------------------------ drawing

  def plot(self):
    screen = pygame.display.get_surface()
    step = self._update_range()

    self._blit_paper(screen)
    self._draw_grid(screen, step)
    self._draw_terms(screen)
    self._draw_target(screen)
    self._draw_trace(screen)
    self._draw_stamp(screen)
    self._draw_steam(screen)
    self._draw_heat(screen)
    self._draw_legend(screen)
    self._draw_fault(screen)
    screen.blit(self._labels_when_on if self._state['on'] else self._labels_when_off, (0, 0))
    self._draw_pen(screen)
    pygame.display.flip()

  def _draw_grid(self, screen, step):
    # Horizontal rules every `step` degrees, fainter half-steps between.
    first = math.ceil(self._lo / (step / 2.0)) * (step / 2.0)
    v = first
    while v <= self._hi:
      y = self._y(v)
      major = abs(v / float(step) - round(v / float(step))) < 1e-6
      if self._draw_rules:
        pygame.draw.line(screen, GRID if major else GRID_FAINT, (0, y), (LCD_WIDTH, y))
      if major:
        # Just the number: the artwork's grid doesn't line up with our scale,
        # and a tick would only draw attention to that.
        txt = self._font_small.render('%g' % v, True, INK_SOFT)
        screen.blit(txt, (4, y - txt.get_height() + 2))
      v += step / 2.0
    # Vertical time rules scroll with the paper: a fine one per second, a
    # stronger one every SECONDS_PER_VLINE.
    minor = self._px_per_sample / self._refresh_rate
    if self._draw_rules and minor >= 2:
      scroll = (self._samples * self._px_per_sample) % minor
      k = 0
      x = PEN_X - scroll
      while x > 0:
        major = (int(round((PEN_X - x) / minor)) + int(self._samples * self._refresh_rate)) % SECONDS_PER_VLINE == 0
        pygame.draw.line(screen, GRID if major else GRID_FAINT, (int(x), 0), (int(x), LCD_HEIGHT))
        x -= minor
        k += 1

  def _draw_terms(self, screen):
    """P, I, D and output as pale lines on their own shared scale (zero always in range)."""
    values = [v for hist in self._terms.values() for v in hist]
    lo, hi = min(0.0, min(values)), max(0.0, max(values))
    pad = max((hi - lo) * 0.1, 1.0)
    lo, hi = lo - pad, hi + pad
    if self._tlo is None:
      self._tlo, self._thi = lo, hi
    else:
      self._tlo += (lo - self._tlo) * 0.25
      self._thi += (hi - self._thi) * 0.25
    span = max(self._thi - self._tlo, 1e-6)
    top, bottom = 12, LCD_HEIGHT - 12

    def y_of(v):
      return int(round(bottom - (bottom - top) * (v - self._tlo) / span))

    overlay = self._overlay
    overlay.fill((0, 0, 0, 0))
    for _, key, color in PID_TERMS:
      hist = self._terms[key]
      pts = [(int(i * self._px_per_sample), y_of(v)) for i, v in enumerate(hist)]
      if len(pts) >= 2:
        pygame.draw.lines(overlay, color + (PID_ALPHA,), False, pts, 2)
    screen.blit(overlay, (0, 0))

  def _draw_heat(self, screen):
    """Dark red line along the bottom edge, present only while the heater was on."""
    y = LCD_HEIGHT - 2
    start = None
    for i, on in enumerate(self._heat):
      x = int(i * self._px_per_sample)
      if on and start is None:
        start = x
      elif not on and start is not None:
        pygame.draw.line(screen, HEAT_RED, (start, y), (x, y), 2)
        start = None
    if start is not None:
      pygame.draw.line(screen, HEAT_RED, (start, y), (PEN_X, y), 2)

  def _draw_legend(self, screen):
    """Coloured term names in a row, bottom left, clear of the axis numbers."""
    x = 30
    y = LCD_HEIGHT - 4
    for name, _, color in PID_TERMS:
      pale = tuple(int(c * 0.7 + p * 0.3) for c, p in zip(color, PAPER))
      tag = self._font_small.render(name, True, pale)
      screen.blit(tag, (x, y - tag.get_height()))
      x += tag.get_width() + 10

  def _draw_target(self, screen):
    on = self._state['on']
    color = RED_INK if on else RED_FAINT
    y = self._y(self._target[-1])
    # Ruled by hand: a dashed line with a slight waver.
    x = 0
    while x < PEN_X:
      yy = y + (1 if (x // 24) % 3 == 1 else 0)
      pygame.draw.line(screen, color, (x, yy), (min(x + 9, PEN_X), yy))
      x += 13
    # If the target moved during the visible window, show the old level too.
    for i in range(1, len(self._target)):
      if self._target[i] != self._target[i - 1]:
        x0 = int(i * self._px_per_sample)
        pygame.draw.line(screen, color, (x0, self._y(self._target[i - 1])), (x0, self._y(self._target[i])))

  def _draw_trace(self, screen):
    pts = [(int(i * self._px_per_sample), self._y(t)) for i, t in enumerate(self._data)]
    if len(pts) < 2:
      return
    # A wider soft stroke under a crisp one gives an inked look.
    pygame.draw.lines(screen, INK_SOFT, False, pts, 3)
    pygame.draw.lines(screen, INK, False, pts, 1)

  def _draw_stamp(self, screen):
    temp = self._state['temp']
    txt = self._font_stamp.render(u'%.1f°' % temp, True, INK)
    screen.blit(txt, (34, 2))
    # Target in the top right corner, above the button labels.
    sub = self._font_small.render(u'cible %.1f°' % self._state['settemp'], True, RED_INK)
    screen.blit(sub, sub.get_rect(topright=(LCD_WIDTH - 6, 2)))
    if not self._state['on'] and not self._state.get('fault'):   # the fault notice says it instead
      off = self._font_label.render('machine off', True, RED_INK)
      screen.blit(off, (36, txt.get_height() - 2))

  def _draw_steam(self, screen):
    """Boiler above the steam threshold: a jet of steam, beside the temperature."""
    if not self._state.get('steam'):
      return
    cx, y0 = 192, 6          # centre line and top of the icon, between the stamp and the target
    # billowing puffs, back to front: each is a cluster of circles outlined then
    # refilled a little smaller so only the cloud's outer edge is left inked
    puffs = [
      [(cx - 12, y0 + 18, 8), (cx - 6, y0 + 11, 9), (cx + 1, y0 + 17, 7)],
      [(cx + 10, y0 + 10, 8), (cx + 16, y0 + 17, 7)],
      [(cx - 3, y0 + 26, 7), (cx + 5, y0 + 23, 9), (cx + 13, y0 + 27, 7)],
    ]
    for puff in puffs:
      for x, y, r in puff:
        pygame.draw.circle(screen, RED_INK, (x, y), r)
      for x, y, r in puff:
        pygame.draw.circle(screen, PAPER_LIGHT, (x, y), r - 2)
    # the wand's nozzle: three short jets fanning up into the cloud
    base = y0 + 46
    for dx in (-5, 0, 5):
      pygame.draw.line(screen, INK, (cx + 4 + dx, base), (cx + 4 + dx * 2, base - 12), 2)

  def _wrap(self, text, font, width):
    """Greedy word wrap for a pygame font."""
    lines, line = [], ''
    for word in text.split():
      trial = (line + ' ' + word).strip()
      if line and font.size(trial)[0] > width:
        lines.append(line)
        line = word
      else:
        line = trial
    if line:
      lines.append(line)
    return lines

  def _draw_fault(self, screen):
    """Safety latch tripped: a notice across the paper saying why and how to reset."""
    fault = self._state.get('fault')
    if not fault:
      return
    pad = 8
    left, right = 10, PEN_X - 10
    width = right - left
    head = self._font_label.render('FAULT - heating disabled', True, RED_INK)
    reason = [self._font_small.render(l, True, INK) for l in self._wrap(fault, self._font_small, width - 2 * pad)]
    reset = [self._font_small.render(l, True, RED_INK)
             for l in self._wrap('press on to reset and start heating again', self._font_small, width - 2 * pad)]
    gap = 3
    height = 2 * pad + head.get_height() + gap + sum(r.get_height() for r in reason) + gap + sum(r.get_height() for r in reset)
    top = (LCD_HEIGHT - height) // 2 + 6   # a touch below centre: the stamp owns the top left

    # Faded paper behind the ink so the notice reads over the traces.
    box = pygame.Surface((width, height), pygame.SRCALPHA)
    box.fill(PAPER_LIGHT + (215,))
    screen.blit(box, (left, top))
    pygame.draw.rect(screen, RED_INK, (left, top, width, height), 2)
    pygame.draw.rect(screen, RED_INK, (left + 3, top + 3, width - 6, height - 6), 1)

    y = top + pad
    screen.blit(head, (left + pad, y))
    y += head.get_height() + gap
    for r in reason:
      screen.blit(r, (left + pad, y))
      y += r.get_height()
    y += gap
    for r in reset:
      screen.blit(r, (left + pad, y))
      y += r.get_height()

  def _draw_pen(self, screen):
    """Only the last stretch of a long needle is on screen; it tapers to the nib."""
    tip = (PEN_X, self._y(self._data[-1]))
    px, py = PEN_PIVOT
    dx, dy = tip[0] - px, tip[1] - py
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length          # unit vector pivot -> tip
    nx, ny = -uy, ux                            # perpendicular
    w_far, w_tip = 7.0, 1.2                     # half-widths at the (off-screen) hinge and nib

    def quad(shift_x=0, shift_y=0):
      return [(int(px + nx * w_far + shift_x), int(py + ny * w_far + shift_y)),
              (int(tip[0] + nx * w_tip + shift_x), int(tip[1] + ny * w_tip + shift_y)),
              (int(tip[0] - nx * w_tip + shift_x), int(tip[1] - ny * w_tip + shift_y)),
              (int(px - nx * w_far + shift_x), int(py - ny * w_far + shift_y))]

    shadow = pygame.Surface(LCD_SIZE, pygame.SRCALPHA)
    pygame.draw.polygon(shadow, (30, 20, 10, 70), quad(3, 4))
    screen.blit(shadow, (0, 0))
    pygame.draw.polygon(screen, STEEL_DARK, quad())
    # highlight along one edge of the body
    inner = [(int(px + nx * (w_far - 2)), int(py + ny * (w_far - 2))),
             (int(tip[0] + nx * 0.4), int(tip[1] + ny * 0.4)),
             (int(tip[0] - nx * 0.4), int(tip[1] - ny * 0.4)),
             (int(px - nx * (w_far - 4)), int(py - ny * (w_far - 4)))]
    pygame.draw.polygon(screen, STEEL, inner)
    pygame.draw.line(screen, STEEL_LIGHT,
                     (int(px + nx * (w_far - 3)), int(py + ny * (w_far - 3))),
                     (int(tip[0] + nx * 0.5), int(tip[1] + ny * 0.5)), 1)
    # Nib: a dark steel point with a bead of ink.
    pygame.draw.circle(screen, INK, tip, 2)
    if self._state.get('heating', False):
      pygame.draw.circle(screen, RED_INK, (tip[0] + 3, tip[1] - 3), 1)

  # ------------------------------------------------------------------- loop

  def handle_sim_key(self, key):
    """Keyboard stand-ins for the 4 PiTFT buttons when running off the Pi."""
    import buttons
    actions = {
      pygame.K_UP: buttons.increase,
      pygame.K_DOWN: buttons.decrease,
      pygame.K_b: buttons.boost,
      pygame.K_SPACE: buttons.toggle,
    }
    if key in actions:
      actions[key](self._state)
    elif key == pygame.K_s:
      self.screenshot('sim-screenshot.png')

  def screenshot(self, path):
    pygame.image.save(pygame.display.get_surface(), path)
    logger.info('Screenshot saved to %s', path)

  def run(self):
    crashed = False
    # SIM only: SILVIA_SIM_SCREENSHOT=<file> saves the screen after
    # SILVIA_SIM_SCREENSHOT_DELAY seconds (default 20).
    auto_shot = os.environ.get('SILVIA_SIM_SCREENSHOT') if SIM else None
    auto_shot_at = time.time() + float(os.environ.get('SILVIA_SIM_SCREENSHOT_DELAY', 20))
    try:
      while not crashed:
        if auto_shot and time.time() > auto_shot_at:
          self.screenshot(auto_shot)
          auto_shot = None
        self.add_temp(self._state['temp'])
        for event in pygame.event.get():
          if event.type == pygame.QUIT:
            crashed = True
          elif SIM and event.type == pygame.KEYDOWN:
            self.handle_sim_key(event.key)
        time.sleep(self._refresh_rate)
    except Exception:
      logger.exception('GUI loop crashed')
    except KeyboardInterrupt:
      logger.info('User interrupted process, exiting GUI')
    logger.info('GUI exiting run() loop')
