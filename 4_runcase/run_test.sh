#/bin/sh

profile=$1
log_file="logs/run_test_${profile}.log"

select=${2:-All}

nohup python3 -u test_runner.py -p $profile -s $select >> "$log_file" &

# tail -f "$log_file"
