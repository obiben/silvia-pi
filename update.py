"""Self-update from the timer menu: git pull, then restart so the new code runs.

Requested from the menu (buttons.py sets state['update_request']) and carried
out by the main process, which exits when new code was pulled: the systemd unit
has Restart=always, so it comes straight back up on the new code. Progress is
reported through state['update_status'] for the menu to display.
"""
import os
import subprocess
import logging

from simulation import SIM, BASE_DIR

logger = logging.getLogger('silvia.update')


def _git(args):
  cmd = ['git', '-C', BASE_DIR] + args
  # The service runs as root but the checkout belongs to whoever cloned it: run git
  # as that user so the files stay theirs and git does not refuse the directory.
  try:
    import pwd
    owner = pwd.getpwuid(os.stat(BASE_DIR).st_uid).pw_name
    if os.geteuid() == 0 and owner != 'root':
      cmd = ['runuser', '-u', owner, '--'] + cmd
  except (ImportError, AttributeError, KeyError):
    pass
  return cmd


def run(state):
  """Pull. Returns True when new code arrived and the process should exit to be restarted."""
  state['update_status'] = 'updating...'
  if SIM:
    logger.info('Update requested (SIM: not pulling)')
    state['update_status'] = 'sim: not pulling'
    return False
  try:
    out = subprocess.check_output(_git(['pull', '--ff-only']), stderr=subprocess.STDOUT)
  except subprocess.CalledProcessError as e:
    logger.error('git pull failed: %s', e.output.decode('utf-8', 'replace').strip())
    state['update_status'] = 'failed, see log'
    return False
  except OSError as e:
    logger.error('could not run git: %s', e)
    state['update_status'] = 'failed, see log'
    return False
  text = out.decode('utf-8', 'replace').strip()
  logger.info('git pull: %s', text.replace('\n', ' | '))
  if 'Already up to date' in text or 'Already up-to-date' in text:
    state['update_status'] = 'already up to date'
    return False
  state['update_status'] = 'restarting...'
  return True
