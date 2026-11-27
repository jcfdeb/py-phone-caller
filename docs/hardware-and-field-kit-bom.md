# Hardware Compatibility & Sovereign Field-Kit BOM Guide

Whether you are assembling a **100% air-gapped datacenter alerting appliance**, an **NGO / civil-defense emergency `/sos` field kit**, or a **hilltop LoRa-to-Asterisk mesh gateway**, this guide documents the reference hardware, USB cellular modems, sub-GHz LoRa transceivers, Bluetooth LE adapters, persistent `udev` rules, and SIP handsets validated with **py-phone-caller** and **OpenAlert (`openalertd`)**.

---

## 1. Three Reference Appliance Archetypes

| Archetype | Target Use Case | Compute Node | Physical Radio / Telephony Peripherals | Recommended Deployment Pillar |
| :--- | :--- | :--- | :--- | :--- |
| **Archetype A — Sovereign NOC / Rack Appliance** | Datacenter, hospital, utility substation, or air-gapped industrial site | **Orange Pi 5 Plus (`RK3588`, 16 GB RAM, NVMe)** or x86_64 Mini-PC | Dual USB 4G/LTE AT modems (carrier diversity) + local Asterisk 22 PBX + PoE SIP desk phones | [09. ARM64 & Air-Gapped Appliance](../deploy/docs/09-arm64-appliance-and-airgapped-deployment.md) |
| **Archetype B — Portable Emergency `/sos` Field Kit** | Disaster response, clinics, community hubs, or blackout zones (`openalertd` standalone) | **Orange Pi Zero 3 (4 GB)** or **Raspberry Pi 5 (4/8 GB)** | Built-in Wi-Fi AP (`OpenAlert-SOS` Captive Portal) + BLE 5.0 (BitChat) + USB LoRa 868/915 MHz + 1x USB GSM modem + 12V LiFePO4 UPS | [OpenAlert Architecture Guide](openalert/README.md) (`install.sh --with-wifi-ap`) |
| **Archetype C — Hilltop Solar Mesh Repeater** | Extending RF coverage between remote valleys/sensors and a central PBX gateway | **Raspberry Pi Zero 2 W** / **Orange Pi Zero 3** (`mesh-repeater.toml`) | Sub-GHz LoRa USB serial transceiver + fiberglass collinear antenna (`5.8 dBi`) + solar MPPT controller | `openalertd` (`config/profiles/mesh-repeater.toml`) |

---

## 2. Single-Board Computers (SBCs) & Host Sizing

### Full Suite (`py-phone-caller` + `Asterisk 22` + `PostgreSQL` + `Redis` + Offline Neural TTS + `openalertd`)

- **Validated Reference ARM64 Appliance**: **Orange Pi 5 Plus** (`Rockchip RK3588` 8-core Cortex-A76/A55, `16 GB` LPDDR4x, M.2 NVMe SSD, dual `2.5 GbE` NICs) running Ubuntu / Armbian (`aarch64`).
    - Synthesizes **Kokoro-82M**, **Silero V3**, and **Piper ONNX** 8000 Hz WAV alerts completely offline on CPU in under `1.2s` with zero GPU requirement.
- **Minimum Full-Suite Sizing**: `4 vCPU` (ARM64 or x86_64), `4 GB RAM` (`8 GB` recommended when preloading multiple TTS engines), `20 GB` SSD/NVMe storage. Avoid running PostgreSQL + TTS caches on consumer microSD cards without wear-leveling; prefer NVMe or industrial eMMC.

### Standalone `openalertd` Edge Node (Rust Binary Only)

- **Footprint**: ~`15–25 MB` RSS RAM, single static/slim binary + embedded SQLite WAL spool.
- **Validated Boards**: **Orange Pi Zero 3**, **Orange Pi 5 Plus**, **Raspberry Pi 4 / 5**, and any Linux `x86_64` / `aarch64` kernel `5.4+`.

---

## 3. Cellular 4G/LTE/GSM USB Modems & Persistent `udev` Rules

Both `py-phone-caller` (`caller_sms` native Rust PyO3 `rust_engine`) and `openalertd` (`src/sms/`) speak standard **3GPP TS 27.005 / 27.007 AT commands** over USB serial (`ttyUSB*`) using **strict UCS-2 hexadecimal PDU/text transcoding** (supporting all international scripts, accents, and alert emojis without corruption).

### Hardware Selection Matrix

| Modem Family | Tested / Compatible Models | Linux Driver & Serial Port | Notes & Operational Tips |
| :--- | :--- | :--- | :--- |
| **SIMCom 4G Cat-4 / Cat-1** *(Recommended)* | **SIM7600E-H** (EU/APAC), **SIM7600G-H** (Global), **SIM7600A-H** (NA), **SIM7100** | Mainline `option` driver; AT port typically `/dev/ttyUSB2` or `/dev/ttyUSB3` | Rock-solid 24/7 stability, external SMA antenna connector, clean `AT+CMGF` / `AT+CSCS="UCS2"` behavior. |
| **Quectel Industrial LTE** *(Recommended)* | **Quectel EC25-E / EC25-AF / EG25-G** (USB dongle or mini-PCIe-to-USB enclosure) | Mainline `option` driver; AT port typically `/dev/ttyUSB2` | Industrial temperature range (`-40°C` to `+85°C`); ideal for unattended cabinets. |
| **Consumer USB Sticks** *(Verify Mode!)* | **Huawei E3372h / E3531** *(Stick/Serial firmware only — NOT HiLink `cdc_ether` RNDIS mode)* | Requires `usb_modeswitch` into serial modem mode (`/dev/ttyUSB0`) | Many consumer sticks ship in NAT router ("HiLink") mode which hides AT serial ports; prefer industrial SIM7600 or Quectel EC25 enclosures. |

> [!WARNING]
> **USB Power Budget (2.0 A RF Burst Peaks) & SIM Preparation**
> 1. Cellular modems draw brief **1.8 A – 2.2 A current spikes** during GSM/LTE registration and SMS transmission. Connect multi-modem setups (`primary_carrier` + `backup_carrier`) through an **externally powered industrial USB 3.0 hub**, never unpowered passive splitters, to prevent USB brownout disconnects.
> 2. **Disable the SIM PIN** on a handset before inserting the SIM into an unattended server (`AT+CPIN?` should return `+CPIN: READY`), and ensure your M2M/IoT tariff includes outbound/inbound SMS.

### Persistent `/etc/udev/rules.d/` Symlinks (Prevent Port Swapping on Reboot)

Linux assigns `/dev/ttyUSB0..7` in enumeration order, which can shift across reboots when two modems or a LoRa dongle share the USB bus. Pin deterministic symlinks (`/dev/modem_primary`, `/dev/modem_backup`, `/dev/lora0`) by USB physical port path or serial number:

```bash
# 1. Inspect the physical USB path and interface number of your AT command port:
udevadm info -a -n /dev/ttyUSB2 | grep -E "KERNEL|KERNELS|ATTRS\{idVendor\}|ATTRS\{idProduct\}|ATTRS\{bInterfaceNumber\}" | head -n 20
```

Create `/etc/udev/rules.d/99-py-phone-caller-radio.rules`:

```ini
# Primary Carrier USB LTE Modem (e.g. SIMCom SIM7600 on USB port 1-1.2, interface 02 = AT port)
SUBSYSTEM=="tty", KERNELS=="1-1.2", ENV{ID_USB_INTERFACE_NUM}=="02", SYMLINK+="modem_primary", GROUP="dialout", MODE="0660"

# Backup Carrier USB LTE Modem (diverse carrier SIM on USB port 1-1.3, interface 02 = AT port)
SUBSYSTEM=="tty", KERNELS=="1-1.3", ENV{ID_USB_INTERFACE_NUM}=="02", SYMLINK+="modem_backup", GROUP="dialout", MODE="0660"

# LoRa Sub-GHz USB Serial Transceiver (CDC-ACM device)
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d4", SYMLINK+="lora0", GROUP="dialout", MODE="0660"
```

Reload `udev` and verify:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
ls -l /dev/modem_primary /dev/modem_backup /dev/lora0
```

---

## 4. Sub-GHz LoRa Serial Transceivers (`openalertd` Peering)

`openalertd` frames compact `postcard`-serialized, `XChaCha20-Poly1305`-encrypted peering datagrams over **SLIP (`END = 0xC0`)** across any transparent serial LoRa transceiver (`/dev/ttyACM*`, `/dev/ttyUSB*`, `/dev/lora0`) while enforcing **ETSI EN 300 220 1.0% airtime duty-cycle** pacing.

- **Recommended Transceiver Hardware**:
    - **SX1262 / SX1276 USB-to-LoRa Serial Adapters** (`868 MHz` for Europe/ITU Region 1; `915 MHz` for Americas/ITU Region 2) configured in transparent serial/UART packet mode (`115200 8N1`) or custom KISS/SLIP firmware outputting optional RSSI/SNR metadata headers.
- **RF & Antenna Best Practices**:
    - **Never power on a LoRa transmitter without an antenna attached** — reflected VSWR energy can permanently damage the SX1262/SX1276 PA stage.
    - Keep `50 Ω` coax runs short (`< 2 m` LMR-200/CFD-200 or `< 5 m` LMR-400); mounting the SBC in a weatherproof IP67 PoE enclosure right at the mast base eliminates coax insertion loss.

---

## 5. Bluetooth Low Energy (BLE) Adapters for BitChat Mesh

`openalertd` advertises a native **BitChat GATT peripheral** via Linux **BlueZ (`5.66+`) D-Bus** using `Noise_XX_25519_ChaChaPoly_SHA256` end-to-end encryption.

- **Onboard SBC Radios**: Tested on onboard combo chips including **Spreadtrum (`uwe5622` on Orange Pi Zero 3)**, **Broadcom/Cypress** (Raspberry Pi 4/5), and **Intel AX200/AX210**. `openalertd` includes automatic HCI adapter power-cycling and GATT re-registration self-healing for embedded Spreadtrum/BlueZ quirks.
- **Rack / Metal Enclosure Tip**: If your server lives inside a grounded steel 19-inch rack, plug in an external **USB BLE 5.0/5.3 Class-1 adapter** (Realtek `RTL8761B` or Cambridge Silicon Radio with external RP-SMA dipole) on a 1.5 m USB extension lead routed outside the cabinet.

---

## 6. SIP Phones, Rugged Handsets & Softphones

Any standard **RFC 3261 PJSIP** endpoint supporting **`ulaw` / `alaw` (G.711 8 kHz)** and **RFC 4733 / RFC 2833 RTP DTMF** works out of the box with `py-phone-caller` (including DTMF `4` acknowledgment and RFC 3428 SIP `MESSAGE` text alerts where supported by the handset):

- **Zero-Hardware Software Clients**: **Linphone** (Desktop & iOS/Android — supports both voice + instant RFC 3428 SIP `MESSAGE` chat), **MicroSIP** (Windows), **Baresip** (Linux CLI/headless testing).
- **PoE NOC Desk Phones**: **Yealink SIP-T33G / T43U**, **Grandstream GRP2602P / GRP2613**, **Snom D717**.
- **Cordless Roaming On-Site Handsets (Factories, Hospitals, Warehouses)**:
    - **DECT IP Base + Handsets**: **Yealink W70B + W73H / W59R (IP67 ruggedized)**
    - **Wi-Fi SIP Handsets**: **Grandstream WP810 / WP825 (ruggedized)** — pairs cleanly with on-site Wi-Fi + local Asterisk extension `1000` in 100% air-gapped facilities without cellular coverage!
