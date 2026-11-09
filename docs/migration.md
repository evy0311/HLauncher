# Migration from the bench launcher

The plugin launcher was tested on the existing Pi 4 bench setup on October 27, 2026. The owner confirmed that the tiles responded, CarPlay displayed, and CarPlay's Honda icon returned to the launcher. The new service did not restart during that test. Worker logs recorded decoded frames and successful dongle touch transfers.

The tested deployment is `/opt/hlauncher`, with service name `hlauncher`. The prior source under `/home/pi/civic_hondalink_hdmi_probe_v1` was preserved. The bench deployment reuses `civic-bt-bench` and `civic-bt-connect` through a service drop-in; it does not start a second BlueALSA daemon. A fresh installation uses the `hlauncher-audio` and `hlauncher-connect` units supplied in this repository.

The bench service is installed and running, but not enabled at boot yet. To restart it:

```bash
sudo systemctl restart hlauncher
```

The bench rollback helper stops HLauncher and starts the original two-hour V42 command:

```bash
sudo hlauncher-rollback
```

That helper is specific to the development Pi and is not part of a fresh installation. Do not run both launchers together. No Bluetooth restart, radio firmware update or SD image change was needed for this migration.

Preferences are in `/var/lib/hlauncher/settings.json`, outside the code checkout. Logs are in `/var/log/hlauncher`, with separate plugin logs beneath `plugins/ID`. Hardware tests should cover enabling/disabling a plugin and reopening HondaLink with a selected default before enabling automatic startup.

The earlier Touch Test code is retained as `hlauncher/touch_diagnostic.py` and is not a home tile. The microphone capture and bounded HFP test helper are retained in the core; this refactor has not added a microphone page or CarPlay audio forwarding.
