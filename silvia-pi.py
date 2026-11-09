#!/usr/bin/python3

import logging
import os
from simulation import SIM, BASE_DIR  # must precede any RPi/gpiozero import

LOG_DIR = os.path.join(BASE_DIR, 'logs')
# Fixed filename, append mode: rotation is handled by logrotate (see silvia-pi-logrotate).
# copytruncate + O_APPEND keeps every process writing to the same file safely.
if not os.path.isdir(LOG_DIR):
  os.makedirs(LOG_DIR)
logger = logging.getLogger('silvia')
logger.setLevel(logging.INFO)
fh = logging.FileHandler(os.path.join(LOG_DIR, 'silvia-pi.log'))
fh.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

def he_control_loop(lock,state):
  from heat import Heat

  import signal, sys
  # terminate() sends SIGTERM; turn it into SystemExit so the finally below
  # runs and the relay pins are driven low instead of staying wherever they were.
  signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

  heat_control = None
  try:
    heat_control = Heat(state)
    heat_control.run()
  except Exception:
    logger.exception('Heat control crashed')
  finally:
    logger.info("----------------Closing heat control----------------")
    if heat_control is not None:
      heat_control.cleanup()

def pid_loop(lock,state):
  from sensor import Sensor
  pid = None
  try:
    pid = Sensor(state)
    pid.run()
  except Exception:
    logger.exception('PID loop crashed')
  finally:
    logger.info("--------------------Closing PID---------------------")
    if pid is not None:
      pid.cleanup()


def pygame_gui(lock, state):
  from chart import Chart

  try:
    Chart.start_pygame()
    c = Chart(0.5, 30, state)
    c.run()
  except Exception:
    logger.exception('GUI crashed')
  finally:
    logger.info("--------------------Closing GUI---------------------")
    Chart.stop_pygame()

def gpio_temp_control(lock, state):
  from gpiozero import Button
  import buttons
  buttons.init_backlight()

  up = Button(17)
  up.when_pressed = lambda: buttons.increase(state)
  down = Button(22)
  down.when_pressed = lambda: buttons.decrease(state)
  # Power button: short press acts on release, a hold opens the timer menu
  kill = Button(27, hold_time=buttons.HOLD_SECONDS)
  kill.when_held = lambda: buttons.power_held(state)
  kill.when_released = lambda: buttons.power_released(state)
  boost = Button(23)
  boost.when_pressed = lambda: buttons.boost(state)

  return up, down, kill, boost

def print_exception(*info):
  import traceback
  tb = ''.join(traceback.format_exception(*info))

  logger.error("Uncaught error: ")
  logger.error(tb)


if __name__ == '__main__':
  from multiprocessing import Process, Manager, Lock
  from time import sleep
  from config import config as conf
  import sys
  from formatter import PartialFormatter

  sys.excepthook = print_exception
  lock = Lock()
  manager = Manager()
  pidstate = manager.dict()
  # Timer: older conf.json files predate these, hence the defaults
  pidstate['timer_on'] = getattr(conf, 'timer_on', '06:30')
  pidstate['timer_off'] = getattr(conf, 'timer_off', '09:00')
  pidstate['timer_enabled'] = bool(getattr(conf, 'timer_enabled', False))
  pidstate['menu'] = None         # index into buttons.MENU_FIELDS while the timer menu is open
  pidstate['update_request'] = False   # set from the menu; the loop below runs update.py
  pidstate['update_status'] = None
  pidstate['i'] = 0
  pidstate['settemp'] = conf.set_temp
  pidstate['avgpid'] = 0.
  pidstate['temp'] = 0.
  pidstate['heating'] = False
  pidstate['steam'] = False       # boiler above the steam threshold: relay held open, icon shown
  pidstate['avgtemp'] = None
  pidstate['exit'] = False
  pidstate['pterm'] = None
  pidstate['iterm'] = None
  pidstate['dterm'] = None
  pidstate['sterm'] = None
  pidstate['pidval'] = 0.  # heat.py compares this numerically; None would crash on py3
  pidstate['boost'] = 0
  pidstate['on'] = True
  pidstate['gui_on'] = False
  pidstate['fault'] = None        # latched safety fault text, cleared by the toggle button
  pidstate['last_update'] = 0     # time() of the last valid sensor reading
  logger.info('Main process started%s', ' (SIMULATION, no hardware)' if SIM else '')

  logger.info('Starting PID loop')
  p = Process(target=pid_loop,args=(lock, pidstate))
  p.daemon = True
  p.start()

  logger.info('Starting heat control')
  h = Process(target=he_control_loop,args=(lock, pidstate))
  h.daemon = True
  h.start()

  logger.info('Starting GUI')
  gui = Process(target=pygame_gui, args=(lock, pidstate))
  gui.daemon = True
  gui.start()

  while not pidstate['gui_on']:
    if not gui.is_alive():
      logger.error('GUI died during startup, exiting')
      p.terminate(); h.terminate(); p.join(); h.join()
      sys.exit(1)
    sleep(1)

  up, down, kill, boost = gpio_temp_control(lock, pidstate)
  logger.info('Buttons assigned')

  logger.info('Starting status loop')
  fmt = PartialFormatter()
  # Only print the per-second status line when someone is watching a terminal;
  # under systemd it would just fill the journal.
  show_status = sys.stdout.isatty()
  children = {'PID': p, 'heat control': h, 'GUI': gui}
  exit_code = 0
  while True:
    dead = [name for name, proc in children.items() if not proc.is_alive()]
    if dead:
      logger.error('Process(es) died: %s. Shutting down so the service can restart.', ', '.join(dead))
      exit_code = 1
      break
    try:
      if pidstate['exit']:
        break
      if pidstate.get('update_request'):
        pidstate['update_request'] = False
        import update
        if update.run(pidstate):
          logger.info('New code pulled, exiting so the service restarts on it')
          sleep(1)   # let the menu show "restarting..." before the screen goes
          break
      if show_status:
        print(fmt.format('P: {pterm:7.2f}\tI: {iterm:7.2f}\tD: {dterm:7.2f}\tS: {sterm:7.2f}\tOut: {pidval:7.2f} Avg PID: {avgpid:7.2f}\tTemp: {temp:7.2f}\tAvg Temp: {avgtemp:7.2f}', **pidstate))
      sleep(1)
    except KeyboardInterrupt:
      logger.error('Keyboard interrupt, exiting')
      break
    except Exception:
      logger.exception('Error in status loop (shared state may be gone)')
      exit_code = 1
      break

  logger.info('Killing PID process')
  p.terminate()
  logger.info('Killing heat control process')
  h.terminate()
  logger.info('Killing GUI process')
  gui.terminate()
  p.join()
  h.join()
  gui.join()

  logger.info('All processes joined, exiting with code %d', exit_code)
  sys.exit(exit_code)
