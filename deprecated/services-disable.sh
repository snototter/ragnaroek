#!/bin/bash -

# Disable & stop home automation services, clean up installed files
echo "Stopping service helheimr-telegram-bot.service"
sudo systemctl disable helheimr-telegram-bot.service
sudo systemctl stop helheimr-telegram-bot.service

echo "Cleaning up files"
sudo rm /etc/systemd/system/helheimr-telegram-bot.service

echo "Reloading systemctl deamon"
sudo systemctl daemon-reload

