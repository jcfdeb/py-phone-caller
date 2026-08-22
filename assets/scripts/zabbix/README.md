# Zabbix Alert Script for py-phone-caller

This directory contains a Zabbix script media integration for `py-phone-caller`. It triggers phone calls through the `asterisk_caller` API when Zabbix sends an alert to the media type.

## Files

* `zabbix_alert_call.sh`: Script media handler that posts to `asterisk_caller`.

## Prerequisites

* Zabbix Server installed and running.
* `bash` and `curl` available on the Zabbix Server.
* `asterisk_caller` reachable from the Zabbix Server.
* A callable API endpoint, normally `http://py-phone-caller.lan:8081/call_to_queue`.

## Installation

1. **Locate Zabbix AlertScriptsPath**:
   Check your Zabbix Server configuration file, usually `/etc/zabbix/zabbix_server.conf`, for the `AlertScriptsPath` variable.
   Common location: `/usr/lib/zabbix/alertscripts`.

2. **Copy the script**:

   ```bash
   cp zabbix_alert_call.sh /usr/lib/zabbix/alertscripts/
   ```

3. **Set permissions**:

   ```bash
   chmod +x /usr/lib/zabbix/alertscripts/zabbix_alert_call.sh
   chown zabbix:zabbix /usr/lib/zabbix/alertscripts/zabbix_alert_call.sh
   ```

4. **Configure the API endpoint**:
   Provide the py-phone-caller API URL either as the `PY_PHONE_CALLER_API_BASE_URL` environment variable available to Zabbix, or as the fourth script parameter in the media type.

## Configuration values

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| `PY_PHONE_CALLER_API_BASE_URL` | Yes, unless parameter 4 is passed | none | Full `asterisk_caller` queue endpoint, for example `http://py-phone-caller.lan:8081/call_to_queue`. |
| `PY_PHONE_CALLER_CURL_TIMEOUT` | No | `10` | Maximum request time in seconds. Keep this low so Zabbix alert workers do not hang. |

Do not include `phone` or `message` in `PY_PHONE_CALLER_API_BASE_URL`. The script appends those query parameters with `curl --data-urlencode` and sends the request as `POST`, which matches the current `asterisk_caller` API.

## Configuration in Zabbix UI

### 1. Create media type

1. Go to **Alerts** -> **Media types**. On older Zabbix versions this can be under **Administration** -> **Media types**.
2. Click **Create media type**.
3. Fill in the following details:
   * **Name**: `Phone Call`, or any name you prefer.
   * **Type**: `Script`.
   * **Script name**: `zabbix_alert_call.sh`.
   * **Script parameters**:
     * `{ALERT.SENDTO}`
     * `{ALERT.SUBJECT}`
     * `{ALERT.MESSAGE}`
     * `http://py-phone-caller.lan:8081/call_to_queue`
4. Click **Add**.

### 2. Configure user media

1. Go to **Users** -> **Users**. On older Zabbix versions this can be under **Administration** -> **Users**.
2. Select the user you want to notify, for example `Admin`.
3. Go to the **Media** tab.
4. Click **Add**.
5. Select the type you created, for example `Phone Call`.
6. **Send to**: enter the destination phone number, for example `0039123456789`, or `oncall` if using the address book feature.
7. Configure active hours and severity as needed.
8. Click **Add**.

### 3. Configure action

1. Go to **Alerts** -> **Actions** -> **Trigger actions**. On older Zabbix versions this can be under **Configuration** -> **Actions** -> **Trigger actions**.
2. Click **Create action**, or edit an existing one.
3. In the **Operations** tab, add a new operation:
   * **Send to users**: select the user configured in the previous step.
   * **Send only to**: select `Phone Call`.
   * **Default subject**: optional, for example `Problem: {EVENT.NAME}`.
   * **Default message**: optional, for example `Host: {HOST.NAME}, Problem: {EVENT.NAME}, Severity: {EVENT.SEVERITY}`.
4. Click **Add**.

## Testing

You can test the script manually from the command line on the Zabbix server:

```bash
/usr/lib/zabbix/alertscripts/zabbix_alert_call.sh \
  "oncall" \
  "Test Subject" \
  "This is a test message from Zabbix" \
  "http://py-phone-caller.lan:8081/call_to_queue"
```

Expected result: `asterisk_caller` returns JSON similar to `{"status": 200}` and the call is queued.

If your Zabbix service environment preserves custom variables, you can also configure the endpoint outside the media type:

```bash
export PY_PHONE_CALLER_API_BASE_URL="http://py-phone-caller.lan:8081/call_to_queue"
export PY_PHONE_CALLER_CURL_TIMEOUT="10"
```

Then keep the media type parameters to only:

```text
{ALERT.SENDTO}
{ALERT.SUBJECT}
{ALERT.MESSAGE}
```

## Troubleshooting

* `Error: PY_PHONE_CALLER_API_BASE_URL or argument 4 must be set`: pass the endpoint as parameter 4 or export the variable in the Zabbix runtime environment.
* `Error: curl is required but was not found in PATH`: install `curl` on the Zabbix server.
* `curl: (22)`: the API returned an HTTP error such as `400` or `500`; check the `asterisk_caller` service logs.
* `curl: (7)` or timeout errors: verify DNS, firewall rules, and that `asterisk_caller` is listening on the configured host and port.
