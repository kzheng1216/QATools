#!/bin/bash

echo "Restarting QATools frontend..."
./shutdown.sh
echo "Starting QATools frontend..."
./startup.sh
echo "QATools frontend restart complete"