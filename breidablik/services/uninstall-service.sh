#!/bin/bash -

# Disable & stop home automation services, clean up installed files
echo "Stopping service breidablik-display.service"
sudo systemctl disable breidablik-display.service
sudo systemctl stop breidablik-display.service

echo "Cleaning up files"
sudo rm /etc/systemd/system/breidablik-display.service

echo "Reloading systemctl deamon"
sudo systemctl daemon-reload

