# Habitat HomeLink for Home Assistant

Home Assistant integration for Ice Air PTAC units with a Habitat HomeLink module.

> Status: early and untested against a live unit.

Habitat has no public API. The HomeLink app is a white-label Salus iT600 app that talks directly to AWS
(Cognito login and AWS IoT device shadows), and this integration does the same using your app login.

## Features

- Climate entity per PTAC: off / cool / heat / fan only, fan auto / low / high, target temperature in °F
- Filter run-days sensor
- Live updates over AWS IoT MQTT, with polling as a fallback

## Installation

Copy `custom_components/habitat_homelink` into your Home Assistant `config/custom_components/` directory
(or add this repo to HACS as a custom integration repository), restart, then add **Habitat HomeLink** and sign in
with your HomeLink app email and password.

## Development

```sh
uv venv -p 3.14 .venv
uv pip install -p .venv/bin/python pytest-homeassistant-custom-component pycognito==2024.5.1 boto3 "paho-mqtt>=2.0.0"
.venv/bin/python -m pytest
```

`scripts/probe.py` checks login, discovery and shadow reads against the live cloud without Home Assistant (read-only).

## Credits

Parts are adapted from [salus-it600-cloud](https://github.com/Peterka35/salus-it600-cloud) (MIT); see `LICENSE`.
Not affiliated with Habitat, Ice Air or Salus.
