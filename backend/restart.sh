#!/bin/bash

echo "Shutting down backend..."
./shutdown.sh
echo "Starting backend..."
./startup.sh
echo "Backend restarted successfully"