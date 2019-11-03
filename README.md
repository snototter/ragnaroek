# About
* This repository is a collection of home automation related source and scripts.
* Why name it ragnarök?<br/>Because once I'm fully dependent on an automated home, I'll be doomed.
* What's in here?
  * `helheimr` - A python3 systemd service to control our heating system. Highlights:
    * Task scheduling, temperature-aware controlling, etc.
    * ZigBee (via RaspBee) temperature sensors
    * LPD433 power plugs
    * Telegram bot

# Installation Helheimr




Installation instructions on RaspberryPi 3B+

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
  sudo apt install -y python3-dev python3-pip libatlas-base-dev libjpeg-dev zlib1g-dev
  sudo -H pip3 install rpi-rf
  ```
* Checkout the source code and set up virtual environment
  ```bash
  git clone https://github.com/snototter/ragnaroek.git
  cd ragnaroek/helheimr
  ./prepare_environment_py3.sh

  # Install xkcd font (added some missing glyphs to the original xkcd-Script font)
  mkdir -p ~/.fonts
  cp assets/xkcd-Regular.otf ~/.fonts/
  fc-cache -f -v
  # Check if it's listed
  fc-list
  ```
* Prepare configuration files, place them into `<prj-root>/helheimr/configs/`:
  * `bot.cfg` - everything related to the Telegram bot
  * `ctrl.cfg` - 
  * `owm.cfg` - OpenWeatherMap configuration
  * `scheduled-jobs.cfg` - (optional) pre-configure periodic heating/non-heating tasks
* Register and start the service
  ```bash
    cd <prj-root>/helheimr/services
    ./install-service.sh

    ### Check logs:
    journalctl -f -u helheimr-heating.service
  ```

