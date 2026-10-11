"""
Exception hierarchy for the caller_sms service.
"""

from __future__ import annotations


class CallerSmsError(Exception):
    """Base exception for all caller_sms errors."""


class MissingSmsParameterError(CallerSmsError):
    """Raised when required parameters ('phone' or 'message') are missing."""


class UnsupportedCarrierError(CallerSmsError):
    """Raised when an unknown or unsupported SMS carrier is requested."""


class SmsDeliveryError(CallerSmsError):
    """Raised when SMS carrier dispatch fails."""


class InboundSmsParseError(CallerSmsError):
    """Raised when an inbound SMS webhook payload cannot be parsed."""
