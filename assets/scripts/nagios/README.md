# Nagios Event Handler for py-phone-caller

This directory contains a Bash script designed to be used as a Nagios Core event handler. It triggers a phone call through the `asterisk_caller` API when a monitored service reaches a confirmed `CRITICAL` / `HARD` state.

## Files

* `nagios_event_handler_call.sh`: Event handler script that posts to `asterisk_caller`.

## Prerequisites

* `bash` and `curl` available on the Nagios server.
* `asterisk_caller` reachable from the Nagios server.
* A callable API endpoint, normally `http://py-phone-caller.lan:8081/call_to_queue`.

## Installation

1. Copy `nagios_event_handler_call.sh` to your Nagios plugins or scripts directory, for example `/usr/local/nagios/libexec/` or `/usr/local/nagios/etc/objects/scripts/`.
2. Make the script executable:

   ```bash
   chmod +x /path/to/nagios_event_handler_call.sh
   ```

3. Configure the target API URL with `PY_PHONE_CALLER_API_BASE_URL` or pass it as argument 7 from the Nagios command definition. Optionally set `PY_PHONE_CALLER_TARGET_PHONE` or pass the target as argument 8.

## Configuration values

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| `PY_PHONE_CALLER_API_BASE_URL` | Yes, unless argument 7 is passed | none | Full `asterisk_caller` queue endpoint, for example `http://py-phone-caller.lan:8081/call_to_queue`. |
| `PY_PHONE_CALLER_TARGET_PHONE` | No | `oncall` | Destination phone number or the address-book `oncall` alias. |
| `PY_PHONE_CALLER_CURL_TIMEOUT` | No | `10` | Maximum request time in seconds. Keep this low so Nagios workers do not hang. |

Do not include `phone` or `message` in `PY_PHONE_CALLER_API_BASE_URL`. The script appends those query parameters with `curl --data-urlencode` and sends the request as `POST`, which matches the current `asterisk_caller` API.

## Nagios configuration

### 1. Define the command

Add the following command definition to your Nagios configuration, for example `commands.cfg`:

```nagios
define command {
    command_name    notify-by-phone-call
    command_line    /path/to/nagios_event_handler_call.sh $SERVICESTATE$ $SERVICESTATETYPE$ $SERVICEATTEMPT$ "$HOSTNAME$" "$SERVICEDESC$" "$SERVICEOUTPUT$" "http://py-phone-caller.lan:8081/call_to_queue" "oncall"
}
```

Alternatively, export the values in the Nagios service environment if your Nagios packaging preserves custom environment variables:

```bash
export PY_PHONE_CALLER_API_BASE_URL="http://py-phone-caller.lan:8081/call_to_queue"
export PY_PHONE_CALLER_TARGET_PHONE="oncall"
export PY_PHONE_CALLER_CURL_TIMEOUT="10"
```

### 2. Enable event handler for a service

Add the `event_handler` directive to the service definition you want to monitor:

```nagios
define service {
    host_name              myserver
    service_description    CPU Load
    check_command          check_load
    event_handler          notify-by-phone-call
    event_handler_enabled  1
    ...
}
```

## Runtime behavior

When the service `CPU Load` on `myserver` enters a `CRITICAL` state and the state type is `HARD`, the script will:

1. Construct a message: `Alert. Host myserver. Service CPU Load is CRITICAL. <Check Output>`.
2. Send a `POST` request to the configured endpoint.
3. Add URL-encoded `phone` and `message` query parameters using `curl`.

The script intentionally ignores `SOFT` states and `OK` recovery states by default to avoid alert noise. Recovery-call examples are left commented in the script if you want to enable them later.

## Manual test

Run this from the Nagios server to verify connectivity without editing the script:

```bash
/path/to/nagios_event_handler_call.sh \
  CRITICAL \
  HARD \
  1 \
  "demo-host" \
  "Demo Service" \
  "This is a test alert from Nagios" \
  "http://py-phone-caller.lan:8081/call_to_queue" \
  "oncall"
```

Expected result: `asterisk_caller` returns JSON similar to `{"status": 200}` and the call is queued.

## Customization

You can configure `nagios_event_handler_call.sh` without editing the file:

* Set `PY_PHONE_CALLER_API_BASE_URL` or pass argument 7 to change the API endpoint.
* Set `PY_PHONE_CALLER_TARGET_PHONE` or pass argument 8 to change the target phone number.
* Set `PY_PHONE_CALLER_CURL_TIMEOUT` to tune the HTTP timeout.
* Adjust the script logic if you want to alert on `WARNING` or recovery `OK` states.

## Troubleshooting

* `Error: PY_PHONE_CALLER_API_BASE_URL or argument 7 must be set`: pass the endpoint in the command definition or export the variable in the Nagios runtime environment.
* `Error: curl is required but was not found in PATH`: install `curl` on the Nagios server.
* `curl: (22)`: the API returned an HTTP error such as `400` or `500`; check the `asterisk_caller` service logs.
* `curl: (7)` or timeout errors: verify DNS, firewall rules, and that `asterisk_caller` is listening on the configured host and port.
