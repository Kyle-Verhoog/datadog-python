# kyle's datadog python vision/proposal

_not for production use_

See [`examples/comprehensive.py`](examples/comprehensive.py) for a mostly
working example of the proposed API.

## 📈🐶 ❤️  🐍


### proposed API


```python
from datadog import DDClient, DDConfig

# Options are
#  - type-checked + validated
#  - available as corresponding environment vars
ddcfg = DDConfig(
        agent_url="localhost",
        datadog_site="us1.datadoghq.com",
        service="my-python-service",
        env="prod",
        version="0.01",
        tracing_enabled=True,
        tracing_patch=True,
        tracing_modules=["django", "redis", "psycopg2"],
        tracing_sampling_rules=[("my-python-service", "prod", 0.02)],
        profiling_enabled=True,
        security_enabled=True,
        runtime_metrics_enabled=True,
)
ddclient = DDClient(config=ddcfg)

# metrics
ddclient.gauge()
ddclient.measure()
ddclient.count()
ddclient.flush_metrics()

# logs
ddclient.log()
ddclient.warning()
ddclient.exception()
ddclient.info()
ddclient.debug()
log = ddclient.getLogger()
ddclient.DDLogHandler()  # or datadog.DDLogHandler()
ddclient.flush_logs()

# tracing
ddclient.trace()
ddclient.patch()
ddclient.flush_traces()

# profiling
ddclient.profiling_start()
ddclient.profiling_stop()
ddclient.flush_profiles()
```


### `ddtrace-run`

I propose `datadog-run` which will install a default `DDClient`, initialized only via environment variable
to `datadog.client`. Essentially `sitecustomize.py` would just be something like:

```python
import datadog
from datadog import DDConfig, DDClient


_DEFAULT_CONFIG = dict(
  tracing_patch=True,  # different from the default when using the library manually
  # ... rest of defaults
)

datadog.client = DDClient(DDConfig(default_config=_DEFAULT_CONFIG))
```


## open questions/concerns


- What API is exposed for flushing data?
  - Unified for entire client?
    - Reuse connections/batch data for performance.
  - Must allow both automatic + manual strategies
    - Buffer size
    - Flush period
- What to use to locate an agent?
  - UDS vs HTTP(S) support
  - URL is weird/not intuitive with unix sockets
- Should config values store whether they are user defined?
