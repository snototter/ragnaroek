#!/bin/bash -

# Register service
function register_service
{
  svc=$1.service
  sysvc=/etc/systemd/system/$svc

  if [ -f "$sysvc" ]
  then
    echo "Need to stop/disable previously registered instance ($sysvc):"
    # Stop and disable previously registered instances
    sudo systemctl disable $svc
    sudo systemctl stop $svc
  fi
  

  # Create/replace the service file
  scriptdir=$(pwd)
  workdir=$(realpath $scriptdir/..)
  sudo cp $svc /etc/systemd/system
  sudo sed -i "s/RAGNAROEKUSR/$USER/g" "$sysvc"
  sudo sed -i "s|RAGNAROEKWORKDIR|$workdir|g" "$sysvc"
  sudo sed -i "s|RAGNAROEKGATEWAYIP|192.168.0.1|g" "$sysvc"

  echo "Registering '$svc' for user '$USER'"

  # Reload and enable service
  sudo systemctl daemon-reload
  sudo systemctl enable $svc
  sudo systemctl start $svc
}

register_service network-wait-online.service
register_service helheimr-heating
