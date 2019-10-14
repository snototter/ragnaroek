#!/bin/bash -

# Disable & stop home automation services, clean up installed files
echo "Stopping service helheimr-telegram-bot.service"
sudo systemctl disable helheimr-heating.service
sudo systemctl stop helheimr-heating.service

echo "Cleaning up files"
sudo rm /etc/systemd/system/helheimr-heating.service

echo "Reloading systemctl deamon"
sudo systemctl daemon-reload

