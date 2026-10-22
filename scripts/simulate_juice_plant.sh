#!/usr/bin/env bash
set -euo pipefail

# Simulation helper for plant_citrus_grove_juice
# Usage:
#   ./scripts/simulate_juice_plant.sh [DURATION_SECONDS] [PASSWORD] [PLANT_ID]
# Example:
#   ./scripts/simulate_juice_plant.sh 30
#   ./scripts/simulate_juice_plant.sh 60 "E-7KfOHryRONXOJDiWKWp_Ziu_HhiC16XySNLkzUhcc"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/simulate_juice_plant.py"

DURATION="${1:-30}"
PASSWORD="${2:-E-7KfOHryRONXOJDiWKWp_Ziu_HhiC16XySNLkzUhcc}"
PLANT_ID="${3:-plant_citrus_grove_juice}"

echo "Starting Citrus Grove Juice Line simulation (${DURATION}s) for '${PLANT_ID}'..."

# Execute via Docker API container where paho-mqtt and internal broker networking are ready
docker compose exec -T api python - \
  --duration "${DURATION}" \
  --password "${PASSWORD}" \
  --plant-id "${PLANT_ID}" \
  < "${PYTHON_SCRIPT}"
