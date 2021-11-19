# kyle's datadog python vision/proposal

_not for production use_

## 📈🐶 ❤️  🐍

The Datadog Python products are great but the Python offering is fragmented.

One has to configure and initialize 4 different clients (metrics, logs,
tracing, profiling) to get a cohesive experience.

It's time to unify and provide a great user experience out of the box for
users.


## proposed API


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


### package structure

```
+datadog
|
|- DDClient
|- DDConfig
```


### `ddtrace-run`

I propose `datadog-run` which will install a default `DDClient`, initialized only via environment variable
to `datadog.client`.


## open questions


- What API is exposed for flushing data?
  - Unified for entire client?
    - Reuse connections/batch data for performance.
  - Must allow both automatic + manual strategies
    - Buffer size
    - Flush period
