#!/bin/bash
#
# Nagios Event Handler - Trigger Phone Call via py-phone-caller
#
# This script acts as a Nagios Event Handler. When a service enters a specified state
# (default: CRITICAL/HARD), it triggers a phone call by sending a POST request to the
# asterisk_caller application.
#
# USAGE:
#   This script should be called by Nagios with the following arguments:
#   $1 = Service State (e.g., OK, WARNING, CRITICAL, UNKNOWN)
#   $2 = Service State Type (e.g., SOFT, HARD)
#   $3 = Service Attempt (e.g., 1, 2, 3)
#   $4 = Hostname
#   $5 = Service Description
#   $6 = Service Output (The alert message)
#   $7 = Optional py-phone-caller API URL when PY_PHONE_CALLER_API_BASE_URL is not set
#   $8 = Optional recipient phone number or 'oncall' alias when PY_PHONE_CALLER_TARGET_PHONE is not set
#
# EXAMPLE NAGIOS COMMAND DEFINITION:
#   define command {
#       command_name    notify-by-phone-call
#       command_line    /path/to/this/script.sh $SERVICESTATE$ $SERVICESTATETYPE$ $SERVICEATTEMPT$ "$HOSTNAME$" "$SERVICEDESC$" "$SERVICEOUTPUT$" "http://py-phone-caller.lan:8081/call_to_queue" "oncall"
#   }
#

# --- Configuration ---
# API endpoint for placing calls. Configure it with the environment variable
# PY_PHONE_CALLER_API_BASE_URL or pass it as argument 7 from the Nagios command.
API_BASE_URL="${PY_PHONE_CALLER_API_BASE_URL:-${7:-}}"

# Target phone number or 'oncall' for the address book. Configure it with
# PY_PHONE_CALLER_TARGET_PHONE or pass it as argument 8 from the Nagios command.
TARGET_PHONE="${PY_PHONE_CALLER_TARGET_PHONE:-${8:-oncall}}"

# Timeout in seconds. Keep it short so Nagios worker processes don't hang.
CURL_TIMEOUT="${PY_PHONE_CALLER_CURL_TIMEOUT:-10}"

# --- Argument Parsing ---
SERVICE_STATE="$1"
SERVICE_STATE_TYPE="$2"
SERVICE_ATTEMPT="$3"
HOSTNAME="$4"
SERVICE_DESC="$5"
SERVICE_OUTPUT="$6"

if [ -z "$API_BASE_URL" ]; then
    echo "Error: PY_PHONE_CALLER_API_BASE_URL or argument 7 must be set, for example http://py-phone-caller.lan:8081/call_to_queue" >&2
    exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but was not found in PATH" >&2
    exit 2
fi

# --- Main Logic ---

# Check for CRITICAL state and HARD type.
# We only want to alert when the problem is confirmed (HARD state).
if [[ "$SERVICE_STATE" == "CRITICAL" && "$SERVICE_STATE_TYPE" == "HARD" ]]; then

    # Construct the message to be spoken.
    # Example: "Alert. Host Server1. Service CPU Load is CRITICAL. Load is 5.0"
    # Using specific phrasing can help the Text-to-Speech engine.
    RAW_MESSAGE="Alert. Host ${HOSTNAME}. Service ${SERVICE_DESC} is ${SERVICE_STATE}. ${SERVICE_OUTPUT}"

    # Execute the request.
    # --request POST: Use POST method.
    # --silent / --show-error: Keep output concise but show errors.
    # --fail: Return an error for HTTP 4xx / 5xx responses.
    # --get + --data-urlencode: Keep parameters in the query string as expected by asterisk_caller.
    # --max-time: Timeout quickly to prevent Nagios from hanging.
    curl --request POST \
        --silent \
        --show-error \
        --fail \
        --get \
        --max-time "${CURL_TIMEOUT}" \
        --data-urlencode "phone=${TARGET_PHONE}" \
        --data-urlencode "message=${RAW_MESSAGE}" \
        "${API_BASE_URL}"

    # Capture exit code for Nagios logs and manual debugging.
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        echo "Error: Failed to trigger phone call. Curl exit code: $EXIT_CODE" >&2
        exit $EXIT_CODE
    fi

elif [[ "$SERVICE_STATE" == "OK" && "$SERVICE_STATE_TYPE" == "HARD" ]]; then
    # Optional: Recovery Notification
    # Uncomment lines below to enable recovery calls.

    # RAW_MESSAGE="Recovery. Host ${HOSTNAME}. Service ${SERVICE_DESC} is ${SERVICE_STATE}."
    # curl --request POST --silent --show-error --fail --get --max-time "${CURL_TIMEOUT}" \
    #     --data-urlencode "phone=${TARGET_PHONE}" \
    #     --data-urlencode "message=${RAW_MESSAGE}" \
    #     "${API_BASE_URL}"
    :
fi

exit 0
