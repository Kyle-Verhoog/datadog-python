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
        llmobs_project_name="my-project",     # experiments/datasets live in a project
        # llmobs_app_key="...",                 # required by the eval APIs
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
ddclient.export_span(span)
ddclient.flush()                          # also flushes llm obs

# evaluations
ddclient.submit_evaluation(label="relevance", value=0.9)
ddclient.get_spans(...)                   # find spans to evaluate offline
ddclient.publish_evaluator(evaluator)     # let Datadog run it on live spans
ddclient.create_dataset(name=..., records=[...])
ddclient.create_dataset_from_csv(csv_path=..., name=..., input_data_columns=[...])
ddclient.pull_dataset(name=...)
ddclient.experiment(name=..., task=..., dataset=..., evaluators=[...])
ddclient.async_experiment(...)            # for a coroutine task
ddclient.run_experiment(...)              # build + run, returns results
ddclient.pull_experiment(experiment_id)
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


### evaluations

Scoring what the app produced is part of observing it, so evaluations are
client methods too. `metric_type` is inferred from the value and the
evaluation attaches to the span being traced, which makes the common case a
one-liner:

```python
@ddclient.workflow(name="rag.answer")
def answer(question: str) -> str:
    output = generate(question)
    ddclient.submit_evaluation("relevance", 0.92)               # score
    ddclient.submit_evaluation("tone", "formal")                # categorical
    ddclient.submit_evaluation("grounded", True,                # boolean
                               assessment="pass",
                               reasoning="every claim is in the docs")
    return output
```

A span from another process is joined by handing back what `export_span()`
produced, or by a tag it carries (`span_with_tag_value=`).

Experiments run a task over a dataset and score every row:

```python
from datadog.llmobs import BaseEvaluator, EvaluatorContext, EvaluatorResult


class AnswerLength(BaseEvaluator):
    def evaluate(self, context: EvaluatorContext):
        return EvaluatorResult(value=len(str(context.output_data)))


dataset = ddclient.create_dataset(name="cities", records=[...])
results = ddclient.run_experiment(
    name="city-lookup",
    task=task,
    dataset=dataset,
    evaluators=[AnswerLength()],
)
```

Datasets and experiments read and write through the Datadog API, so they
need an app key (`llmobs_app_key=` or `DD_APP_KEY`) on top of the api key,
and they organize under `llmobs_project_name=` (or `DD_LLMOBS_PROJECT_NAME`).
Evaluator base classes, the built-in evaluators, the llm-as-a-judge helpers
and the dataset types are re-exported from `datadog.llmobs`, so evaluator
code never imports `ddtrace` itself. See [`examples/evals.py`](examples/evals.py).


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
