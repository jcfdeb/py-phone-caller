# py-phone-caller Documentation (2025 Architecture Archive)

> [!TIP]
> **Looking for the modern 1.0.0 Architecture & API reference?**
> - For current end-to-end call flows, state machines, and sequence diagrams: see **[Architecture & Call Flows Guide](architecture-and-call-flows.md)**.
> - For full REST API endpoint specifications: see **[Services and Endpoints Reference](services-and-endpoints.md)**.
> - For deployment instructions: see **[Operator Installation Guide (A to Z)](OPERATOR_INSTALLATION_GUIDE.md)**.
>
> *This document is preserved for historical reference.*

## Table of Contents
1. [Introduction](#introduction)
2. [System Architecture](#system-architecture)
3. [Components](#components)
   - [asterisk_caller](#asterisk_caller)
   - [asterisk_recallerer](#asterisk_recallerer)
   - [asterisk_ws_monitor](#asterisk_ws_monitor)
   - [caller_address_book](#caller_address_book)
   - [caller_prometheus_webhook](#caller_prometheus_webhook)
   - [caller_register](#caller_register)
   - [caller_scheduler](#caller_scheduler)
   - [caller_sms](#caller_sms)
   - [generate_audio](#generate_audio)
   - [py_phone_caller_ui](#py_phone_caller_ui)
   - [py_phone_caller_utils](#py_phone_caller_utils)
4. [Configuration](#configuration)
5. [Call Flows](#call-flows)
6. [SMS Flows](#sms-flows)
7. [Prometheus Alert Flows](#prometheus-alert-flows)

## Introduction

py-phone-caller is an automated phone calling and SMS notification system built with Python. It integrates with Asterisk PBX to make automated phone calls, deliver voice messages, and send SMS notifications. The system can be triggered manually, scheduled for future execution, or automatically triggered by Prometheus alerts.

The project provides a modular architecture with components for call initiation, audio generation, call tracking, SMS sending, and a web-based user interface. It supports multiple text-to-speech engines and can be configured to retry failed calls.

## System Architecture

The py-phone-caller system consists of several interconnected components that work together to provide automated phone calling and SMS notification capabilities. The following diagram illustrates the high-level architecture of the system:

```mermaid
graph TD
    UI[py_phone_caller_ui] --> CS[caller_scheduler]
    UI --> CAB[caller_address_book]
    AC[asterisk_caller] -.logs.-> UI
    WSM[asterisk_ws_monitor] -.logs.-> UI

    PW[caller_prometheus_webhook] --> AC
    PW --> SMS[caller_sms]

    CR[caller_register] --> AC
    CS --> CR

    AC --> GA[generate_audio]
    AC --> WSM
    AC --> CAB

    WSM --> GA
    WSM --> CR

    AR[asterisk_recallerer] --> AC

    subgraph Database
        DB[(PostgreSQL)]
    end

    CR --> DB
    WSM --> DB
    AR --> DB
    CAB --> DB

    subgraph Queue
        RQ[(Redis)]
    end

    CS --> RQ

    subgraph Utils
        PCU[py_phone_caller_utils]
    end

    AC --> PCU
    AR --> PCU
    WSM --> PCU
    PW --> PCU
    CR --> PCU
    CS --> PCU
    SMS --> PCU
    GA --> PCU
    UI --> PCU
    CAB --> PCU
```

## Components

### asterisk_caller

#### Overview
The asterisk_caller component is responsible for initiating and managing phone calls through Asterisk. It provides a web API for placing calls and playing audio messages. The component handles the communication with Asterisk's REST Interface (ARI) to initiate calls, control call flow, and play audio messages to the caller.

#### Key Features
- Initiates outbound calls through Asterisk
- Manages call queues
- Plays audio messages during calls
- Provides HTTP endpoints for call control

#### Main Functions
- `manage_call_queue()`: Manages the call queue
- `initiate_asterisk_call()`: Initiates calls through Asterisk
- `place_call()`: HTTP endpoint for placing calls
- `asterisk_play()`: HTTP endpoint for playing audio messages
- `init_app()`: Initializes the application

#### Component Interactions

The following sequence diagram illustrates how `asterisk_caller` interacts with the PBX and other microservices to initiate a call and manage its early lifecycle:

```mermaid
sequenceDiagram
    participant Client
    participant AC as asterisk_caller
    participant Asterisk
    participant WSM as asterisk_ws_monitor
    participant GA as generate_audio

    Client->>AC: POST /place_call
    AC->>Asterisk: Initiate call
    Asterisk-->>AC: Call initiated
    AC->>WSM: Call initiated (via Asterisk events)
    WSM->>GA: Request audio generation
    GA-->>WSM: Audio file ready
    WSM->>Asterisk: Play audio
    Asterisk-->>WSM: Audio played
    WSM->>CR: Update call status
    WSM-->>AC: Call status updated
    AC-->>Client: Call status

    Note right of WSM: asterisk_ws_monitor is always needed when placing calls
```

### caller_address_book

#### Overview
The caller_address_book component manages a data source for contacts and their on-call availability. It allows the system to resolve the reserved word "oncall" to a real phone number based on prioritized on-call rotations. It provides a REST API for managing contacts and querying the current on-call responder.

#### Key Features
- Centralized contact management
- Prioritized on-call availability windows
- Support for multiple on-call periods per contact
- CSV Import/Export functionality
- Integration with `asterisk_caller` for automatic responder routing

#### Main Functions
- `get_contact_on_call()`: Retrieves the phone number of the currently active on-call contact
- `post_contact_add()`: Adds a new contact to the address book
- `post_contacts_import_csv()`: Bulk imports contacts from CSV
- `get_contacts_export_csv()`: Exports all contacts to CSV

#### Component Interactions

The `caller_address_book` service acts as a centralized data provider for contact resolution, as shown in the diagram below:

```mermaid
sequenceDiagram
    participant UI as py_phone_caller_ui
    participant CAB as caller_address_book
    participant DB as Database
    participant AC as asterisk_caller

    UI->>CAB: Manage contacts (Add/Edit/Delete)
    CAB->>DB: Persist contact data
    
    AC->>CAB: GET /contact_on_call
    CAB->>DB: Query active responder
    DB-->>CAB: Responder data
    CAB-->>AC: Phone number
```

### asterisk_recallerer

#### Overview
The asterisk_recallerer component handles retrying failed phone calls. It periodically checks the database for calls that need to be retried and initiates recall attempts based on configured parameters. The component uses a strategy of waiting a certain amount of time between retry attempts and has a maximum number of retry attempts.

#### Key Features
- Monitors for failed or unanswered calls
- Implements configurable retry logic
- Spaces retry attempts over time
- Tracks retry attempts in the database

#### Main Functions
- `asterisk_recaller()`: Periodically checks for calls that need to be retried
- `recall_post()`: Sends a POST request to the Asterisk call service to initiate a recall

#### Component Interactions

The `asterisk_recallerer` continuously monitors the database for calls that require attention, following the retry cycle illustrated here:

```mermaid
sequenceDiagram
    participant AR as asterisk_recallerer
    participant DB as Database
    participant AC as asterisk_caller

    loop Every SLEEP_BEFORE_QUERYING seconds
        AR->>DB: Query for calls to retry
        DB-->>AR: Return eligible calls

        loop For each call to retry
            AR->>AC: Initiate recall
            AC-->>AR: Recall initiated
            AR->>AR: Wait sleep_and_retry seconds
        end
    end
```

### asterisk_ws_monitor

#### Overview
The asterisk_ws_monitor component monitors Asterisk events through a WebSocket connection. It handles various events from Asterisk, such as call initiation, and performs actions like generating audio files and playing them to the channel. It also logs events to a database and coordinates with other components like call_register.

#### Key Features
- Connects to Asterisk via WebSockets
- Monitors call events in real-time
- Triggers audio generation and playback
- Logs call events to the database

#### Main Functions
- `asterisk_ws_client()`: Establishes a WebSocket connection to Asterisk
- `generate_the_audio_file()`: Generates audio files for messages
- `play_audio_to_channel()`: Plays audio to an Asterisk channel
- `take_control_of_dialplan()`: Takes control of the Asterisk dialplan
- `querying_call_register()`: Queries the call register for call information

#### Component Interactions

This component is the primary event listener for Asterisk, coordinating multiple services in response to real-time events:

```mermaid
sequenceDiagram
    participant Asterisk
    participant WSM as asterisk_ws_monitor
    participant GA as generate_audio
    participant CR as caller_register

    Asterisk->>WSM: WebSocket event
    WSM->>CR: Query call information
    CR-->>WSM: Call information
    WSM->>GA: Generate audio
    GA-->>WSM: Audio file ready
    WSM->>Asterisk: Play audio
    WSM->>CR: Update call status
```

### caller_prometheus_webhook

#### Overview
The caller_prometheus_webhook component serves as a webhook endpoint for Prometheus alerts. It receives alert notifications from Prometheus AlertManager and can trigger different types of notifications: phone calls only, SMS only, SMS before call, or both call and SMS simultaneously. It uses a queue-based approach with producer-consumer pattern to process alerts.

#### Key Features
- Receives webhook notifications from Prometheus AlertManager
- Supports multiple notification strategies
- Processes alerts asynchronously using queues
- Integrates monitoring systems with phone/SMS notifications

#### Main Functions
- `do_call_only()`: Handles call-only notifications
- `send_the_sms()`: Sends SMS notifications
- `do_sms_before_call()`: Handles SMS-before-call notifications
- `do_call_and_sms()`: Handles simultaneous call and SMS notifications
- `process_the_queue()`: Processes the alert queue
- `data_from_alert_manager()`: Processes data from Prometheus AlertManager
- `init_app()`: Initializes the application with HTTP endpoints for different notification types

#### Component Interactions

The webhook component supports several notification strategies, as detailed in the following decision flow:

```mermaid
sequenceDiagram
    participant Prometheus
    participant PW as caller_prometheus_webhook
    participant AC as asterisk_caller
    participant WSM as asterisk_ws_monitor
    participant SMS as caller_sms

    Prometheus->>PW: Alert notification

    alt Call only
        PW->>AC: Initiate call
        AC->>WSM: Call initiated (via Asterisk events)
        Note right of WSM: asterisk_ws_monitor is always needed when placing calls
    else SMS only
        PW->>SMS: Send SMS
    else SMS before call
        PW->>SMS: Send SMS
        PW->>PW: Wait configured time
        PW->>AC: Initiate call
        AC->>WSM: Call initiated (via Asterisk events)
        Note right of WSM: asterisk_ws_monitor is always needed when placing calls
    else Call and SMS
        PW->>AC: Initiate call
        AC->>WSM: Call initiated (via Asterisk events)
        PW->>SMS: Send SMS
        Note right of WSM: asterisk_ws_monitor is always needed when placing calls
    end
```

### caller_register

#### Overview
The caller_register component manages the registration and tracking of calls in the system. It handles database operations for call records, including creating new call attempts, updating call statuses (acknowledged, heard), and managing voice messages. It also supports scheduled calls.

#### Key Features
- Maintains a registry of all calls in the system
- Tracks call statuses and outcomes
- Manages voice message associations
- Provides API for call registration and status updates

#### Main Functions
- `init_database()`: Initializes the database connection and runs migrations
- `register_call()`: Registers a new call in the system
- `acknowledge()`: Updates the acknowledgement status of a call
- `heard()`: Updates the heard status of a call
- `voice_message()`: Manages voice messages
- `scheduled_call()`: Handles scheduled calls
- `init_app()`: Initializes the application with HTTP endpoints

#### Component Interactions

The following diagram illustrates how the `caller_register` service manages the persistence and retrieval of call records for external clients:

```mermaid
sequenceDiagram
    participant Client
    participant CR as caller_register
    participant DB as Database

    Client->>CR: Register call
    CR->>DB: Create call record
    DB-->>CR: Call record created
    CR-->>Client: Call registered

    Client->>CR: Update call status
    CR->>DB: Update call record
    DB-->>CR: Call record updated
    CR-->>Client: Status updated
```

### caller_scheduler

#### Overview
The caller_scheduler component provides functionality for scheduling calls to be made at a specific time in the future. It exposes a web API endpoint that accepts parameters for the phone number, message, and scheduled time. The component converts the local time to UTC and uses Celery to schedule the call task.

#### Key Features
- Schedules calls for future execution
- Handles time zone conversions
- Uses Celery for reliable task scheduling
- Provides API for scheduling calls

#### Main Functions
- `schedule_this_call()`: Handles incoming requests to schedule a call at a specified time
- `init_app()`: Initializes and configures the aiohttp web application for scheduling calls

#### Component Interactions

The scheduler leverages Celery for asynchronous execution, as shown in the lifecycle diagram below:

```mermaid
sequenceDiagram
    participant Client
    participant CS as caller_scheduler
    participant Celery
    participant CR as caller_register

    Client->>CS: Schedule call
    CS->>CS: Convert time to UTC
    CS->>Celery: Schedule task
    Celery-->>CS: Task scheduled
    CS-->>Client: Call scheduled

    Note over Celery,CR: At scheduled time
    Celery->>CR: Execute scheduled call
```

### caller_sms

#### Overview
The caller_sms component provides functionality for sending SMS messages. It exposes a web API endpoint that accepts parameters for the message content and recipient phone number. The component uses Twilio as the SMS provider and sends messages asynchronously using a thread pool executor.

#### Key Features
- Sends SMS notifications via Twilio
- Processes SMS requests asynchronously
- Provides API for sending SMS messages
- Can be used independently or with call notifications

#### Main Functions
- `sms_sender_async()`: Sends an SMS message asynchronously using a thread pool executor
- `send_the_sms()`: Handles incoming requests to send an SMS message to a specified phone number
- `init_app()`: Initializes and configures the aiohttp web application for sending SMS messages

#### Component Interactions

The following diagram shows the asynchronous SMS delivery process through the Twilio gateway:

```mermaid
sequenceDiagram
    participant Client
    participant SMS as caller_sms
    participant Twilio

    Client->>SMS: Send SMS
    SMS->>SMS: Create thread pool
    SMS->>Twilio: Send SMS request
    Twilio-->>SMS: SMS sent
    SMS-->>Client: SMS status
```

### generate_audio

#### Overview
The generate_audio component is responsible for converting text messages to speech audio files. It supports multiple text-to-speech (TTS) engines including Google TTS, AWS Polly, Facebook MMS, and Piper TTS. The component is highly optimized for containerized environments and ensures offline readiness by managing its own models.

#### Key Features
- Converts text to speech using multiple TTS engines
- Supports multiple languages and voices
- **Offline Readiness**: Automatically downloads and bakes in configured TTS models (Facebook MMS / Piper) at build time or startup.
- **Optimized for CPU**: Uses CPU-only versions of PyTorch and Transformers to significantly reduce image size (from 15GB to ~3.2GB).
- **Multi-stage Build**: Efficient containerization using multi-stage Docker builds on `rockylinux:9-minimal`.
- Manages audio file storage and retrieval
- Provides API for audio generation and status checking

#### Main Functions
- `generate_tts_audio()`: Generates audio files using the selected TTS engine
- `text_to_speech_piper_tts()`: Implements the Piper TTS engine
- `ensure_models_present()`: Asynchronous function that checks for and downloads missing TTS models at startup.
- `is_audio_ready()`: HTTP endpoint to check if an audio file is ready
- `create_audio()`: HTTP endpoint to create an audio file from a text message
- `init_app()`: Initializes the application with HTTP endpoints

#### Component Interactions

This service handles both audio generation and readiness checks, supporting a variety of TTS engines:

```mermaid
sequenceDiagram
    participant Client
    participant GA as generate_audio
    participant TTS as TTS Engine

    Client->>GA: Create audio
    GA->>TTS: Convert text to speech
    TTS-->>GA: Audio data
    GA->>GA: Save audio file
    GA-->>Client: Audio creation status

    Client->>GA: Check if audio ready
    GA->>GA: Check file existence
    GA-->>Client: Audio ready status
```

### py_phone_caller_ui

#### Overview
The py_phone_caller_ui component provides a web-based user interface for the py-phone-caller system. It's built using Flask and includes several sections: login, home, calls, schedule_call, users, address_book, and ws_events. The component handles user authentication using Flask-Login and ensures that an admin user exists in the system.

#### Key Features
- Web-based interface for system management
- User authentication and authorization
- Visual feedback for login failures (Bootstrap alerts)
- Call history and management
- Call scheduling interface
- Integrated Address Book and On-Call rotation management
- Real-time event log viewing

#### Main Functions
- Flask application setup with blueprints for different sections (login, home, calls, schedule_call, users, address_book, ws_events)
- `load_user()`: Loads a user for Flask-Login based on the provided user ID
- `setup_admin_user()`: Ensures that an admin user exists and resets the admin password if required (controlled by `UI_USER_RESET_PASSWORD`)

#### Component Interactions

The UI interacts with several backend services to provide log viewing and call scheduling functionality:

```mermaid
sequenceDiagram
    participant User
    participant UI as py_phone_caller_ui
    participant CS as caller_scheduler
    participant AC as asterisk_caller
    participant WSM as asterisk_ws_monitor

    User->>UI: Login
    UI-->>User: Authentication status

    User->>UI: View logs
    UI->>AC: Query logs
    AC-->>UI: Log data
    UI->>WSM: Query logs
    WSM-->>UI: Log data
    UI-->>User: Log information

    User->>UI: Schedule call
    UI->>CS: Schedule call
    CS-->>UI: Call scheduled
    UI-->>User: Scheduling confirmation
```

### py_phone_caller_utils

#### Overview
The py_phone_caller_utils package is a collection of shared utility modules. In the Release Candidate, it has been transformed into a standard Python package that can be installed into `site-packages`, improving architectural robustness and removing reliance on `PYTHONPATH` hacks for common code.

#### Key Features
- Centralized configuration management via DynaConf
- Database schema management and migrations using Piccolo ORM
- Specialized Text-to-Speech interfaces (Piper, Facebook MMS, AWS Polly, gTTS)
- SMS sending utilities (Twilio)
- Asynchronous Celery task definitions
- Shared user model and authentication logic
- Automatic TTS model management utilities

#### Subpackages and Modules
- **config.py**: Dynamic configuration loader with environment override support.
- **checksums**: Standardized hash generation for messages and calls.
- **login**: Flask-Login user model and session management.
- **py_phone_caller_db**: Piccolo ORM tables, configuration, and migrations.
- **py_phone_caller_voices**: Core TTS engine implementations and model downloaders.
- **sms**: Twilio SMS client wrapper.
- **tasks**: Celery task definitions for background execution.

#### Component Interactions

The utility package provides shared logic and models across the entire ecosystem, as shown in the following architectural overview:

```mermaid
graph TD
    AC[asterisk_caller] --> PCU[py_phone_caller_utils]
    AR[asterisk_recallerer] --> PCU
    WSM[asterisk_ws_monitor] --> PCU
    PW[caller_prometheus_webhook] --> PCU
    CR[caller_register] --> PCU
    CS[caller_scheduler] --> PCU
    SMS[caller_sms] --> PCU
    GA[generate_audio] --> PCU
    UI[py_phone_caller_ui] --> PCU

    subgraph py_phone_caller_utils
        CFG[config]
        CHK[checksums]
        LGN[login]
        DB[py_phone_caller_db]
        VOI[py_phone_caller_voices]
        SMS_U[sms]
        TSK[tasks]
    end
```

## Configuration

The py-phone-caller system is configured using DynaConf, which loads settings from `settings.toml` and sensitive information from `.secrets.toml`. By default, these files are expected in `src/config/`, but the configuration directory can be explicitly set using the `CALLER_CONFIG_DIR` environment variable. This allows for flexible configuration management, including environment variable overrides. In the Release Candidate, all port settings are strictly typed as integers to ensure reliability.

The configuration is organized into sections:

- **[commons]**: Common settings like Asterisk credentials
- **[asterisk_call]**: Settings for the asterisk_caller component
- **[call_register]**: Settings for the caller_register component
- **[asterisk_ws_monitor]**: Settings for the asterisk_ws_monitor component
- **[asterisk_recaller]**: Settings for the asterisk_recallerer component
- **[generate_audio]**: Settings for the generate_audio component (TTS engine, language codes, model paths)
- **[caller_prometheus_webhook]**: Settings for the caller_prometheus_webhook component
- **[caller_sms]**: Settings for the caller_sms component
- **[scheduled_calls]**: Settings for the caller_scheduler component
- **[caller_address_book]**: Settings for the caller_address_book component
- **[queue]**: Settings for the message queue (Redis URL and scheme)
- **[database]**: Database connection settings (PostgreSQL)
- **[py_phone_caller_ui]**: Settings for the web UI (Admin user, session protection)
- **[logs]**: Logging configuration (Formatter, Level, and specialized error messages)

Configuration settings can be accessed in code by importing `settings` from the `py_phone_caller_utils.config` module.

### Environment Variables

The system relies on several environment variables for setup, operation, and diagnostics:

#### Mandatory / Core
- **`CALLER_CONFIG_DIR`**: Path to the directory containing `settings.toml` and `.secrets.toml`.
- **`PICCOLO_CONF`**: The module path for Piccolo ORM configuration (e.g., `py_phone_caller_utils.py_phone_caller_db.piccolo_conf`).
- **`PYTHONPATH`**: Should include the `src` directory.
- **`UI_USER_RESET_PASSWORD`**: Set to `true` to trigger an admin password reset on UI startup (password is printed to logs).

#### Docker / Optimization
- **`PYTHONWARNINGS=ignore::SyntaxWarning`**: Suppresses noisy Python 3.12 syntax warnings from third-party libraries like `pydub`.
- **`NNPACK_VERBOSE=0`**: Suppresses hardware-related initialization warnings from the `generate_audio` component.
- **`TORCH_CPP_LOG_LEVEL=ERROR`**: Minimizes PyTorch internal logging.
- **`PYTHONUNBUFFERED=1`**: Ensures real-time log output in containerized environments.

#### Deployment
- **`DYNACONF_...`**: Any configuration setting can be overridden using the `DYNACONF_` prefix followed by the section and key in uppercase (e.g., `DYNACONF_DATABASE__DB_HOST=db`).

## Call Flows

The py-phone-caller system supports several call flows, depending on how the call is initiated. **Note that the asterisk_ws_monitor package is always needed when placing calls**, as it handles the real-time monitoring of call events and coordinates audio playback. The following diagrams illustrate the main call flows:

### Manual / Scheduled Call Flow

This flow covers call initiation from the Web UI, including immediately or at a specific future date:

```mermaid
sequenceDiagram
    participant User
    participant UI as py_phone_caller_ui
    participant CS as caller_scheduler
    participant Celery
    participant AC as asterisk_caller
    participant CAB as caller_address_book
    participant CR as caller_register
    participant WSM as asterisk_ws_monitor
    participant GA as generate_audio
    participant Asterisk

    User->>UI: Schedule call (Now or Future)
    UI->>CS: POST /schedule_call
    UI->>CR: POST /scheduled_call (Record)
    CS->>Celery: Enqueue task
    
    Note over Celery,AC: At execution time
    Celery->>AC: POST /place_call
    AC->>CAB: Resolve "oncall" (if needed)
    AC->>Asterisk: ARI: Create Channel
    AC->>CR: POST /register_call (Attempt)
    
    Asterisk->>WSM: WebSocket: StasisStart
    WSM->>CR: POST /msg (Get message info)
    CR-->>WSM: Message data
    WSM->>GA: POST /make_audio
    GA-->>WSM: Audio ready
    WSM->>Asterisk: ARI: Play audio
    Asterisk->>User: Voice message delivered
    
    User->>Asterisk: DTMF / Hangup (optional)
    Asterisk->>WSM: WebSocket: DTMF/StasisEnd
    WSM->>CR: POST /ack or /heard
```

### Prometheus Alert Call Flow

When an alert is received from Prometheus, the system automatically triggers the following automated calling sequence:

```mermaid
sequenceDiagram
    participant Prometheus
    participant PW as caller_prometheus_webhook
    participant AC as asterisk_caller
    participant CAB as caller_address_book
    participant CR as caller_register
    participant WSM as asterisk_ws_monitor
    participant GA as generate_audio
    participant Asterisk
    participant User

    Prometheus->>PW: Alert notification (Webhook)
    PW->>AC: Initiate call
    AC->>CAB: Resolve "oncall" (if needed)
    AC->>Asterisk: ARI: Create Channel
    AC->>CR: POST /register_call (Attempt)
    
    Asterisk->>WSM: WebSocket: StasisStart
    WSM->>CR: POST /msg
    CR-->>WSM: Message data
    WSM->>GA: POST /make_audio
    GA-->>WSM: Audio ready
    WSM->>Asterisk: ARI: Play audio
    Asterisk->>User: Voice message delivered
```

### Failed Call Retry Flow

The system ensures alert delivery through a robust retry mechanism, which follows the logic shown in the diagram below:

```mermaid
sequenceDiagram
    participant AR as asterisk_recallerer
    participant DB as Database
    participant AC as asterisk_caller
    participant CAB as caller_address_book
    participant CR as caller_register
    participant WSM as asterisk_ws_monitor
    participant Asterisk
    participant User

    AR->>DB: Query for calls to retry
    DB-->>AR: Return eligible calls
    AR->>AC: POST /place_call
    AC->>CAB: Resolve "oncall" (if needed)
    AC->>Asterisk: ARI: Create Channel
    AC->>CR: POST /register_call (Attempt)
    
    Asterisk->>WSM: WebSocket events
    WSM->>Asterisk: Handle call flow
    Asterisk->>User: Call delivered
    WSM->>CR: Update status
```

## SMS Flows

The py-phone-caller system supports sending SMS messages independently or in conjunction with phone calls. The following diagrams illustrate the main SMS flows:

### Manual SMS Flow

SMS notifications can be sent directly via the API, as illustrated in the following sequence:

```mermaid
sequenceDiagram
    participant User
    participant Client
    participant SMS as caller_sms
    participant Twilio

    User->>Client: Send SMS
    Client->>SMS: Send SMS
    SMS->>Twilio: Send SMS request
    Twilio->>User: SMS delivered
    Twilio-->>SMS: SMS sent
    SMS-->>Client: SMS status
    Client-->>User: SMS status

    Note right of Client: py_phone_caller_ui does not directly interact with caller_sms
```

### Prometheus Alert SMS Flow

This flow shows how Prometheus alerts are bridged to the Twilio gateway for SMS delivery:

```mermaid
sequenceDiagram
    participant Prometheus
    participant PW as caller_prometheus_webhook
    participant SMS as caller_sms
    participant Twilio
    participant User

    Prometheus->>PW: Alert notification
    PW->>SMS: Send SMS
    SMS->>Twilio: Send SMS request
    Twilio->>User: SMS delivered
    Twilio-->>SMS: SMS sent
    SMS-->>PW: SMS status
```

## Prometheus Alert Flows

The py-phone-caller system can be triggered by Prometheus alerts through the caller_prometheus_webhook component. The following diagrams illustrate the different alert notification strategies:

### Call Only Alert Flow

When configured for voice-only alerts, the system executes the following interaction with the PBX:

```mermaid
sequenceDiagram
    participant Prometheus
    participant PW as caller_prometheus_webhook
    participant AC as asterisk_caller
    participant CAB as caller_address_book
    participant CR as caller_register
    participant WSM as asterisk_ws_monitor
    participant Asterisk
    participant User

    Prometheus->>PW: Alert notification
    PW->>AC: Initiate call
    AC->>CAB: Resolve "oncall" (if needed)
    AC->>Asterisk: ARI: Create Channel
    AC->>CR: POST /register_call
    Asterisk->>WSM: WebSocket: StasisStart
    WSM->>Asterisk: Handle call flow
    Asterisk->>User: Call delivered
```

### SMS Only Alert Flow

For low-priority or out-of-band alerts, the system can be configured to send only an SMS message:

```mermaid
sequenceDiagram
    participant Prometheus
    participant PW as caller_prometheus_webhook
    participant SMS as caller_sms
    participant User

    Prometheus->>PW: Alert notification
    PW->>SMS: Send SMS
    SMS->>User: SMS delivered
```

### SMS Before Call Alert Flow

This multi-step flow attempts to notify the responder via SMS first, followed by a phone call if no action is taken within the configured grace period:

```mermaid
sequenceDiagram
    participant Prometheus
    participant PW as caller_prometheus_webhook
    participant SMS as caller_sms
    participant AC as asterisk_caller
    participant CAB as caller_address_book
    participant CR as caller_register
    participant WSM as asterisk_ws_monitor
    participant Asterisk
    participant User

    Prometheus->>PW: Alert notification
    PW->>SMS: Send SMS
    SMS->>User: SMS delivered
    PW->>PW: Wait configured time
    PW->>AC: Initiate call
    AC->>CAB: Resolve "oncall" (if needed)
    AC->>Asterisk: ARI: Create Channel
    AC->>CR: POST /register_call
    Asterisk->>WSM: WebSocket events
    WSM->>Asterisk: Handle call flow
    Asterisk->>User: Call delivered
```

### Call and SMS Alert Flow

The most comprehensive alert strategy initiates both a phone call and an SMS message in parallel, ensuring maximum visibility:

```mermaid
sequenceDiagram
    participant Prometheus
    participant PW as caller_prometheus_webhook
    participant AC as asterisk_caller
    participant SMS as caller_sms
    participant CAB as caller_address_book
    participant CR as caller_register
    participant WSM as asterisk_ws_monitor
    participant Asterisk
    participant User

    Prometheus->>PW: Alert notification
    par Initiate Call
        PW->>AC: Initiate call
        AC->>CAB: Resolve "oncall" (if needed)
        AC->>Asterisk: ARI: Create Channel
        AC->>CR: POST /register_call
        Asterisk->>WSM: WebSocket events
        WSM->>Asterisk: Handle call flow
        Asterisk->>User: Call delivered
    and Send SMS
        PW->>SMS: Send SMS
        SMS->>User: SMS delivered
    end
```
