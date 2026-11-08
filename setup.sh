#!/bin/bash
SCRIPT=$(readlink -f "$0")
BASEDIR=$(dirname "$SCRIPT")

if [[ $(whoami) -ne 'root' ]]; then
  echo "Must run as root!"
  exit -1
fi

apt-get -y install rpi-update git build-essential python-dev python-smbus python-pip logrotate make

echo "Installing Adafruit GPIO library..."
cd ~
git clone https://github.com/adafruit/Adafruit_Python_GPIO.git
cd ~/Adafruit_Python_GPIO
python setup.py install

echo "Installing MAX31855 Thermocouple Amp library..."
cd ~
git clone https://github.com/adafruit/Adafruit_Python_MAX31855.git
cd ~/Adafruit_Python_MAX31855
python setup.py install

echo "Installing ivPID library..."
cd ~
git clone https://github.com/ivmech/ivPID.git
cp ~/ivPID/PID.py ~/silvia-pi/

echo "Installing remaining python libraries..."
pip install --upgrade -r $BASEDIR/requirements.txt

echo "Installing systemd service and logrotate config..."
make -C $BASEDIR install

echo "Installation complete.  Please reboot."
