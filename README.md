#### TODO
* Update requirements and install script
* Re-include web interface and make it a config whether or not to use it

# silvia-pi
A Raspberry Pi modification to the Rancilio Silvia Espresso Machine implementing PID temperature control.

This is based on http://github.com/brycesub/silvia-pi and adapted to graph current and target temperatures on a PiTFT28 fitted above the steam valve.
#### UI
Target temp can be controlled via buttons. Bottom button kills all processes.
![Machine with LCD](media/screen_plexi_copper.jpg?raw=true "LCD Display")

#### Hardware
* Raspberry Pi 2
  * $35 - http://www.amazon.com/Raspberry-Pi-Model-Project-Board/dp/B00T2U7R7I
  * $5 - Raspberry Pi Zero should work too
* PiTFT 2.8"
  * $45 Capacitive https://www.adafruit.com/product/2423
  * $35 Resistive https://www.adafruit.com/product/2298
* Power Adapter
  * Any Micro USB 5v / 2A supply will do, the longer the cable the better
  * $9 - http://www.amazon.com/CanaKit-Raspberry-Supply-Adapter-Charger/dp/B00GF9T3I0
* Micro SD Card
  * 4GB minimum, 8GB Class 10 recommended
  * $7 - http://www.amazon.com/Samsung-Class-Adapter-MB-MP16DA-AM/dp/B00IVPU7KE
* Solid State Relay - For switching on and off the heating element
  * $10 - https://www.sparkfun.com/products/13015
* Thermocouple Amplifier - For interfacing between the Raspberry Pi and Thermocouple temperature probe
  * $15 - https://www.sparkfun.com/products/13266
* Type K Thermocouple - For accurate temperature measurement
  * $15 - http://www.auberins.com/index.php?main_page=product_info&cPath=20_3&products_id=307
* Ribbon Cable - For connecting everything together
  * $7 - http://www.amazon.com/Veewon-Flexible-Multicolored-Female-Breadboard/dp/B00N7XX4XM
    * Female to Female if using the Raspberry Pi 2
  * $5 - http://www.amazon.com/uxcell-Width-Colorful-Flexible-Ribbon/dp/B00BWFY6JI
    * Bare wire if using the Raspberry Pi Zero
* 14 gauge wire - For connecting the A/C side of the relay to the circuit
  * $5 - Hardware Store / Scrap
    * Don't skimp here.  Remember this wire will be in close proximit to a ~240*F boiler

#### Hardware Installation
[Installation Instructions / Pictures](http://imgur.com/a/3WLVt)

#### Circuit Diagram
High-level circuit diagram:

![Circuit Diagram](media/circuit.png?raw=true "Circuit Diagram")

#### Software
* OS - Raspbian Jessie
  * Full - https://downloads.raspberrypi.org/raspbian_latest
  * Lite (for smaller SD Cards) - https://downloads.raspberrypi.org/raspbian_lite_latest

Install Raspbian and configure Wi-Fi and timezone.

#### silvia-pi Software Installation Instructions

*** Outdated ***

Execute on the pi bash shell:
````
sudo apt-get -y update
sudo apt-get -y upgrade
sudo apt-get -y install rpi-update git build-essential python-dev python-smbus python-pip
sudo rpi-update
sudo bash -c 'echo "dtparam=spi=on" >> /boot/config.txt'
sudo reboot
````

After the reboot:
````
sudo git clone https://github.com/brycesub/silvia-pi.git /root/silvia-pi
sudo /root/silvia-pi/setup.sh
````
This last step will download the necessariy python libraries and install the silvia-pi software in /root/silvia-pi

It also creates an entry in /etc/rc.local to start the software on every boot.

