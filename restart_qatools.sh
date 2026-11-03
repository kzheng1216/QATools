#!/bin/bash

echo "Restarting QATools..."
./shutdown_qatools.sh
./startup_qatools.sh
echo "QATools restart complete" 