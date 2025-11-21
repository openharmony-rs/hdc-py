# hdc-py

A Python wrapper around the (Open)Harmony Device Connector hdc.
Using the library requires the `hdc` tool to be already installed.

hdc-py is meant to make writing scripts for testing on OpenHarmony devices easier,
and provide abstractions. Goals include:

- Improved error checking / validation of command success
- Support `with` syntax to enable performance mode for a number of commands,
  and disable the performance mode again, even if an exception occurs.

This library is still under active development and far from complete. Known limitations include:

- Currently only supports a single connected hdc device. 
- Only a subset of commands is currently wrapped.


This library is not an official OpenHarmony project.
