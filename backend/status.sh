#!/bin/bash

# Check if uvicorn app:app --host 0.0.0.0 --port 9888
if ps aux | grep uvicorn | grep -v grep > /dev/null; then
    echo "Uvicorn is running"
    echo "PID: $(ps aux | grep uvicorn | grep -v grep | awk '{print $2}')"
else
    echo "Uvicorn is not running"
fi

# List all running cases and PIDs
echo "-----------------------------------------------------------------------------"
echo "| Running cases and PIDs:                                                   |"
echo "-----------------------------------------------------------------------------"
ps aux | grep uvicorn | grep -v grep | awk '{pid=$2; p=""; s=""; for(i=1;i<=NF;i++){if($i=="-p") p=$(i+1); if($i=="-s") s=$(i+1)} printf "[PID]:%-8s [Profile]:%-55s [Select]:%s\n\n", pid, p, s; c++} END{print "Total: "c}'
echo "-----------------------------------------------------------------------------"