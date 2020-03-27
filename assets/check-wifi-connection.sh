#!/bin/bash --
wake_time="06:30"
sleep_time="23:00"
known_ip=192.168.0.1

# Time strings can be compared lexicographically: https://unix.stackexchange.com/a/395936
currenttime=$(date +%H:%M)
if [[ "$currenttime" > "${wake_time}" ]] && [[ "$currenttime" < "${sleep_time}" ]]; then
  ping -c4 ${known_ip} > /dev/null
   
  if [[ $? != 0 ]]; then
    echo "Cannot reach ip ${known_ip}, rebooting!" | systemd-cat -t helheimr -p warning
    sudo /sbin/shutdown -r +1
  fi
fi
