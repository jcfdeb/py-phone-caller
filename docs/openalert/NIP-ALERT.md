# NIP-ALERT: Decentralized Critical Alert Events & Out-of-Band Bridging

`draft` `optional` `author:fdpergolini` `author:Jorge C. Franco`

This NIP defines a standardized event schema, encryption envelope, radio-safe payload MTU, and operator Command-and-Control (C2) protocol for publishing, routing, and acknowledging critical alerts over Nostr and bridging them across off-grid / out-of-band transports (sub-GHz LoRa, Bluetooth Low Energy mesh, GSM/LTE SMS, and SIP/PSTN voice telephony).

---

## 1. Abstract & Motivation

During internet shutdowns, state censorship, natural disasters, or infrastructure failures, centralized push notifications (APNs, FCM) and cloud messaging platforms fail. While Nostr provides censorship-resistant relay gossip over IP networks, critical alerts often originate from—or must be delivered to—off-grid field nodes operating over constrained physical transports:

- **Sub-GHz LoRa RF** (e.g., ETSI EN 300 220 868 MHz with 1% duty-cycle constraints and ~200–255 byte physical frames)
- **Bluetooth Low Energy (BLE) GATT Mesh** (e.g., BitChat peripheral/central flood meshes)
- **Cellular GSM/LTE SMS** (160-character GSM-7 or 70-character UCS-2 segments)
- **Offline Neural Text-to-Speech (TTS) Voice Calls** over sovereign SIP/PSTN/GSM gateways (`py-phone-caller`)

Standardizing critical alert events on Nostr enables:
1. **Deterministic Deduplication & State Replacement**: Using parameterized replaceable events (`Kind 30000`) keyed by a globally unique `alert_id` (`d` tag) so relays retain the latest state of an active incident without flooding subscribers.
2. **Cross-Transport Payload Fidelity**: Enforcing a strict **500-byte UTF-8 plaintext summary ceiling** and canonical summary grammar so alerts traverse Nostr relays, LoRa links, BLE meshes, SMS gateways, and TTS voice calls without loss of critical context (category, sender, GPS coordinates, message, and originating node).
3. **Configurable Privacy Modes**: Supporting both public cleartext advisories and zero-metadata encrypted group/direct envelopes (`XChaCha20-Poly1305` AEAD for shared-key meshes and `NIP-17`/`NIP-59` Gift Wraps for 1-on-1 operator notifications).
4. **Interactive Operator Acknowledgment (C2)**: Allowing authorized responders using standard Nostr clients (such as `0xChat`, Damus, or Amethyst) to query node status, acknowledge active alerts (`ack`), or bridge messages back into local BLE/SMS meshes.

---

## 2. Multi-Kind Event Architecture

Implementations of this NIP operate across three complementary Nostr event classes:

| Role | Event Kind(s) | NIP Dependencies | Protocol Behavior |
| :--- | :--- | :--- | :--- |
| **Canonical Stateful Alert** | `Kind 30000` *(default)* | NIP-01, NIP-20, NIP-33, NIP-40 | Parameterized replaceable event keyed by `(pubkey, 30000, d-tag)`. Relays retain the latest state per `alert_id`. |
| **Public Timeline Broadcast & Threaded Replies** | `Kind 1` | NIP-01, NIP-10, NIP-40 | Human-readable Markdown alert card for public timeline subscribers and NIP-10 threaded operator C2 replies (`["e", "<id>", "", "reply"]`). |
| **End-to-End Encrypted Direct Alert & C2** | `Kind 1059` (`Kind 13` → `Kind 14`) & `Kind 4` *(legacy fallback)* | NIP-17, NIP-44, NIP-59, NIP-04 | Zero-metadata direct alert delivery to subscribed responders and authenticated operator C2 commands. |

---

## 3. Canonical Summary Grammar & Radio-Safe 500-Byte MTU

To guarantee that any Nostr alert can be bridged over sub-GHz LoRa serial links, BLE GATT notifications, and cellular SMS without dropping the originating node identifier or GPS coordinates:

1. **Maximum Summary Length**: The raw message body MUST NOT exceed **500 UTF-8 bytes**.
2. **Canonical Summary Format**:
   ```text
   [<CATEGORY>] (<SENDER> | GPS:<LAT>,<LON> (±<ACC>m)): <MESSAGE> [<NODE_NAME>]
   ```
   - `<CATEGORY>` *(optional)*: Uppercase incident classification (e.g., `MEDICAL`, `SECURITY`, `FIRE`, `INFRASTRUCTURE`, `SOS`). Omitted if `GENERAL` or unspecified.
   - `<SENDER>` *(optional)*: Callsign, operator handle, or sensor identifier, optionally followed by `| GPS:<lat>,<lon> (±<accuracy>m)` when hardware or browser geolocation is available.
   - `<MESSAGE>` *(mandatory)*: Human-readable alert summary (1–500 UTF-8 bytes).
   - `[<NODE_NAME>]` *(recommended)*: Appended at the end of the summary so downstream voice TTS and SMS recipients immediately hear or read which physical node originated the alert.

### Examples
```text
[MEDICAL] (Jorge | GPS:41.90280,12.49640 (±6m)): Urgent evacuation required at sector 4 [openalertd-fog-arm]
```
```text
[SOS] (Maria): Main power feed failure on repeater station B [node02-solar]
```

---

## 4. Stateful Alert Events (`Kind 30000`)

### 4.1. Tag Schema

Every `Kind 30000` alert event MUST include a `d` tag and at least one topic tag `["t", "alert"]` or `["t", "openalert"]` so subscribers and relays can distinguish alert events from generic NIP-51 categorized people lists (which also use `Kind 30000`, e.g., `["d", "Chat-Friends"]`).

| Tag Key | Cleartext Mode | Encrypted Mode | Value Format & Semantics |
| :--- | :--- | :--- | :--- |
| `d` | **Mandatory** | **Mandatory** | Globally unique `alert_id` string (e.g., `sos-a1b2c3d4-1761854000000`). Serves as the NIP-33 replaceable key and cross-transport deduplication identifier. |
| `t` | **Mandatory** | **Mandatory** | Must include `"openalert"` and/or `"alert"`. Cleartext events SHOULD include both `["t", "alert"]` and `["t", "openalert"]`. |
| `severity` | **Mandatory** | *Omitted (inside ciphertext)* | Lowercase severity level: `"emergency"`, `"critical"`, `"warning"`, or `"info"`. |
| `source` | **Recommended** | *Omitted (inside ciphertext)* | Lowercase origin transport: `"nostr"`, `"rest"`, `"prometheus"`, `"bitchat"`, `"peering"`, `"sms"`, or `"zap"`. |
| `sender` | *Optional* | *Omitted (inside ciphertext)* | Originating callsign, service name, or hex pubkey. |
| `node` | *Optional* | *Omitted (inside ciphertext)* | Originating node or hostname (e.g., `"openalertd-fog-arm"`). |
| `enc` | *Omitted* | **Mandatory** | AEAD cipher identifier: `"xchacha20poly1305"` (implementations SHOULD also accept `"chacha20poly1305"` for backward compatibility). |
| `v` | *Omitted* | **Mandatory** | Envelope schema version: `"1"`. |
| `expiration` | **Recommended** | **Recommended** | NIP-40 Unix timestamp in seconds (`created_at + alert_ttl_seconds`) after which relays and subscribers MUST drop the event. |

### 4.2. Cleartext Mode Example (`Kind 30000`)

```json
{
  "id": "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e",
  "pubkey": "7ebd6445ad80abe6b1dca2fff3c0d31f06773af01b6426028374dbca71db4848",
  "created_at": 1761900000,
  "kind": 30000,
  "tags": [
    ["d", "sos-9add0a10-1761900000000"],
    ["severity", "emergency"],
    ["source", "rest"],
    ["t", "alert"],
    ["t", "openalert"],
    ["sender", "Jorge"],
    ["node", "openalertd-fog-arm"],
    ["expiration", "1761903600"]
  ],
  "content": "[MEDICAL] (Jorge | GPS:41.9028,12.4964 (±5m)): Urgent evacuation required [openalertd-fog-arm]",
  "sig": "e4f5a6b7c8d9..."
}
```

### 4.3. Encrypted Group Mode (`XChaCha20-Poly1305` Envelope)

When operating over untrusted public relays where alert metadata (`severity`, `source`, `sender`, `node`, `summary`) must remain confidential across a federation of nodes sharing a 256-bit pre-shared key (`shared_key`):

1. **Plaintext Serialization**: The canonical `Alert` object is serialized as UTF-8 JSON:
   ```json
   {
     "alert_id": "sos-9add0a10-1761900000000",
     "severity": "emergency",
     "summary": "[MEDICAL] (Jorge): Urgent evacuation required [openalertd-fog-arm]",
     "description": "[MEDICAL] (Jorge): Urgent evacuation required [openalertd-fog-arm]",
     "source": "rest",
     "sender": "Jorge",
     "node": "openalertd-fog-arm",
     "starts_at": "2026-10-31T09:00:00Z",
     "destinations": ["webhook", "nostr"],
     "hop": 5
   }
   ```
2. **AEAD Encryption (`XChaCha20-Poly1305`)**:
   - Generate a cryptographically random **24-byte nonce** (`OsRng`).
   - Encrypt the UTF-8 JSON bytes using `XChaCha20Poly1305` with the 32-byte `shared_key`, producing `ciphertext || 16-byte Poly1305 tag`.
   - Concatenate `nonce (24 bytes) || ciphertext || tag (16 bytes)` and encode as standard **Base64** in `event.content`.
3. **Encrypted Event Structure**:
   ```json
   {
     "id": "3a2b1c0d9e8f...",
     "pubkey": "7ebd6445ad80abe6b1dca2fff3c0d31f06773af01b6426028374dbca71db4848",
     "created_at": 1761900000,
     "kind": 30000,
     "tags": [
       ["d", "sos-9add0a10-1761900000000"],
       ["t", "openalert"],
       ["enc", "xchacha20poly1305"],
       ["v", "1"],
       ["expiration", "1761903600"]
     ],
     "content": "<Base64(24-byte XNonce || Ciphertext || 16-byte Poly1305 Tag)>",
     "sig": "b1c2d3e4f5a6..."
   }
   ```

---

## 5. NIP-51 People List Disambiguation & Subscriber Auto-Discovery

Because Nostr clients such as `0xChat` also publish `Kind 30000` events for NIP-51 categorized people lists (e.g., `["d", "Chat-Friends"]`, `["d", "friends"]`, `["d", "contacts"]`), a compliant alert subscriber MUST apply the following disambiguation rule upon receiving a `Kind 30000` event:

1. Check if the event carries an encryption tag (`["enc", "xchacha20poly1305" | "chacha20poly1305"]`), an alert topic tag (`["t", "alert" | "openalert"]`), or a `["severity", ...]` tag (`has_openalert_marker`).
2. If the `d` tag starts with `"Chat-"` or equals `"friends"` / `"contacts"`, OR if `has_openalert_marker` is `false`:
   - The subscriber MUST **not** route the event as an alert.
   - If 0xChat subscriber auto-discovery is enabled, the node MAY register `event.pubkey` as an active subscriber for future outbound alert notifications.

---

## 6. Direct Operator Notifications & Command-and-Control (C2)

### 6.1. Outbound Alert Cards (`Kind 1059` Gift Wrap / `Kind 1`)

To notify human responders on mobile Nostr clients (`0xChat`, Damus, Amethyst), nodes format a human-readable alert card:

```text
🚨🚨 [Emergency ALERT] [MEDICAL] (Jorge): Urgent evacuation required [openalertd-fog-arm]

Node: openalertd-fog-arm
Time: 2026-10-31 09:00:00 UTC
ID: sos-9add0a10-1761900000000
```

- **Direct Message Mode (`dm`)**: Wrapped in a **NIP-17 / NIP-59 Gift Wrap (`Kind 1059`)** containing a NIP-44 encrypted `Kind 13` Seal and `Kind 14` Rumor addressed to each registered subscriber `["p", "<subscriber_pubkey_hex>"]` (with NIP-04 `Kind 4` used only as a fallback if Gift Wrap construction fails).
- **Public Timeline Mode (`public`)**: Published as a signed `Kind 1` note tagged with `["t", "openalert"]`, `["t", "<severity>"]`, and `["d", "<alert_id>"]`.

### 6.2. Inbound Operator C2 Commands

Authorized operator public keys (`c2_authorized_operators`) can send commands to the node via **NIP-17 (`Kind 1059`)**, **NIP-04 (`Kind 4`)**, or **NIP-10 public replies (`Kind 1` mentioning the node's `#p` tag or `#t = "openalert"`)**:

| Command | Syntax | Behavior |
| :--- | :--- | :--- |
| `ping` | `ping` or `!ping` | Returns `🏓 PONG [OpenAlert Daemon]`, current UTC timestamp, and operational state. |
| `status` | `status` or `!status` | Returns node name, software version, uptime, active peering count, Nostr relay count, and pending SQLite spool count. |
| `ack` | `ack [<alert_id>]` or `ok` | Marks `<alert_id>` as `dispatched` in persistent storage. If `<alert_id>` is omitted, resolves the parent alert via NIP-10 `["e", "<parent_event_id>"]` tag lookup (`d` tag of parent event) or acknowledges the most recent pending alert. |
| `mesh` | `mesh <message>` (or `bitchat <message>`) | Broadcasts `<message>` out-of-band over the local Bluetooth Low Energy (BitChat) mesh. |
| `sms` | `sms <phone_number> <message>` | Dispatches `<message>` to `<phone_number>` via the local hardware GSM/LTE AT modem. |
| `help` | `help` or `!help` | Returns the list of supported operator commands. |

### 6.3. Replay & Lookback Protection for NIP-17 C2

Because NIP-59 Gift Wraps (`Kind 1059`) intentionally randomize their outer `created_at` timestamp up to 48 hours into the past to resist traffic analysis, implementations MUST validate the command age against the decrypted **inner `Kind 14` rumor's `created_at` timestamp** (`now - rumor.created_at <= max_c2_age`) and record `c2-ev:<outer_event_id>` in persistent deduplication storage so historical commands are never re-executed on daemon restart.

---

## 7. Delivery Quorum (NIP-20) & Relay Health Scoring

When publishing an alert event to $N$ configured relays:
1. The publisher transmits `["EVENT", <event_json>]` concurrently to all $N$ relays and awaits NIP-20 command results:
   ```json
   ["OK", "<event_id>", true, ""]
   ```
2. Each relay maintains an exponential moving average health score $S \in [0.0, 1.0]$:
   - On NIP-20 acceptance: $S \leftarrow 0.8 \cdot S + 0.2$
   - On timeout, socket error, or NIP-20 rejection: $S \leftarrow 0.6 \cdot S$
3. Delivery succeeds when at least `quorum_min_relays` ($M \le N$) relays return `accepted = true` within `nip20_timeout_seconds`. If quorum is not met, the alert remains in the local SQLite persistent spool (`status = 'pending'`) for automatic retry or failover routing (e.g., LoRa peering or GSM SMS).

---

## 8. Reference Implementation

- **Daemon**: `openalertd` (`src/openalert/`)
  - Egress Publisher & NIP-20 Quorum: [`src/openalert/src/egress/nostr.rs`](../../src/openalert/src/egress/nostr.rs)
  - Ingress Subscriber & C2 Engine: [`src/openalert/src/ingress/nostr.rs`](../../src/openalert/src/ingress/nostr.rs)
  - Emergency `/sos` Portal & Canonical Formatter: [`src/openalert/src/ingress/sos.rs`](../../src/openalert/src/ingress/sos.rs)
  - Embedded Nostr Micro-Relay (NIP-01 / NIP-11 / NIP-20 / NIP-33 / NIP-40 / NIP-57): [`src/openalert/src/nostr_relay/mod.rs`](../../src/openalert/src/nostr_relay/mod.rs)
