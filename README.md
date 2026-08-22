# Truesight

Truesight captures a screenshot with `niri` and sends it to an already-running
Surya OCR 2 server. The project-local `surya_slim` package supports both vLLM
and llama.cpp through their OpenAI-compatible HTTP APIs. It does not install,
start, stop, or otherwise manage an inference server.

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

## Library API

```python
from PIL import Image

from surya_slim import EndpointConfig, ocr_image

config = EndpointConfig.from_toml("./config.toml")
with Image.open("screenshot.png") as image:
    result = ocr_image(image, config=config)

print(result.confidence)
for block in result.blocks:
    print(block.label, block.bbox, block.html)
```

`PageOCRResult.confidence` is the mean probability derived from completion token
logprobs. Logprobs are always requested because the OpenAI-compatible protocol
has no standard overall-confidence field. Confidence is `None` if the server
does not return token logprobs. It is page-wide and is deliberately not present
on `BlockOCRResult`.

Before OCR, the client polls `/health` and discovers the served model through
`/v1/models`. OCR is attempted at most twice. A caller may provide an
`on_second_failure` callback for notification; the second error is always raised
after the callback returns.

The client adapts the full-page OCR prompt, image normalization, label mapping,
and HTML parsing behavior from the Apache-2.0 licensed
[Surya project](https://github.com/datalab-to/surya). Model weights are not
distributed by this project and retain their own license.
