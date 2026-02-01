#!/bin/bash
output=$1
mkdir -p $output

echo "Saving logs and job metadata to ${output}"

# This will save logs, events, and jobspecs
for jobid in $(flux jobs -a --json | jq -r .jobs[].id)
  do
    echo "Parsing jobid ${jobid}"
    flux job attach $jobid &> $output/${jobid}.out
    echo "START OF JOBSPEC" >> $output/${jobid}.out
    flux job info $jobid jobspec >> $output/${jobid}.out
    echo "START OF EVENTLOG" >> $output/${jobid}.out
    flux job info $jobid guest.exec.eventlog >> $output/${jobid}.out
done
