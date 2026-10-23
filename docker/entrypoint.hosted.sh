#!/bin/sh
set -e

log() {
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%S.%3NZ')] $1"
}

# Ensure glibc prefers IPv4 over IPv6 in IPv4-only cloud container environments (e.g. Render)
if [ -w /etc/gai.conf ] || [ ! -f /etc/gai.conf ]; then
    echo "precedence ::ffff:0:0/96 100" >> /etc/gai.conf 2>/dev/null || true
fi

# Ensure HOME points to user home directory so libpq SSL does not attempt to read /root
export HOME="/home/app"
mkdir -p /home/app && chown -R app:app /home/app 2>/dev/null || true

log "==> Validating required secrets..."
if [ -z "$DATABASE_URL" ]; then
    log "ERROR: Missing required secret: DATABASE_URL is not set. Exiting."
    exit 1
fi

if [ -z "$BACKEND_MQTT_PASSWORD" ]; then
    log "ERROR: Missing required secret: BACKEND_MQTT_PASSWORD is not set. Exiting."
    exit 1
fi

if [ -z "$MQTT_PASSWORD" ]; then
    log "ERROR: Missing required secret: MQTT_PASSWORD is not set. Exiting."
    exit 1
fi

if [ -z "$WATER_MQTT_PASSWORD" ]; then
    log "ERROR: Missing required secret: WATER_MQTT_PASSWORD is not set. Exiting."
    exit 1
fi

if [ -z "$PLANT_WATER_DISTRICT_9_VIEWER_TOKEN" ]; then
    log "ERROR: Missing required secret: PLANT_WATER_DISTRICT_9_VIEWER_TOKEN is not set. Exiting."
    exit 1
fi

if [ "$BACKEND_MQTT_PASSWORD" = "$MQTT_PASSWORD" ] || \
   [ "$BACKEND_MQTT_PASSWORD" = "$WATER_MQTT_PASSWORD" ] || \
   [ "$MQTT_PASSWORD" = "$WATER_MQTT_PASSWORD" ]; then
    log "ERROR: Device and service passwords must be unique. Detected identical passwords. Exiting."
    exit 1
fi

# Hardening: ADMIN_TOKEN and ADMIN_SECRET_TOKEN must stay unset on hosted
if [ -n "$ADMIN_TOKEN" ] || [ -n "$ADMIN_SECRET_TOKEN" ]; then
    log "WARNING: ADMIN_TOKEN / ADMIN_SECRET_TOKEN should stay unset on hosted deployment. Unsetting them now to enforce security posture."
    unset ADMIN_TOKEN
    unset ADMIN_SECRET_TOKEN
fi

export PORT="${PORT:-8000}"
export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MOSQUITTO_AUTH_DIR="${MOSQUITTO_AUTH_DIR:-/mosquitto/auth}"
export RETENTION_DAYS="${RETENTION_DAYS:-2}"
export ENABLE_RETENTION_WORKER="${ENABLE_RETENTION_WORKER:-true}"
export DEMO_MAX_SECONDS_PER_DAY="${DEMO_MAX_SECONDS_PER_DAY:-1800}"

export BACKEND_MQTT_USER="${BACKEND_MQTT_USER:-backend_service}"

export SIMULATOR_MQTT_USER="${MQTT_USER:-device_plant_demo_membrane}"
export SIMULATOR_MQTT_CLIENT_ID="${MQTT_CLIENT_ID:-client_demo_membrane_sim}"
export SIMULATOR_MQTT_PASSWORD="$MQTT_PASSWORD"
export DEVICE_DEVICE_PLANT_DEMO_MEMBRANE_PASSWORD="$MQTT_PASSWORD"
export MQTT_PASSWORD_DEMO="$MQTT_PASSWORD"

export WATER_MQTT_USER="${WATER_MQTT_USER:-device_plant_water_district_9}"
export WATER_MQTT_CLIENT_ID="${WATER_MQTT_CLIENT_ID:-gateway_district9_cellular}"
export DEVICE_DEVICE_PLANT_WATER_DISTRICT_9_PASSWORD="$WATER_MQTT_PASSWORD"

if [ -n "$DATABASE_URL_UNPOOLED" ]; then
    log "==> Running database migrations using unpooled direct URL (DATABASE_URL_UNPOOLED)..."
    export DATABASE_URL_UNPOOLED
else
    log "==> Running database migrations using pooled URL (DATABASE_URL)..."
fi
alembic upgrade head
log "==> Database migrations completed."

log "==> Generating Mosquitto auth files from database..."
mkdir -p "$MOSQUITTO_AUTH_DIR" /mosquitto/data
python scripts/generate_mosquitto_auth.py \
    --from-db \
    --passwd-path "$MOSQUITTO_AUTH_DIR/passwd" \
    --acl-path "$MOSQUITTO_AUTH_DIR/acl.conf" \
    --backend-user "$BACKEND_MQTT_USER" \
    --backend-password "$BACKEND_MQTT_PASSWORD" \
    --plants-dir plants
chown -R app:app /mosquitto /etc/mosquitto /app 2>/dev/null || true
log "==> Mosquitto auth files generated."

log "==> Starting supervisor..."
exec supervisord -c /etc/supervisor/supervisord.conf
