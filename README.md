# py-phone-caller

## Introduction

py-phone-caller is an automated phone calling and SMS notification system built with Python. It integrates with Asterisk PBX to make automated phone calls, deliver voice messages, and send SMS notifications. The system can be triggered manually, scheduled for future execution, or automatically triggered by Prometheus alerts.

The project provides a modular architecture with components for call initiation, audio generation, call tracking, SMS sending, and a web-based user interface. It supports multiple text-to-speech engines and can be configured to retry failed calls.

**Current Status**: Works fine, but a few things need to be improved or implemented. The project isn't ready to be used without a deep knowledge of Asterisk, Linux, etc. It is ready to be used in production, but the set of updated Ansible playbooks _(to install the components)_ is work in progres _(also runs on containers, Kubernetes...)_. Have patience, maybe in a near future it will be more _usable/installable_.

## Components

### asterisk_caller

This component is responsible for initiating and managing phone calls through Asterisk. It provides a web API for placing calls and playing audio messages. The component handles the communication with Asterisk's REST Interface (ARI) to initiate calls, control call flow, and play audio messages to the caller.

Key features:
- Initiates outbound calls through Asterisk
- Manages call queues
- Plays audio messages during calls
- Provides HTTP endpoints for call control

### asterisk_recaller

This component handles retrying failed phone calls. It periodically checks the database for calls that need to be retried and initiates recall attempts based on configured parameters. The component uses a strategy of waiting a certain amount of time between retry attempts and has a maximum number of retry attempts.

Key features:
- Monitors for failed or unanswered calls
- Implements configurable retry logic
- Spaces retry attempts over time
- Tracks retry attempts in the database

### asterisk_ws_monitor

This component monitors Asterisk events through a WebSocket connection. It handles various events from Asterisk, such as call initiation, and performs actions like generating audio files and playing them to the channel. It also logs events to a database and coordinates with other components like call_register.

Key features:
- Connects to Asterisk via WebSockets
- Monitors call events in real-time
- Triggers audio generation and playback
- Logs call events to the database

### caller_prometheus_webhook

This component serves as a webhook endpoint for Prometheus alerts. It receives alert notifications from Prometheus AlertManager and can trigger different types of notifications: phone calls only, SMS only, SMS before call, or both call and SMS simultaneously. It uses a queue-based approach with producer-consumer pattern to process alerts.

Key features:
- Receives webhook notifications from Prometheus AlertManager
- Supports multiple notification strategies
- Processes alerts asynchronously using queues
- Integrates monitoring systems with phone/SMS notifications

### caller_register

This component manages the registration and tracking of calls in the system. It handles database operations for call records, including creating new call attempts, updating call statuses (acknowledged, heard), and managing voice messages. It also supports scheduled calls.

Key features:
- Maintains a registry of all calls in the system
- Tracks call statuses and outcomes
- Manages voice message associations
- Provides API for call registration and status updates

### caller_scheduler

This component provides functionality for scheduling calls to be made at a specific time in the future. It exposes a web API endpoint that accepts parameters for the phone number, message, and scheduled time. The component converts the local time to UTC and uses Celery to schedule the call task.

Key features:
- Schedules calls for future execution
- Handles time zone conversions
- Uses Celery for reliable task scheduling
- Provides API for scheduling calls

### caller_sms

This component provides functionality for sending SMS messages. It exposes a web API endpoint that accepts parameters for the message content and recipient phone number. The component uses Twilio as the SMS provider and sends messages asynchronously using a thread pool executor.

Key features:
- Sends SMS notifications via Twilio
- Processes SMS requests asynchronously
- Provides API for sending SMS messages
- Can be used independently or with call notifications

### generate_audio

This component is responsible for converting text messages to speech audio files. It supports multiple text-to-speech (TTS) engines including Google TTS, AWS Polly, Facebook MMS, and Piper TTS. The component exposes web API endpoints for creating audio files from text messages and checking if audio files are ready.

Key features:
- Converts text to speech using multiple TTS engines
- Supports multiple languages and voices
- Manages audio file storage and retrieval
- Provides API for audio generation and status checking

### py-phone-caller-ui

This component provides a web-based user interface for the py-phone-caller system. It's built using Flask and includes several sections: login, home, calls, schedule_call, users, and ws_events. The component handles user authentication using Flask-Login and ensures that an admin user exists in the system.

Key features:
- Web-based interface for system management
- User authentication and authorization
- Call history and management
- Call scheduling interface

### py_phone_caller_utils

This is a collection of utility modules used by other components in the system:

#### checksums

Provides functions for generating various types of checksums used in the system:
- Checksums for calls based on phone number and message
- Checksums for messages based on content
- Unique checksums for call attempts

#### login

Handles user authentication for the web UI:
- User class implementation for Flask-Login
- User authentication status tracking

#### py_phone_caller_db

Handles database operations for various components of the system:
- Database access for call registration
- Database access for WebSocket monitoring
- Database access for call scheduling
- Database access for user management
- Uses Piccolo ORM for database access

#### py_phone_caller_voices

Provides interfaces to various text-to-speech (TTS) engines:
- AWS Polly integration
- Facebook MMS integration
- Google TTS integration
- Piper TTS integration

#### sms

Provides functionality for sending SMS messages:
- Twilio SMS integration

#### tasks

Handles asynchronous task processing for the system:
- Celery task definitions
- Task posting to caller_register
- Task posting to caller_scheduler

## More Information

If you want to know how it's organized please read the current [version documentation](https://github.com/jcfdeb/py-phone-caller/blob/main/doc/py-phone-caller_2025.05.md) 

For more details about the project setup and installation, you can refer to [this -OLD- documentation](https://github.com/jcfdeb/py-phone-caller/blob/main/doc/fedora34-server-with-podman_though-ansible.md).

A Web Interface for the 'py-phone-caller' was added and works fine, but several things need to be improved or implemented.

## Good Advice

* The project isn't ready to be used without a deep knowledge of Asterisk, Linux, etc.
* It is not ready to be used in production
* Have patience, maybe in a near future it will be more _usable_
