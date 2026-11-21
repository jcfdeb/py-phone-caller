# py-phone-caller

Automated phone call and SMS alerting platform for Asterisk-based environments.

## Installation

```bash
# Install core utilities and unified CLI
pip install py-phone-caller

# Install all microservices, TTS audio engine, and Web UI
pip install "py-phone-caller[all]"
```

## CLI Usage

```bash
# Display version
py-phone-caller --version

# List available microservices and their entrypoints
py-phone-caller list-services

# Launch a specific microservice
py-phone-caller run asterisk-caller
```
