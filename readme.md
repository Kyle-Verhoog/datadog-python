# kyle's datadog python vision/proposal

_not for production use_

See [`examples/comprehensive.py`](examples/comprehensive.py) for a mostly
working example of the proposed API.

## 📈🐶 ❤️  🐍

<pre>
 ✅ traces, metrics, logs, profiles, application security, llm observability
 ✅ unified configuration
 ✅ trace-logs correlation by default
 ✅ trace-aware metrics
 ✅ typed and validated configuration
</pre>

### API


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
        llmobs_enabled=True,
        llmobs_ml_app="my-python-service",
        # llmobs_agentless_enabled=True,        # send straight to Datadog if no local agent
        # llmobs_integrations_enabled=True,     # auto-instrument openai/anthropic/etc. (default)
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
ddclient.LogHandler()  # or datadog.DDLogHandler()
ddclient.flush_logs()

# tracing
ddclient.trace()
ddclient.traced()
ddclient.patch()
ddclient.flush_traces()

# profiling
ddclient.profiling_start()
ddclient.profiling_stop()
ddclient.flush_profiles()

# llm observability
@ddclient.workflow(name="rag.answer")     # decorator (also: .task, .tool)
@ddclient.llm(model_name="gpt-4o-mini")   # decorator (also: .embedding, .retrieval, .llm_agent)
ddclient.annotate(input_data=..., output_data=..., metadata=..., tags=...)
ddclient.annotation_context(...)
ddclient.submit_evaluation(span_context=..., label=..., value=...)
ddclient.export_span(span)
ddclient.flush()                          # also flushes llm obs
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


### llm observability

LLM Observability is a first-class pillar alongside traces, metrics, logs,
and profiles — same `DDConfig`, same `DDClient`, no separate import. Turn
it on with `llmobs_enabled=True` (or `DD_LLMOBS_ENABLED=1`) and pick an
ml app with `llmobs_ml_app=` (or `DD_LLMOBS_ML_APP`). The decorators
live directly on the client:

```python
@ddclient.workflow(name="rag.answer")
def answer(question: str) -> str:
    docs = retrieve(question)
    return generate(question, docs)


@ddclient.retrieval(name="vector_search")
def retrieve(question: str):
    docs = vector_db.search(question)
    ddclient.annotate(input_data=question, output_data=docs)
    return docs


@ddclient.llm(model_name="gpt-4o-mini", model_provider="openai")
def generate(question, docs):
    # openai (anthropic, etc.) calls are auto-instrumented as child llm
    # spans when llmobs_integrations_enabled is on (default).
    return OpenAI().chat.completions.create(...).choices[0].message.content
```

`@ddclient.llm_agent` is the agentic-loop decorator — renamed from
`agent` to avoid colliding with `agent_run=` / the embedded Datadog
Agent runner. See [`examples/llmobs.py`](examples/llmobs.py) for an
end-to-end run.


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
