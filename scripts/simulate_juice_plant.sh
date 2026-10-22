#!/usr/bin/env bash
set -euo pipefail

# Simulation helper for plant_citrus_grove_juice
DURATION="${1:-30}"
PASSWORD="${2:-E-7KfOHryRONXOJDiWKWp_Ziu_HhiC16XySNLkzUhcc}"
PLANT_ID="plant_citrus_grove_juice"
USER_NAME="device_${PLANT_ID}"

echo "Starting telemetry simulation for ${PLANT_ID} (${DURATION} seconds)..."

for i in $(seq 1 "${DURATION}"); do
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # 1. Extractor 01
  feed=$(awk -v i="$i" 'BEGIN{srand(); printf "%.1f", 94.0 + sin(i/3)*3 + (rand()*1.5)}')
  pulp=$(awk -v i="$i" 'BEGIN{srand(); printf "%.1f", 10.2 + cos(i/4)*0.8 + (rand()*0.4)}')
  vib=$(awk -v i="$i" 'BEGIN{srand(); printf "%.2f", 1.20 + sin(i/2)*0.15 + (rand()*0.1)}')

  docker compose exec -T broker mosquitto_pub \
    -u "${USER_NAME}" \
    -P "${PASSWORD}" \
    -t "plants/${PLANT_ID}/assets/extractor_01/telemetry" \
    -m "{\"schema_version\":\"1.0\",\"plant_id\":\"${PLANT_ID}\",\"asset_id\":\"extractor_01\",\"device_timestamp\":\"$ts\",\"message_id\":\"msg-ext-$ts\",\"payload\":{\"status\":\"RUNNING\",\"metrics\":{\"feed_rate_lpm\":$feed,\"pulp_density_pct\":$pulp,\"motor_vibration_mms\":$vib}}}"

  # 2. Pasteurizer 01
  brix=$(awk -v i="$i" 'BEGIN{srand(); printf "%.1f", 11.8 + sin(i/5)*0.4 + (rand()*0.2)}')
  temp=$(awk -v i="$i" 'BEGIN{srand(); printf "%.1f", 72.5 + cos(i/3)*1.2 + (rand()*0.3)}')
  tube=$(awk -v i="$i" 'BEGIN{srand(); printf "%.2f", 2.80 + sin(i/4)*0.15 + (rand()*0.05)}')

  docker compose exec -T broker mosquitto_pub \
    -u "${USER_NAME}" \
    -P "${PASSWORD}" \
    -t "plants/${PLANT_ID}/assets/pasteurizer_01/telemetry" \
    -m "{\"schema_version\":\"1.0\",\"plant_id\":\"${PLANT_ID}\",\"asset_id\":\"pasteurizer_01\",\"device_timestamp\":\"$ts\",\"message_id\":\"msg-past-$ts\",\"payload\":{\"status\":\"RUNNING\",\"metrics\":{\"brix_level\":$brix,\"pasteurization_temp_c\":$temp,\"tube_pressure_bar\":$tube}}}"

  # 3. Filler 01
  vol=$(awk -v i="$i" 'BEGIN{srand(); printf "%.1f", 500.0 + sin(i/2)*2.0 + (rand()*1.0)}')
  bpm=$(awk -v i="$i" 'BEGIN{srand(); printf "%.0f", 120 + sin(i/4)*5 + (rand()*2)}')
  press=$(awk -v i="$i" 'BEGIN{srand(); printf "%.1f", 25.0 + cos(i/3)*1.5 + (rand()*0.5)}')

  docker compose exec -T broker mosquitto_pub \
    -u "${USER_NAME}" \
    -P "${PASSWORD}" \
    -t "plants/${PLANT_ID}/assets/filler_01/telemetry" \
    -m "{\"schema_version\":\"1.0\",\"plant_id\":\"${PLANT_ID}\",\"asset_id\":\"filler_01\",\"device_timestamp\":\"$ts\",\"message_id\":\"msg-fill-$ts\",\"payload\":{\"status\":\"RUNNING\",\"metrics\":{\"fill_volume_ml\":$vol,\"filling_speed_bpm\":$bpm,\"cleanroom_pressure_pa\":$press}}}"

  # 4. Capper 01
  torq=$(awk -v i="$i" 'BEGIN{srand(); printf "%.2f", 3.20 + sin(i/3)*0.25 + (rand()*0.1)}')
  cvib=$(awk -v i="$i" 'BEGIN{srand(); printf "%.2f", 0.85 + cos(i/2)*0.10 + (rand()*0.05)}')

  docker compose exec -T broker mosquitto_pub \
    -u "${USER_NAME}" \
    -P "${PASSWORD}" \
    -t "plants/${PLANT_ID}/assets/capper_01/telemetry" \
    -m "{\"schema_version\":\"1.0\",\"plant_id\":\"${PLANT_ID}\",\"asset_id\":\"capper_01\",\"device_timestamp\":\"$ts\",\"message_id\":\"msg-cap-$ts\",\"payload\":{\"status\":\"RUNNING\",\"metrics\":{\"capping_torque_nm\":$torq,\"vibration_mms\":$cvib}}}"

  # 5. Inspector 01
  rej=$(awk -v i="$i" 'BEGIN{srand(); printf "%.2f", 0.40 + sin(i/6)*0.15 + (rand()*0.08)}')
  herr=$(awk -v i="$i" 'BEGIN{srand(); printf "%.2f", 0.12 + cos(i/3)*0.08 + (rand()*0.04)}')

  docker compose exec -T broker mosquitto_pub \
    -u "${USER_NAME}" \
    -P "${PASSWORD}" \
    -t "plants/${PLANT_ID}/assets/inspector_01/telemetry" \
    -m "{\"schema_version\":\"1.0\",\"plant_id\":\"${PLANT_ID}\",\"asset_id\":\"inspector_01\",\"device_timestamp\":\"$ts\",\"message_id\":\"msg-insp-$ts\",\"payload\":{\"status\":\"RUNNING\",\"metrics\":{\"reject_rate_pct\":$rej,\"fill_height_error_mm\":$herr}}}"

  echo "[$i/${DURATION}] Streamed live metrics for all 5 citrus juice line machines at $ts"
  sleep 1
done

echo "Simulation completed successfully (${DURATION}s)."
