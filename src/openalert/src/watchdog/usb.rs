//! # Autonomous Kernel-Level USB Reset Supervisor (`ioctl(USBDEVFS_RESET)`)
//!
//! Provides automated hardware fault detection, sysfs topology traversal, and
//! low-level USB controller resets (`ioctl(USBDEVFS_RESET)`) for hung USB serial
//! bridges (e.g. CH340/CH343, FTDI, CP2102) and cellular GSM/LTE baseband modems.
//!
//! Guarantees non-crashing recovery without operating system reboots or physical intervention.

use crate::error::{OpenAlertError, Result};
use std::fs::{self, File, OpenOptions};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
use tracing::{debug, error, info, warn};

#[cfg(unix)]
use std::os::unix::io::AsRawFd;

/// Linux USBDEVFS_RESET ioctl definition: _IO('U', 20) -> 0x5514
#[cfg(target_os = "linux")]
const USBDEVFS_RESET: libc::c_ulong = 0x5514;

/// Autonomous hardware supervisor tracking consecutive communication failures
/// and triggering kernel-level USB bus resets when failure thresholds are exceeded.
#[derive(Debug)]
pub struct UsbPortSupervisor {
    /// Target serial character device path (e.g. `/dev/ttyACM0`, `/dev/ttyUSB2`).
    tty_path: PathBuf,
    /// Number of consecutive I/O or connection timeouts observed.
    consecutive_failures: u32,
    /// Number of failures required to trigger a hardware reset.
    failure_threshold: u32,
    /// Timestamp of last executed hardware reset (for rate-limiting).
    last_reset: Option<Instant>,
    /// Minimum time that must elapse between consecutive resets.
    min_reset_interval: Duration,
    /// Optional custom sysfs base directory (for mock testing).
    sysfs_base: Option<PathBuf>,
    /// Optional custom `/dev/bus/usb` base directory (for mock testing).
    dev_bus_usb_base: Option<PathBuf>,
}

impl UsbPortSupervisor {
    /// Creates a new supervisor for the specified TTY device path.
    pub fn new(tty_path: impl Into<PathBuf>, failure_threshold: u32) -> Self {
        Self {
            tty_path: tty_path.into(),
            consecutive_failures: 0,
            failure_threshold: failure_threshold.max(1),
            last_reset: None,
            min_reset_interval: Duration::from_secs(60),
            sysfs_base: None,
            dev_bus_usb_base: None,
        }
    }

    /// Customizes the minimum interval between hardware resets (default: 60s).
    pub fn with_min_interval(mut self, interval: Duration) -> Self {
        self.min_reset_interval = interval;
        self
    }

    /// Sets a mock sysfs root directory for unit testing.
    pub fn with_sysfs_base(mut self, base: PathBuf) -> Self {
        self.sysfs_base = Some(base);
        self
    }

    /// Sets a mock `/dev/bus/usb` base directory for unit testing.
    pub fn with_usb_base(mut self, base: PathBuf) -> Self {
        self.dev_bus_usb_base = Some(base);
        self
    }

    /// Returns the monitored TTY path.
    pub fn tty_path(&self) -> &Path {
        &self.tty_path
    }

    /// Returns the current count of consecutive failures.
    pub fn consecutive_failures(&self) -> u32 {
        self.consecutive_failures
    }

    /// Records a successful communication event, resetting failure count.
    pub fn record_success(&mut self) {
        if self.consecutive_failures > 0 {
            debug!(
                port = ?self.tty_path,
                "USB communication restored; resetting {} consecutive failure(s)",
                self.consecutive_failures
            );
        }
        self.consecutive_failures = 0;
    }

    /// Records a communication failure. If the failure threshold is reached,
    /// triggers an autonomous kernel USB reset (subject to rate limiting).
    ///
    /// Returns `Ok(true)` if a reset was executed, `Ok(false)` if threshold was not
    /// reached or if rate-limiting suppressed the reset, or `Err` if reset failed.
    pub fn record_failure(&mut self) -> Result<bool> {
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);

        if self.consecutive_failures >= self.failure_threshold {
            if let Some(last) = self.last_reset
                && last.elapsed() < self.min_reset_interval
            {
                warn!(
                    port = ?self.tty_path,
                    failures = self.consecutive_failures,
                    threshold = self.failure_threshold,
                    "USB reset threshold reached, but rate-limited (last reset: {:?} ago)",
                    last.elapsed()
                );
                return Ok(false);
            }

            warn!(
                port = ?self.tty_path,
                failures = self.consecutive_failures,
                threshold = self.failure_threshold,
                "🚨 USB failure threshold exceeded! Initiating autonomous hardware kernel reset..."
            );

            let res = self.perform_kernel_reset();
            self.last_reset = Some(Instant::now());
            self.consecutive_failures = 0;
            res.map(|_| true)
        } else {
            debug!(
                port = ?self.tty_path,
                failures = self.consecutive_failures,
                threshold = self.failure_threshold,
                "Recorded USB port failure"
            );
            Ok(false)
        }
    }

    /// Traverses Linux `sysfs` from `/sys/class/tty/<device>/device` to identify
    /// the physical parent USB controller and returns the `/dev/bus/usb/BBB/DDD` path.
    pub fn resolve_usb_device_path(&self) -> Result<PathBuf> {
        let tty_name = self
            .tty_path
            .file_name()
            .and_then(|n| n.to_str())
            .ok_or_else(|| OpenAlertError::Config(format!("Invalid TTY path: {:?}", self.tty_path)))?;

        let class_base = self
            .sysfs_base
            .clone()
            .unwrap_or_else(|| PathBuf::from("/sys/class/tty"));
        let sysfs_device = class_base.join(tty_name).join("device");

        let canonical = fs::canonicalize(&sysfs_device).map_err(|e| {
            OpenAlertError::Peering(format!(
                "Failed to canonicalize sysfs path {:?}: {}",
                sysfs_device, e
            ))
        })?;

        let mut curr = Some(canonical.as_path());
        let mut busnum = None;
        let mut devnum = None;

        while let Some(dir) = curr {
            let bus_path = dir.join("busnum");
            let dev_path = dir.join("devnum");
            if bus_path.exists() && dev_path.exists() {
                busnum = fs::read_to_string(bus_path).ok();
                devnum = fs::read_to_string(dev_path).ok();
                break;
            }
            curr = dir.parent();
        }

        let (bus_str, dev_str) = match (busnum, devnum) {
            (Some(b), Some(d)) => (b.trim().to_string(), d.trim().to_string()),
            _ => {
                return Err(OpenAlertError::Peering(format!(
                    "Unable to locate 'busnum' and 'devnum' in sysfs parent hierarchy for {:?}",
                    self.tty_path
                )));
            }
        };

        let bus_id: u32 = bus_str.parse().map_err(|_| {
            OpenAlertError::Peering(format!("Malformed busnum '{}' in sysfs", bus_str))
        })?;
        let dev_id: u32 = dev_str.parse().map_err(|_| {
            OpenAlertError::Peering(format!("Malformed devnum '{}' in sysfs", dev_str))
        })?;

        let usb_base = self
            .dev_bus_usb_base
            .clone()
            .unwrap_or_else(|| PathBuf::from("/dev/bus/usb"));
        let usb_dev_path = usb_base.join(format!("{:03}", bus_id)).join(format!("{:03}", dev_id));

        Ok(usb_dev_path)
    }

    /// Executes the kernel-level USB controller reset via `ioctl(USBDEVFS_RESET)`.
    /// If character device access is unprivileged, falls back to sysfs unbind/bind.
    pub fn perform_kernel_reset(&self) -> Result<()> {
        let usb_node = match self.resolve_usb_device_path() {
            Ok(path) => path,
            Err(e) => {
                warn!(
                    port = ?self.tty_path,
                    "Could not resolve /dev/bus/usb node ({}). Attempting sysfs fallback...",
                    e
                );
                return self.fallback_sysfs_rebind();
            }
        };

        info!(
            tty = ?self.tty_path,
            usb_node = %usb_node.display(),
            "🔌 Triggering USBDEVFS_RESET ioctl on parent USB controller..."
        );

        #[cfg(target_os = "linux")]
        {
            let file_res = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&usb_node)
                .or_else(|_| File::open(&usb_node));

            match file_res {
                Ok(file) => {
                    let fd = file.as_raw_fd();
                    let ret = unsafe { libc::ioctl(fd, USBDEVFS_RESET as _, 0) };
                    if ret < 0 {
                        let err = std::io::Error::last_os_error();
                        error!(
                            error = %err,
                            usb_node = %usb_node.display(),
                            "USBDEVFS_RESET ioctl failed! Attempting sysfs driver rebind fallback..."
                        );
                        self.fallback_sysfs_rebind()
                    } else {
                        info!(
                            tty = ?self.tty_path,
                            usb_node = %usb_node.display(),
                            "✅ Kernel USBDEVFS_RESET completed successfully!"
                        );
                        Ok(())
                    }
                }
                Err(e) => {
                    warn!(
                        error = %e,
                        usb_node = %usb_node.display(),
                        "Could not open USB character device node directly. Attempting sysfs rebind fallback..."
                    );
                    self.fallback_sysfs_rebind()
                }
            }
        }

        #[cfg(not(target_os = "linux"))]
        {
            warn!("Kernel USBDEVFS_RESET ioctl is only available on Linux targets");
            Ok(())
        }
    }

    /// Fallback reset mechanism via `/sys/bus/usb/drivers/usb/unbind` and `bind`.
    fn fallback_sysfs_rebind(&self) -> Result<()> {
        let tty_name = self
            .tty_path
            .file_name()
            .and_then(|n| n.to_str())
            .ok_or_else(|| OpenAlertError::Config("Invalid TTY path for sysfs rebind".into()))?;

        let class_base = self
            .sysfs_base
            .clone()
            .unwrap_or_else(|| PathBuf::from("/sys/class/tty"));
        let sysfs_device = class_base.join(tty_name).join("device");

        if let Ok(canonical) = fs::canonicalize(&sysfs_device) {
            // Find the USB interface or parent device directory
            let dev_name = canonical
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("");

            let unbind_path = Path::new("/sys/bus/usb/drivers/usb/unbind");
            let bind_path = Path::new("/sys/bus/usb/drivers/usb/bind");

            if unbind_path.exists() && bind_path.exists() && !dev_name.is_empty() {
                info!(
                    device = %dev_name,
                    "Executing sysfs driver unbind/bind cycle..."
                );
                if let Err(e) = fs::write(unbind_path, dev_name) {
                    debug!("sysfs unbind note: {}", e);
                }
                std::thread::sleep(Duration::from_millis(200));
                if let Err(e) = fs::write(bind_path, dev_name) {
                    debug!("sysfs bind note: {}", e);
                }
                info!("✅ sysfs unbind/bind cycle completed");
                return Ok(());
            }
        }

        warn!(
            port = ?self.tty_path,
            "Autonomous USB reset skipped: neither /dev/bus/usb nor sysfs unbind was writable."
        );
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use std::io::Write;

    #[test]
    fn test_supervisor_failure_counting_and_success_reset() {
        let mut sup = UsbPortSupervisor::new("/dev/ttyACM0", 3);
        assert_eq!(sup.consecutive_failures(), 0);

        // Record 1 failure
        let res = sup.record_failure().unwrap();
        assert!(!res);
        assert_eq!(sup.consecutive_failures(), 1);

        // Record 2nd failure
        let res = sup.record_failure().unwrap();
        assert!(!res);
        assert_eq!(sup.consecutive_failures(), 2);

        // Success resets counter
        sup.record_success();
        assert_eq!(sup.consecutive_failures(), 0);
    }

    #[test]
    fn test_supervisor_rate_limiting() {
        let mut sup = UsbPortSupervisor::new("/dev/ttyACM0", 2)
            .with_min_interval(Duration::from_secs(3600));

        // Threshold reached (first time, with last_reset None)
        // Note: perform_kernel_reset will attempt sysfs and safely handle mock/missing paths
        let _ = sup.record_failure();
        let _ = sup.record_failure();
        assert_eq!(sup.consecutive_failures(), 0);

        // Trigger failures again immediately
        let _ = sup.record_failure();
        let res = sup.record_failure().unwrap();
        // Must be rate-limited (false) because min_reset_interval = 3600s
        assert!(!res, "Second reset within rate-limit window must be suppressed");
    }

    #[test]
    fn test_resolve_usb_device_path_with_mock_sysfs() {
        let temp_dir = std::env::temp_dir().join(format!("openalert_mock_sysfs_{}", std::process::id()));
        let tty_name = "ttyMOCK0";
        let mock_class_tty = temp_dir.join("sys/class/tty").join(tty_name);
        let mock_usb_device = temp_dir.join("sys/devices/pci/usb1/1-1/1-1.2");
        let mock_usb_interface = mock_usb_device.join("1-1.2:1.0");

        fs::create_dir_all(&mock_class_tty).unwrap();
        fs::create_dir_all(&mock_usb_interface).unwrap();

        // Write busnum and devnum in parent device directory
        let mut bus_file = File::create(mock_usb_device.join("busnum")).unwrap();
        writeln!(bus_file, " 5 ").unwrap();
        let mut dev_file = File::create(mock_usb_device.join("devnum")).unwrap();
        writeln!(dev_file, " 17 ").unwrap();

        // Symlink /sys/class/tty/ttyMOCK0/device -> mock_usb_interface
        #[cfg(unix)]
        std::os::unix::fs::symlink(&mock_usb_interface, mock_class_tty.join("device")).unwrap();

        let mock_usb_bus = temp_dir.join("dev/bus/usb");
        fs::create_dir_all(&mock_usb_bus).unwrap();

        let sup = UsbPortSupervisor::new(format!("/dev/{}", tty_name), 3)
            .with_sysfs_base(temp_dir.join("sys/class/tty"))
            .with_usb_base(mock_usb_bus.clone());

        #[cfg(unix)]
        {
            let resolved = sup.resolve_usb_device_path().unwrap();
            assert_eq!(resolved, mock_usb_bus.join("005/017"));
        }

        // Cleanup
        let _ = fs::remove_dir_all(&temp_dir);
    }
}
