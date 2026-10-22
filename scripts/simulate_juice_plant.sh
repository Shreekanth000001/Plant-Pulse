#!/usr/bin/env bash
set -euo pipefail

# Simulation helper for plant_citrus_grove_juice
# Usage:
#   ./scripts/simulate_juice_plant.sh [DURATION_SECONDS|continuous] [PASSWORD] [PLANT_ID]
# Examples:
#   ./scripts/simulate_juice_plant.sh 30
#   ./scripts/simulate_juice_plant.sh continuous
#   ./scripts/simulate_juice_plant.sh 0 "E-7KfOHryRONXOJDiWKWp_Ziu_HhiC16XySNLkzUhcc"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/simulate_juice_plant.py"

ARG1="${1:-30}"
if [[ "$ARG1" == "continuous" || "$ARG1" == "forever" || "$ARG1" == "--continuous" ]]; then
  DURATION=0
else
  DURATION="$ARG1"
fi

PASSWORD="${2:-E-7KfOHryRONXOJDiWKWp_Ziu_HhiC16XySNLkzUhcc}"
PLANT_ID="${3:-plant_citrus_grove_juice}"

if [[ "$DURATION" -eq 0 ]]; then
  echo "Starting Citrus Grove Juice Line continuous simulation (indefinite) for '${PLANT_ID}' (Ctrl+C to stop)..."
else
  echo "Starting Citrus Grove Juice Line simulation (${DURATION}s) for '${PLANT_ID}'..."
fi

# Execute via Docker API container where paho-mqtt and internal broker networking are ready
docker compose exec -T api python - \
  --duration "${DURATION}" \
  --password "${PASSWORD}" \
  --plant-id "${PLANT_ID}" \
  < "${PYTHON_SCRIPT}"
