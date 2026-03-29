# hdc-py

A Python wrapper around the (Open)Harmony Device Connector `hdc`.
Using the library requires the `hdc` tool to already be installed.

Release notes and migration guide: [CHANGELOG.md](/Users/jschwender/Dev/hdc-py/CHANGELOG.md)

The API is split into global `hdc` operations and target-specific device operations:

```python
from hdc_py import Hdc

hdc = Hdc()
device = hdc.connect()  # or hdc.connect(target="127.0.0.1:55555")
result = device.cmd("echo hello", capture_output=True, text=True)
```

`HarmonyDeviceConnector` remains available as a compatibility wrapper around a concrete connected device.

hdc-py is meant to make writing scripts for testing on OpenHarmony devices easier,
and provide abstractions. Goals include:

- Improved error checking and validation of command success
- Multi-device support via `Hdc.connect(...)` and automatic `-t <target>` scoping on device commands
- Support `with` syntax to enable performance mode for a number of commands,
  and disable the performance mode again, even if an exception occurs

This library is still under active development and far from complete. Known limitations include:

- Only a subset of commands is currently wrapped


This library is not an official OpenHarmony project.
