#!/usr/bin/env bash
# ==============================================================================
# Script: manage_services.sh
# Project: py-phone-caller
#
# Purpose:
#   Full lifecycle manager (start, stop, restart, status, logs) for all 11
#   py-phone-caller microservices executing directly on the host using `uv`.
#
# Why Run Directly on Host:
#   Building container images for all services (Kokoro TTS models, PyTorch,
#   C-extensions, Celery workers) takes significant time and resources. Running
#   services directly on the host using `uv` allows instant startup, real-time
#   debugging, and sub-second feedback during development and testing.
#
# Managed Services:
#   1.  caller_register         - Call lifecycle registry & audit state machine (port 8083)
#   2.  generate_audio          - Kokoro TTS / Facebook MMS audio synthesis server (port 8082)
#   3.  caller_address_book     - Emergency contacts & on-call address book API (port 8087)
#   4.  asterisk_caller         - Asterisk ARI dialer with circuit breaker & PJSIP probing (port 8081)
#   5.  asterisk_ws_monitor     - Asterisk WebSocket event monitor (background daemon)
#   6.  caller_sms              - SMS dispatch with sovereign modem & two-way ACK (port 8085)
#   7.  caller_prometheus_webhook - Prometheus Alertmanager webhook ingress (port 8084)
#   8.  caller_scheduler        - Dynamic call scheduler & calendar integration (port 8086)
#   9.  py_phone_caller_ui      - Flask / Gunicorn management UI & audit dashboard (port 5000)
#   10. celery_worker           - Celery background worker & Celery Beat scheduler (background daemon)
#   11. asterisk_recaller       - Dead-letter redialer & escalation loop daemon (background daemon)
#
# Runtime Artifacts:
#   - PIDs: /tmp/py-phone-caller/pids/<service_name>.pid
#   - Logs: /tmp/py-phone-caller/logs/<service_name>.log
#   - Celery Beat Schedule: /tmp/py-phone-caller/celerybeat-schedule
#
# Commands:
#   ./src/manage_services.sh start             # Start all services
#   ./src/manage_services.sh stop              # Stop all services gracefully
#   ./src/manage_services.sh restart           # Restart all services
#   ./src/manage_services.sh status            # Show real-time PID & port status table
#   ./src/manage_services.sh logs [service]    # Tail live logs for a service or all services
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Runtime state directories
RUN_DIR="/tmp/py-phone-caller"
PID_DIR="$RUN_DIR/pids"
LOG_DIR="$RUN_DIR/logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

# Configuration discovery: prefer dist configuration if present, otherwise default src/config
if [[ -d "$REPO_ROOT/docs/openalert/dist/py-phone-caller/config" ]]; then
    export CALLER_CONFIG_DIR="$REPO_ROOT/docs/openalert/dist/py-phone-caller/config"
else
    export CALLER_CONFIG_DIR="$REPO_ROOT/src/config"
fi

export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT/src/py-phone-caller-utils"
export PICCOLO_CONF="py_phone_caller_utils.py_phone_caller_db.piccolo_conf"
export PYTHONUNBUFFERED=1

# Color formatting
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Microservices registry
# Format: name|run_cmd|port(or 0 if worker/daemon)
SERVICES=(
    "caller_register|uv run python -m caller_register.caller_register|8083"
    "generate_audio|uv run python -m generate_audio.generate_audio|8082"
    "caller_address_book|uv run python -m caller_address_book.caller_address_book|8087"
    "asterisk_caller|uv run python -m asterisk_caller.asterisk_caller|8081"
    "asterisk_ws_monitor|uv run python -m asterisk_ws_monitor.asterisk_ws_monitor|0"
    "caller_sms|uv run python -m caller_sms.caller_sms|8085"
    "caller_prometheus_webhook|uv run python -m caller_prometheus_webhook.caller_prometheus_webhook|8084"
    "caller_scheduler|uv run python -m caller_scheduler.caller_scheduler|8086"
    "py_phone_caller_ui|uv run gunicorn -w 2 -b 0.0.0.0:5000 py_phone_caller_ui.app:app|5000"
    "celery_worker|uv run celery -A py_phone_caller_utils.tasks.celery_task worker -B -s /tmp/py-phone-caller/celerybeat-schedule -Q telephony.p0,telephony.p2,telephony.dlq,celery --loglevel=info|0"
    "asterisk_recaller|uv run python -m asterisk_recaller.asterisk_recaller|0"
)

get_actual_pid() {
    local pid_file="$PID_DIR/$1.pid"
    if [[ -f "$pid_file" ]]; then
        local p
        p=$(cat "$pid_file" 2>/dev/null || true)
        if [[ -n "$p" ]] && kill -0 "$p" 2>/dev/null; then
            echo "$p"
            return 0
        fi
    fi
    return 1
}

is_running() {
    get_actual_pid "$1" >/dev/null 2>&1
}

start_service() {
    local s_name="$1"
    local s_cmd="$2"
    local s_port="$3"

    if is_running "$s_name"; then
        local cur_pid
        cur_pid=$(get_actual_pid "$s_name")
        echo -e "  [${YELLOW}SKIP${NC}] $s_name is already running (PID: $cur_pid)"
        return 0
    fi

    local log_file="$LOG_DIR/$s_name.log"
    echo -e "  [${BLUE}STARTING${NC}] $s_name..."

    # Use setsid to dissociate completely from the calling shell's process group
    cd "$REPO_ROOT"
    setsid bash -c "exec $s_cmd" >> "$log_file" 2>&1 < /dev/null &
    local spawned_pid=$!
    echo "$spawned_pid" > "$PID_DIR/$s_name.pid"

    # Give process a moment to initialize
    sleep 1.2

    if kill -0 "$spawned_pid" 2>/dev/null; then
        if [[ "$s_port" != "0" ]]; then
            echo -e "  [${GREEN}OK${NC}] $s_name started (PID: $spawned_pid, port: $s_port)"
        else
            echo -e "  [${GREEN}OK${NC}] $s_name started (PID: $spawned_pid, background daemon)"
        fi
    else
        echo -e "  [${RED}FAIL${NC}] $s_name failed to start. Last log entries:"
        tail -n 6 "$log_file" | sed 's/^/         /'
    fi
}

stop_service() {
    local s_name="$1"
    local pid_file="$PID_DIR/$s_name.pid"

    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [[ -n "$pid" ]]; then
            echo -e "  [${YELLOW}STOPPING${NC}] $s_name (PID: $pid)..."
            # Kill process and child processes in its process group
            pkill -P "$pid" 2>/dev/null || true
            kill "$pid" 2>/dev/null || true

            for _ in {1..10}; do
                if kill -0 "$pid" 2>/dev/null; then
                    sleep 0.3
                else
                    break
                fi
            done

            if kill -0 "$pid" 2>/dev/null; then
                pkill -9 -P "$pid" 2>/dev/null || true
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$pid_file"
        echo -e "  [${GREEN}STOPPED${NC}] $s_name"
    else
        echo -e "  [${YELLOW}NOT RUNNING${NC}] $s_name"
    fi
}

check_status() {
    echo -e "\n${CYAN}================================================================${NC}"
    echo -e "${CYAN} py-phone-caller Local Services Status                          ${NC}"
    echo -e "${CYAN} Configuration: $CALLER_CONFIG_DIR                              ${NC}"
    echo -e "${CYAN}================================================================${NC}"
    printf "%-28s %-10s %-8s %-12s\n" "SERVICE" "STATUS" "PID" "PORT / INFO"
    echo "----------------------------------------------------------------"

    for item in "${SERVICES[@]}"; do
        IFS="|" read -r name cmd port <<< "$item"
        if is_running "$name"; then
            local pid
            pid=$(get_actual_pid "$name")
            local info="port: $port"
            [[ "$port" == "0" ]] && info="daemon"
            printf "%-28s ${GREEN}%-10s${NC} %-8s %-12s\n" "$name" "RUNNING" "$pid" "$info"
        else
            printf "%-28s ${RED}%-10s${NC} %-8s %-12s\n" "$name" "STOPPED" "-" "-"
        fi
    done
    echo "----------------------------------------------------------------"
    echo -e "Logs available in: ${YELLOW}$LOG_DIR${NC}\n"
}

start_all() {
    echo -e "\n${CYAN}Starting all py-phone-caller local services...${NC}"
    echo -e "Config: ${YELLOW}$CALLER_CONFIG_DIR${NC}\n"

    for item in "${SERVICES[@]}"; do
        IFS="|" read -r name cmd port <<< "$item"
        start_service "$name" "$cmd" "$port"
    done

    echo -e "\n${GREEN}All services requested to start.${NC}"
    check_status
}

stop_all() {
    echo -e "\n${CYAN}Stopping all py-phone-caller local services...${NC}"
    for item in "${SERVICES[@]}"; do
        IFS="|" read -r name cmd port <<< "$item"
        stop_service "$name"
    done
    echo -e "\n${GREEN}All services stopped.${NC}\n"
}

tail_logs() {
    local target="${1:-}"
    if [[ -n "$target" ]]; then
        local target_log="$LOG_DIR/$target.log"
        if [[ -f "$target_log" ]]; then
            echo -e "${CYAN}Tailing $target_log (Ctrl+C to stop)...${NC}"
            tail -f "$target_log"
        else
            echo -e "${RED}Log file $target_log does not exist.${NC}"
        fi
    else
        echo -e "${CYAN}Tailing all logs in $LOG_DIR (Ctrl+C to stop)...${NC}"
        tail -f "$LOG_DIR"/*.log
    fi
}

case "${1:-}" in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 1
        start_all
        ;;
    status)
        check_status
        ;;
    logs)
        tail_logs "${2:-}"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [service_name]}"
        exit 1
        ;;
esac
