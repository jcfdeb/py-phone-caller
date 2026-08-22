#!/bin/bash
#
# Zabbix Custom Alert Script - Trigger Phone Call via py-phone-caller
#
# This script is designed to be used as a "Script" Media Type in Zabbix.
# It sends a POST request to the asterisk_caller application to initiate a phone call.
#
# ZABBIX PARAMETERS:
#   $1 = Send to (The recipient's phone number or 'oncall' alias)
#   $2 = Subject (The subject of the alert)
#   $3 = Message (The body of the alert)
#   $4 = Optional py-phone-caller API URL when PY_PHONE_CALLER_API_BASE_URL is not set
#

# --- Configuration ---
API_BASE_URL="${PY_PHONE_CALLER_API_BASE_URL:-${4:-}}"

# Timeout in seconds. Keep it short so Zabbix alert worker processes don't hang.
CURL_TIMEOUT="${PY_PHONE_CALLER_CURL_TIMEOUT:-10}"

# --- Argument Parsing ---
RECIPIENT="$1"
SUBJECT="$2"
MESSAGE_BODY="$3"

if [ -z "$API_BASE_URL" ]; then
    echo "Error: PY_PHONE_CALLER_API_BASE_URL or argument 4 must be set, for example http://py-phone-caller.lan:8081/call_to_queue" >&2
    exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "Error: curl is required but was not found in PATH" >&2
    exit 2
fi

# --- Main Logic ---

# Validate Recipient.
if [ -z "$RECIPIENT" ]; then
    echo "Warning: No recipient specified. Defaulting to 'oncall'."
    RECIPIENT="oncall"
fi

# Combine Subject and Message for the voice call.
# We add a pause (period) between them for better TTS rhythm.
RAW_MESSAGE="${SUBJECT}. ${MESSAGE_BODY}"

# Execute the request.
# --request POST: Use POST method.
# --silent / --show-error: Keep output concise but show errors.
# --fail: Return an error for HTTP 4xx / 5xx responses.
# --get + --data-urlencode: Keep parameters in the query string as expected by asterisk_caller.
# --max-time: Timeout quickly to prevent Zabbix from hanging.
curl --request POST \
    --silent \
    --show-error \
    --fail \
    --get \
    --max-time "${CURL_TIMEOUT}" \
    --data-urlencode "phone=${RECIPIENT}" \
    --data-urlencode "message=${RAW_MESSAGE}" \
    "${API_BASE_URL}"

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "Error: Failed to trigger phone call. Curl exit code: $EXIT_CODE" >&2
    exit $EXIT_CODE
fi

exit 0
