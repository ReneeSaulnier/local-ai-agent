#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Kill any leftover processes from a previous run
pkill -f "python -m listener.listener" 2>/dev/null
sleep 1

# Start Ollama if not already running
if ! ollama list &>/dev/null; then
  echo "Starting Ollama..."
  ollama serve &
  sleep 2
fi

echo ""
echo "================================================"
echo "  Local Agent - iMessage Mode"
echo "  Text yourself to talk to the agent."
echo "  Press Ctrl+C to stop."
echo "================================================"
echo ""

python -m listener.listener
