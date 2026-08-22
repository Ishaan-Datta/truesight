# Truesight

Truesight captures a screenshot with `niri` and sends it to an already-running
Surya OCR 2 server. The project-local `surya_slim` package supports both vLLM
and llama.cpp through their OpenAI-compatible HTTP APIs. It does not install,
start, stop, or otherwise manage an inference server.

## Installation

Build or run the Nix package directly from the repository:

```bash
nix build
nix run -- --config ./config.toml
```

The package supplies the `niri`, `wl-copy`, and `notify-send` commands used at
runtime. A `truesight` console script is also installed by the Python package.

<!-- TODO: need to add example of adding to the configuration, like desktop-reminder-system.. -->

## Configuration

Pass the configuration file explicitly:

```bash
uv run python main.py --config ./config.toml
```

```toml
[capture]
picture_directory = "/tmp"
confidence_threshold = 0.5

[endpoint_config]
api_url = "http://localhost:8000/v1"
health_url = "http://localhost:8000/health"
model = "datalab-to/surya-ocr-2"

request_timeout_seconds = 600.0
health_timeout_seconds = 30.0
health_interval_seconds = 1.0
retry_backoff_seconds = 1.5

max_tokens = 12288
temperature = 0.0
top_p = 0.1
```

Screenshots are written to `picture_directory`, which defaults to `/tmp` when
the `[capture]` table or setting is omitted. OCR HTML is printed and copied to the
Wayland clipboard with `wl-copy` only when page confidence meets
`confidence_threshold`. A response without confidence is rejected.

The package never searches for a configuration file. Environment variables are
used when no file is passed, or as lower-priority fallbacks for settings omitted
from the supplied TOML file:

```text
TRUESIGHT_API_URL
TRUESIGHT_HEALTH_URL
TRUESIGHT_MODEL
TRUESIGHT_API_KEY
TRUESIGHT_REQUEST_TIMEOUT_SECONDS
TRUESIGHT_HEALTH_TIMEOUT_SECONDS
TRUESIGHT_HEALTH_INTERVAL_SECONDS
TRUESIGHT_RETRY_BACKOFF_SECONDS
TRUESIGHT_MAX_TOKENS
TRUESIGHT_TEMPERATURE
TRUESIGHT_TOP_P
```

Per-field precedence is an explicitly constructed `EndpointConfig`, then the
supplied TOML file, then environment variables, then defaults. Prefer the
environment for `TRUESIGHT_API_KEY` so credentials do not enter source control.

The client adapts the full-page OCR prompt, image normalization, label mapping,
and HTML parsing behavior from the Apache-2.0 licensed
[Surya project](https://github.com/datalab-to/surya). Model weights are not
distributed by this project and retain their own license.
