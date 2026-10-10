//! # Autonomous Hardware Watchdog & Kernel Supervisors
//!
//! Provides system supervisors for hardware resilience, including autonomous
//! USB port resetting (`UsbPortSupervisor`) to recover hung USB serial bridges and modems.

pub mod usb;

pub use usb::UsbPortSupervisor;
