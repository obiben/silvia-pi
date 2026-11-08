# Install / manage silvia-pi as a systemd service.
#
#   sudo make install     install service + logrotate, enable and start
#   sudo make uninstall   stop, disable and remove them
#   make status           service status
#   make logs             follow the app log
#   make journal          follow the systemd journal (stderr / tracebacks)
#   sudo make restart     restart the service (after editing code)
#   make sim              run on a desktop with simulated hardware (no sudo)
#   make sim-deps         pip install what the simulation needs

SERVICE     := silvia-pi
PYTHON      ?= python
INSTALL_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
UNIT_DST    := /etc/systemd/system/$(SERVICE).service
LOGROTATE_DST := /etc/logrotate.d/$(SERVICE)
LOG_DIR     := $(INSTALL_DIR)/logs

.PHONY: install uninstall start stop restart status logs journal enable disable check-root sim sim-deps

sim:
	SILVIA_SIM=1 $(PYTHON) $(INSTALL_DIR)/silvia-pi.py

sim-deps:
	$(PYTHON) -m pip install -r $(INSTALL_DIR)/requirements-sim.txt

install: check-root
	@echo "Installing $(SERVICE) from $(INSTALL_DIR)"
	mkdir -p $(LOG_DIR)
	chmod +x $(INSTALL_DIR)/silvia-pi.py
	# Point the unit at wherever this repo actually lives
	sed 's|/home/pi/silvia-pi|$(INSTALL_DIR)|g' $(INSTALL_DIR)/silvia-pi.service > $(UNIT_DST)
	sed 's|/home/pi/silvia-pi|$(INSTALL_DIR)|g' $(INSTALL_DIR)/silvia-pi-logrotate > $(LOGROTATE_DST)
	# Remove the old rc.local autostart if it is still there
	@if grep -q silvia-pi.py /etc/rc.local 2>/dev/null; then \
	  echo "Removing old /etc/rc.local entry"; \
	  cp /etc/rc.local /etc/rc.local.bak; \
	  sed -i '/silvia-pi.py/d' /etc/rc.local; \
	fi
	systemctl daemon-reload
	systemctl enable $(SERVICE)
	systemctl restart $(SERVICE)
	@echo
	@systemctl --no-pager status $(SERVICE) || true

uninstall: check-root
	-systemctl stop $(SERVICE)
	-systemctl disable $(SERVICE)
	rm -f $(UNIT_DST) $(LOGROTATE_DST)
	systemctl daemon-reload

start stop restart enable disable: check-root
	systemctl $@ $(SERVICE)

status:
	systemctl --no-pager status $(SERVICE)

logs:
	tail -f $(LOG_DIR)/silvia-pi.log

journal:
	journalctl -u $(SERVICE) -f

check-root:
	@if [ "$$(id -u)" -ne 0 ]; then echo "Run with sudo"; exit 1; fi
