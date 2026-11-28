# 5-Minute Local Quickstart (Zero VoIP Trunk Needed)

Want to hear **py-phone-caller** place a real synthesized voice call, acknowledge it by pressing **`4`** on your keypad, and receive an instant text alert — **without paying for a SIP trunk or attaching cellular hardware**?

This quickstart uses the free, open-source **[Linphone](https://www.linphone.org/)** softphone (Linux, macOS, Windows, Android, or iOS) registered directly to local Asterisk PJSIP extension **`1000`**.

---

## Architecture of Your Local Sandbox

```mermaid
flowchart LR
    Trigger["curl / Alertmanager / OpenAlert /sos"] --> App["py-phone-caller Suite<br/>(:5000 UI · :8081..8087 APIs)"]
    App -->|"ARI :8088<br/>Voice + SIP MESSAGE"| PBX["Asterisk 22 PBX<br/>(Local PJSIP Exten 1000)"]
    PBX <-->|"SIP :5060 UDP<br/>+ RTP Audio + DTMF '4'"| Phone["Linphone Softphone<br/>(Laptop or Smartphone)"]
```

---

## Step 1: Launch the Stack with Local Extension `1000`

Choose either the **Automated Native Ansible** track (on a disposable Debian 13, Ubuntu 26.04, Rocky 10, or AlmaLinux 10 VM) or **Docker / Podman Compose** (connecting to a local Asterisk instance):

=== "Option A: Automated Native Ansible (VM)"

    Ansible installs PostgreSQL, Redis/Valkey, Asterisk 22, all 11 Python microservices, and `openalertd`, and automatically generates a random 24-character password for local SIP extension **`1000`**:

    ```bash
    cd deploy/ansible
    ansible-galaxy collection install -r requirements.yml -p ./.collections

    # Run against your test VM (ensure asterisk_sip_exten_1000_enabled: true in inventory
    # and asterisk_chan_type = "PJSIP/{phone}" in settings.toml for local softphone dialing):
    ansible-playbook -i /path/to/hosts.yml site.yml \
      -e "asterisk_sip_exten_1000_enabled=true" \
      -e "asterisk_sip_bindaddr=0.0.0.0:5060" \
      --ask-vault-pass
    ```

    At the end of the play, Ansible prints your ready-to-register credentials:

    ```text
    Local SIP extension ready: 1000
    SIP username: 1000
    SIP password: <PASSWORD>
    SIP transport bind: 0.0.0.0:5060 (UDP, context=py-phone-caller, qualify_frequency=0)
    ```

=== "Option B: Docker / Podman Compose + Local Asterisk"

    1. Configure a local Asterisk instance with `[py-phone-caller]` ARI user and PJSIP extension `[1000]` using the copy-paste blocks in **[Asterisk PBX Configuration & Examples](asterisk-pbx-configuration-guide.md)** (setting `asterisk_pass` and extension `1000`'s password to `<PASSWORD>`).
    2. Start the containerized `py-phone-caller` + `openalertd` stack using the prebuilt **GitHub Container Registry (`ghcr.io/jcfdeb`)** images (or append `--build` with `MY_DOCKER_REGISTRY=localhost` to build locally), pointing it at your host IP (`<HOST_IP>`, e.g. `192.168.1.50`):

    ```bash
    export MY_DOCKER_REGISTRY="ghcr.io/jcfdeb"
    export ASTERISK_HOST="<HOST_IP>"
    export ASTERISK_PASS="<PASSWORD>"
    export UI_ADMIN_PASSWORD="<PASSWORD>"
    export UI_SECRET_KEY="<PASSWORD>"
    export DYNACONF_ASTERISK_CALL__ASTERISK_CHAN_TYPE="PJSIP/{phone}"
    export DYNACONF_GENERATE_AUDIO__GENERATE_AUDIO_HOST="<HOST_IP>"

    docker compose -f deploy/compose/docker-compose.yml pull
    docker compose -f deploy/compose/docker-compose.yml up -d
    ```

---

## Step 2: Register Linphone to Extension `1000`

1. Install and open **Linphone** on your workstation or smartphone (connected to the same LAN/VPN as `<HOST_IP>`).
2. Open **Assistant** → **Use a SIP Account** and enter:
    - **Username**: `1000`
    - **SIP Domain**: `<HOST_IP>:5060`
    - **Password**: `<PASSWORD>`
    - **Transport**: `UDP`
3. Click **Use** — the top-left status indicator in Linphone turns **green (`Connected`)**.

Verify on the Asterisk host that Linphone is registered:

```bash
sudo asterisk -rx "pjsip show aor 1000"
```

---

## Step 3: Trigger a Live Voice Call & Press `4` to Acknowledge

Send a queued voice alert to extension `1000`:

```bash
curl -fsS -X POST "http://127.0.0.1:8081/call_to_queue" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "1000",
    "message": "Critical alert on production database cluster. Replication lag exceeded thirty seconds."
  }'
```

**What happens next:**

1. **Linphone rings** within 1–2 seconds (`Caller ID: Py-Phone-Caller`).
2. **Answer the call**: You hear the greeting prompt followed by the offline-synthesized neural TTS voice reading your alert message.
3. **Acknowledge via DTMF**: After the beep, open Linphone's keypad and press **`4`**.
4. Asterisk notifies `caller_register` (`GET /ack`), plays `"Goodbye"`, hangs up, and cancels any further `asterisk_recaller` retry attempts!

---

## Step 4: Send an Instant SIP `MESSAGE` Text Alert

Without any USB GSM modem or Twilio account, `caller_sms` delivers **RFC 3428 SIP `MESSAGE`** chat alerts directly to local SIP extensions:

```bash
curl -fsS -X POST "http://127.0.0.1:8085/send_sms" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "1000",
    "message": "[FIRING] HighMemoryUsage on node-01 (94.2%) — check Grafana dashboard."
  }'
```

Linphone immediately pops up an incoming **SIP chat message** from `py-phone-caller`!

---

## Step 5: Explore the Operator Web UI & OpenAlert `/sos` Portal

1. **py-phone-caller Web Console** (`http://<HOST_IP>:5000`):
    - Sign in (`admin@py-phone-caller.link` / `<PASSWORD>`).
    - Inspect **Managed Calls** (showing `heard_at` and `acknowledge_at` timestamps from your DTMF `4` press), **Managed SMS**, **PBX WebSocket Events**, and **Address Book** (where you can add extension `1000` as your active **On-Call** responder so `"phone": "oncall"` routes to you automatically!).
2. **OpenAlert Mission Control & Emergency SOS Portal** (`http://<HOST_IP>:8090` & `http://<HOST_IP>:8090/sos`):
    - Open `http://<HOST_IP>:8090/sos` on your phone or browser, solve the offline 4-digit SVG CAPTCHA, and dispatch a simulated field emergency — watching it stream live into Mission Control and cascade into `py-phone-caller`!

---

## Next Steps

- Connect real monitoring stacks: **[Prometheus Alertmanager](../src/caller_prometheus_webhook/README.md)**, **[Nagios](../assets/scripts/nagios/README.md)**, or **[Zabbix](../assets/scripts/zabbix/README.md)**.
- Add a commercial SIP trunk or custom dialplan: **[Asterisk PBX Configuration & Examples](asterisk-pbx-configuration-guide.md)**.
- Move to production across **Ansible**, **Docker Compose**, **Kubernetes/Helm**, **DEB/RPM**, or **ARM64 Air-Gapped Appliances**: **[Deployment Hub](../deploy/docs/README.md)**.
