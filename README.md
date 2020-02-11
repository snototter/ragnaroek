# Ragnar&oslash;k
* This repository is a collection of home automation related source and scripts.
* Why name it ragnar&oslash;k?<br/>Because once I'm fully dependent on an automated home, I'll be doomed.
* What's in here?
  * `helheimr` - A python3 systemd service to control our heating system. Highlights:
    * Task scheduling, temperature-aware controlling, etc.
    * ZigBee (via RaspBee) temperature sensors
    * LPD433 power plugs
    * Telegram bot
  * `breidablik` - TBD, e-ink display

## Sneak Peek
* Telegram bot to control `helheimr`:

  ![Telegram Bot](assets/example-bot.png "Telegram Bot")
* The RaspberryPi 3B+ running `helheimr`:

  ![RaspberryPi/Helheimr](assets/nastroend.jpg "Helheimr with LPD433 antenna")
* The RaspberryPi running bilskirnir, TODO


## Installation Helheimr
Installation instructions on RaspberryPi 3B+:

* Download Raspbian (tested with Buster lite)
  * Enable ssh (create empty `ssh` file)
  * (Optional) For convenience, add public key to `/home/pi/.ssh`, see https://www.raspberrypi.org/documentation/remote-access/ssh/passwordless.md
  * Configure wifi via wpa_supplicant.conf (country code=.., update_config=1)
* Set up RaspBee (deCONZ, Phoscon) following their [setup guide](https://phoscon.de/en/raspbee/install#raspbian)
  * For convenience (and fear of trusting external websites):
    ```bash
    ### Enable serial interface
    sudo raspi-config
    # Interfacing Options => Serial
    # * Login shell over serial => No
    # * Enable serial port hardware => Yes

    # Reboot

    ### Install deCONZ via APT
    # Import public key
    wget -O - http://phoscon.de/apt/deconz.pub.key | sudo apt-key add -

    # Stable APT repository
    sudo sh -c "echo 'deb http://phoscon.de/apt/deconz \
            $(lsb_release -cs) main' > \
            /etc/apt/sources.list.d/deconz.list"

    # Install
    sudo apt update
    sudo apt install deconz

    # Ensure it is running
    sudo systemctl enable deconz-gui

    # Install realvnc to use the deconz-gui remotely (to easily do the
    # initial ZigBee network configuration)
    sudo apt install realvnc-vnc-server realvnc-vnc-viewer

    ### RPi 4 requires additional steps, check their guide!
    ```
  * Start deCONZ application and pair devices.
* Install software packages
  ```bash
  sudo apt install -y python3-dev python3-pip python3-venv libatlas-base-dev libjpeg-dev zlib1g-dev
  sudo -H pip3 install rpi-rf
  ```
* Checkout the source code and set up virtual environment (if some time in the future the newer packages would break the application, use the provided `frozen-requirements.txt` instead of `requirements.txt`, see `prepare_environment_py3.sh`)
  ```bash
  git clone https://github.com/snototter/ragnaroek.git
  cd ragnaroek/helheimr
  ./prepare_environment_py3.sh

  # Install xkcd font (added some missing glyphs to the original xkcd-Script font)
  mkdir -p ~/.fonts
  cp ../assets/xkcd-Regular.otf ~/.fonts/
  fc-cache -f -v
  # Check if it's listed
  fc-list
  ```
* Prepare configuration files, place them into `<prj-root>/helheimr/configs/`:
  * `bot.cfg` - everything related to the Telegram bot
  * `ctrl.cfg` - heating, scheduling, logging, sensors, etc.
  * `owm.cfg` - OpenWeatherMap configuration
  * `scheduled-jobs.cfg` - (optional) pre-configure periodic heating/non-heating tasks
* Register and start the service
  ```bash
    cd <prj-root>/helheimr/services
    ./install-service.sh

    ### Check logs:
    journalctl -f -u helheimr-heating.service
  ```
* Set up a cronjob to check WIFI connection (and reboot upon error), as raspberry 3's seem to "frequently" (about once per month) loose wireless connection.
  * Create a script, e.g. `sudo vi /usr/local/bin/ensure-wifi.sh` with
    ```bash
    #!/bin/bash --
    ping -c4 192.168.0.1 > /dev/null
     
    if [ $? != 0 ] 
    then
      sudo /sbin/shutdown -r +1
    fi
    ```
  * Adjust permissions: `sudo chmod 755 /usr/local/bin/ensure-wifi.sh`
  * Add a cronjob, `crontab -e`, e.g. every 15 minutes:
    ```
    */15 * * * * /usr/bin/sudo -H /usr/local/bin/ensure-wifi.sh >> /dev/null 2>&1
    ```


## Installation Breidablik
* Raspbian Buster Lite, [release 2019-09-26](https://downloads.raspberrypi.org/raspbian_lite_latest)
* Install BCM2835 library
  ```bash
  wget http://www.airspayce.com/mikem/bcm2835/bcm2835-1.60.tar.gz
  tar zxvf bcm2835-1.60.tar.gz 
  cd bcm2835-1.60/
  ./configure
  make
  sudo make check
  sudo make install
  ```
* Install packages
  ```bash
  sudo apt install wiringpi
  sudo apt install python3-dev python3-venv python3-pip libatlas-base-dev libjpeg-dev zlib1g-dev git
  sudo -H pip3 install wheel
  ```
* Test e-ink paper
  * Shutdown, connect display
  * Clone waveshare repo: `git clone https://github.com/waveshare/e-Paper waveshare-eink`

## TODOs
* [ ] REST API for e-ink display
* [ ] e-ink display tests
* [ ] e-ink cover
* [ ] pip freeze exact versions (breidablik)
* [ ] Restart helheimr upon deCONZ connection issues (I should've never started with the zigbee sensors, they're a pain at times...)

