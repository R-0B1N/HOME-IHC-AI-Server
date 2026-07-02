#!/bin/bash

echo "Starting Gemini CLI Agent Loop..."

while true; do
  echo "----------------------------------------"
  echo "Gathering context..."
  
  # Get last 5 commits
  commits=$(git log -n 5 --oneline 2>/dev/null || echo "No git repository or no commits found.")
  
  # Read all issues from project/issues/*.md
  issues=""
  for f in project/issues/*.md; do
    if [ -f "$f" ]; then
      issues+="\n--- $f ---\n"
      issues+=$(cat "$f")
    fi
  done
  
  if [ -z "$issues" ]; then
    issues="No active issues found."
  fi

  # Construct prompt
  prompt="Iteration: Review the current system context. Decide what needs to be done next based on project/instructions.md.\n## CURRENT SYSTEM CONTEXT\n\n### Recent Commits:\n$commits\n### Active Issues:\n$issues"

  echo "Invoking Antigravity Python Agent..."
  python agent.py "$prompt"
  
  echo "----------------------------------------"
  echo "Sleeping for 60 seconds before next iteration..."
  sleep 60
done
