#!/bin/bash
set -e

# Export environment variables for cron jobs (cron doesn't inherit env)
printenv | grep -E '^(TA_|FUTU_|HTTP_)' > /etc/environment

case "${1:-serve}" in
  serve)
    # Default: start API server only
    exec python -m trader_analysis serve --host 0.0.0.0 --port 8000
    ;;
  all)
    # Start API server + cron scheduler (production mode)
    echo "Starting cron daemon..."
    cron
    echo "Starting API server..."
    exec python -m trader_analysis serve --host 0.0.0.0 --port 8000
    ;;
  init)
    # One-shot: initialize history data
    exec python -m trader_analysis init "${@:2}"
    ;;
  update)
    # One-shot: incremental update
    exec python -m trader_analysis update "${@:2}"
    ;;
  temperature)
    # One-shot: calculate market temperature
    exec python -m trader_analysis temperature
    ;;
  run)
    # One-shot: full strategy pipeline
    exec python -m trader_analysis run "${@:2}"
    ;;
  *)
    exec "$@"
    ;;
esac
