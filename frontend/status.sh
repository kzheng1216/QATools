#!/bin/bash

# Check npm dev server is running
echo "-----------------------------------------------------------------------------"
echo "| NPM dev server status:                                                     |"
echo "-----------------------------------------------------------------------------"
if ps aux | grep "npm run dev" | grep -v grep > /dev/null; then
    echo "NPM dev server is running"
    echo "PID: $(ps aux | grep "npm run dev" | grep -v grep | awk '{print $2}')"
else
    echo "NPM dev server is not running"
fi
echo "-----------------------------------------------------------------------------"