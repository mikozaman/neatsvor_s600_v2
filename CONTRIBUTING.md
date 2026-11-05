# Contributing

Thanks for helping. This integration is unofficial and reverse-engineered, so reports
from real robots are the most valuable contribution.

## Help test on real hardware

« Si vous avez un modèle similaire, aidez-moi à tester les niveaux d'eau/aspiration et
ouvrez une Issue avec vos logs »

If you own a similar model, help verify the water and suction levels and open an issue
with your logs. Redact MAC addresses, emails and tokens first (the diagnostics download
already does this).

## Development

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
ruff check .
pytest
```

The tests need no robot and no network: MQTT and HTTP are mocked.

## Pull requests

1. Branch from `main`.
2. Add or update tests with your change (write the failing test first).
3. Keep `ruff check .` and `pytest` green; CI also runs hassfest and the HACS validation.
4. Describe what you verified, and say clearly if something was not tested on a real robot.
