#!/bin/bash

# Run the activation process for a device

device_name=$1

if [ -z "$device_name" ]; then
    echo "Device name is required"
    exit 1
fi

nohup python3 -u factory_reset_and_activate.py $device_name &