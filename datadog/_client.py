import inspect
import logging
import os
import shutil
import subprocess
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    cast,
)


import ddtrace
from ddtrace.internal.http import HTTPConnection
from ddtrace.internal.utils.formats import asbool
from ddtrace.profiling import Profiler
from ddtrace.runtime import RuntimeMetrics
from ddtrace.trace import Span
from ddtrace._logger import DD_LOG_FORMAT

from ._metrics import MetricsClient
from ._logging import V2LogWriter


if TYPE_CHECKING:
    from ddtrace.llmobs._experiment import Dataset
    from ddtrace.llmobs._experiment import DatasetRecordNew
    from ddtrace.llmobs._experiment import Experiment
    from ddtrace.llmobs._experiment import ExperimentResult
    from ddtrace.llmobs._experiment import SyncExperiment


logger = logging.getLogger(__name__)

TraceSampleRule = Tuple[str, str, float]
# The value of an evaluation metric, and the metric_type it implies.
EvalValue = Union[str, int, float, bool, Dict[str, Any]]
MetricType = Literal["categorical", "score", "boolean", "json"]
# A span to join an evaluation to: a live span, or the dict produced by
# ``export_span()`` (which is what crosses a process boundary).
EvalSpan = Union[Span, Dict[str, str]]
# Experiment building blocks. Kept loose here; ``datadog.llmobs`` re-exports
# the real ddtrace types for annotating user code.
Task = Callable[..., Any]
Evaluator = Any
DEFAULT_PROJECT_NAME = "default"
# recursive types aren't supported (yet): https://github.com/python/mypy/issues/731
# _JSON = Union[str, float, int, List["_JSON"], Dict[str, "_JSON"], None]


class _Sentinel(object):
    def __bool__(self):
        return False


_sentinel = _Sentinel()


_DEFAULT_CONFIG = dict(
    agent_hostname="localhost",
    agent_run=False,
    agent_version="7.73.2",
    datadog_site="datadoghq.com",
    datadog_hostname=ddtrace.internal.hostname.get_hostname(),
    remote_configuration_enabled=True,
    metrics_port=8125,
    tracing_port=8126,
    tracing_enabled=True,
    tracing_patch=False,
    tracing_modules=["django", "redis", ...],
    profiling_enabled=False,
    runtime_metrics_enabled=False,
    llmobs_enabled=False,
    llmobs_agentless_enabled=False,
    llmobs_integrations_enabled=True,
    llmobs_project_name=DEFAULT_PROJECT_NAME,
)  # type: Dict[str, Any]


class DDConfig(object):
    def __init__(
        self,
        agent_hostname=_sentinel,  # type: Union[_Sentinel, str]
        agent_run=_sentinel,  # type: Union[_Sentinel, bool]
        agent_version=_sentinel,  # type: Union[_Sentinel, str]
        api_key=_sentinel,  # type: Union[_Sentinel, str]
        datadog_site=_sentinel,  # type: Union[_Sentinel, str]
        datadog_hostname=_sentinel,  # type: Union[_Sentinel, str]
        remote_configuration_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        service=_sentinel,  # type: Union[_Sentinel, str]
        env=_sentinel,  # type: Union[_Sentinel, str]
        version=_sentinel,  # type: Union[_Sentinel, str]
        version_use_git=_sentinel,  # type: Union[_Sentinel, bool]
        metrics_port=_sentinel,  # type: Union[_Sentinel, int]
        tracing_port=_sentinel,  # type: Union[_Sentinel, int]
        tracing_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        tracing_patch=_sentinel,  # type: Union[_Sentinel, bool]
        tracing_modules=_sentinel,  # type: Union[_Sentinel, List[str]]
        tracing_sampling_rules=_sentinel,  # type: Union[_Sentinel, List[TraceSampleRule]]
        tracing_integration_configs=_sentinel,  # type: Union[_Sentinel, ]
        profiling_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        security_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        runtime_metrics_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        llmobs_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        llmobs_ml_app=_sentinel,  # type: Union[_Sentinel, str]
        llmobs_agentless_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        llmobs_integrations_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        llmobs_app_key=_sentinel,  # type: Union[_Sentinel, str]
        llmobs_project_name=_sentinel,  # type: Union[_Sentinel, str]
        default_config=_DEFAULT_CONFIG,  # type: Dict[str, Any]
    ):
        # type: (...) -> None
        if isinstance(agent_hostname, _Sentinel):
            agent_hostname = os.getenv(
                "DD_AGENT_HOST", default_config["agent_hostname"]
            )
        self.agent_hostname = agent_hostname
        if isinstance(agent_version, _Sentinel):
            agent_version = os.getenv(
                "DD_AGENT_VERSION", default_config["agent_version"]
            )
        self.agent_version = agent_version

        if isinstance(agent_run, _Sentinel):
            agent_run = asbool(os.getenv("DD_AGENT_RUN", default_config["agent_run"]))
        self.agent_run = agent_run

        if isinstance(api_key, _Sentinel):
            api_key = os.getenv("DD_API_KEY", api_key)
        if isinstance(api_key, _Sentinel):
            raise ValueError("An API key must be set")
        self.api_key = api_key

        if isinstance(datadog_site, _Sentinel):
            datadog_site = os.getenv("DD_SITE", default_config["datadog_site"])
        self.site = cast(str, datadog_site)

        if isinstance(datadog_hostname, _Sentinel):
            datadog_hostname = os.getenv(
                "DD_HOSTNAME", default_config["datadog_hostname"]
            )
        self.hostname = cast(str, datadog_hostname)

        if isinstance(remote_configuration_enabled, _Sentinel):
            remote_configuration_enabled = asbool(
                os.getenv(
                    "DD_REMOTE_CONFIGURATION_ENABLED",
                    default_config["remote_configuration_enabled"],
                )
            )
        self.remote_configuration_enabled = remote_configuration_enabled

        if service is _sentinel:
            service = os.getenv("DD_SERVICE", service)
        if service is _sentinel or not service:
            raise ValueError(
                "A service name must be set, refer to the documentation for unified service tagging here: https://docs.datadoghq.com/getting_started/tagging/unified_service_tagging/"
            )
        self.service = service

        if env is _sentinel:
            env = os.getenv("DD_ENV", env)
        if env is _sentinel or not env:
            raise ValueError(
                "An env must be set, refer to the documentation for unified service tagging here: https://docs.datadoghq.com/getting_started/tagging/unified_service_tagging/"
            )
        self.env = env

        if isinstance(version, _Sentinel):
            version = os.getenv("DD_VERSION", version)
        self.version = version

        if isinstance(version_use_git, _Sentinel):
            if "DD_VERSION_USE_GIT" in os.environ:
                if asbool(os.getenv("DD_VERSION_USE_GIT")):
                    version_use_git = True
        if version_use_git:
            import git

            self.version = str(
                git.Repo(search_parent_directories=True).head.object.hexsha[0:6]
            )

        if not isinstance(version, _Sentinel) and not isinstance(
            version_use_git, _Sentinel
        ):
            raise ValueError(
                "Ambiguous version! Cannot use both custom version %r and git version"
                % self.version
            )
        if not self.version:
            raise ValueError(
                "A version must be set, refer to the documentation for unified service tagging here: https://docs.datadoghq.com/getting_started/tagging/unified_service_tagging/"
            )

        if isinstance(metrics_port, _Sentinel):
            metrics_port = int(
                os.getenv("DD_DOGSTATSD_PORT", default_config["metrics_port"])
            )
        self.metrics_port = metrics_port

        if isinstance(tracing_port, _Sentinel):
            tracing_port = int(
                os.getenv("DD_AGENT_PORT", default_config["tracing_port"])
            )
        self.tracing_port = tracing_port

        if isinstance(tracing_enabled, _Sentinel):
            tracing_enabled = asbool(
                os.getenv("DD_TRACE_ENABLED", default_config["tracing_enabled"])
            )
        self.tracing_enabled = tracing_enabled

        if isinstance(tracing_modules, _Sentinel):
            tracing_modules = (
                os.getenv("DD_TRACE_MODULES", "").split(",")
                or default_config["tracing_modules"]
            )

        if isinstance(tracing_patch, _Sentinel):
            tracing_patch = asbool(
                os.getenv("DD_TRACE_PATCH", default_config["tracing_patch"])
            )
        if tracing_patch:
            ddtrace.patch(**{m: True for m in tracing_modules})

        if profiling_enabled is _sentinel:
            profiling_enabled = asbool(
                os.getenv("DD_PROFILING_ENABLED", default_config["profiling_enabled"])
            )
        self.profiling_enabled = profiling_enabled

        if runtime_metrics_enabled is _sentinel:
            runtime_metrics_enabled = asbool(
                os.getenv(
                    "DD_RUNTIME_METRICS_ENABLED",
                    default_config["runtime_metrics_enabled"],
                )
            )
        self.runtime_metrics_enabled = runtime_metrics_enabled

        if isinstance(llmobs_enabled, _Sentinel):
            llmobs_enabled = asbool(
                os.getenv("DD_LLMOBS_ENABLED", default_config["llmobs_enabled"])
            )
        self.llmobs_enabled = llmobs_enabled

        if isinstance(llmobs_ml_app, _Sentinel):
            llmobs_ml_app = os.getenv("DD_LLMOBS_ML_APP", self.service)
        self.llmobs_ml_app = llmobs_ml_app

        if isinstance(llmobs_agentless_enabled, _Sentinel):
            llmobs_agentless_enabled = asbool(
                os.getenv(
                    "DD_LLMOBS_AGENTLESS_ENABLED",
                    default_config["llmobs_agentless_enabled"],
                )
            )
        self.llmobs_agentless_enabled = llmobs_agentless_enabled

        if isinstance(llmobs_integrations_enabled, _Sentinel):
            llmobs_integrations_enabled = asbool(
                os.getenv(
                    "DD_LLMOBS_INTEGRATIONS_ENABLED",
                    default_config["llmobs_integrations_enabled"],
                )
            )
        self.llmobs_integrations_enabled = llmobs_integrations_enabled

        # The app key is only needed by the eval APIs (datasets, experiments,
        # publishing evaluators) which talk to the Datadog API directly, so an
        # empty one is not an error until one of those is used.
        if isinstance(llmobs_app_key, _Sentinel):
            llmobs_app_key = os.getenv("DD_APP_KEY", "")
        self.llmobs_app_key = cast(str, llmobs_app_key)

        if isinstance(llmobs_project_name, _Sentinel):
            llmobs_project_name = os.getenv(
                "DD_LLMOBS_PROJECT_NAME", default_config["llmobs_project_name"]
            )
        self.llmobs_project_name = cast(str, llmobs_project_name)


def _infer_metric_type(label, value):
    # type: (str, EvalValue) -> MetricType
    # bool first: it is a subclass of int and would otherwise read as a score.
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "score"
    if isinstance(value, str):
        return "categorical"
    if isinstance(value, dict):
        return "json"
    raise ValueError(
        "Cannot infer the metric type of the %r evaluation from a %s value. "
        "Pass metric_type= explicitly." % (label, type(value).__name__)
    )


class DDAgent:
    def __init__(self, version: str, config: DDConfig):
        self._proc = None
        self._version = version
        self._config = config

    def start(self, wait: bool):
        if self._proc:
            raise RuntimeError("Agent is already running")
        docker_exec = shutil.which("docker")
        if not docker_exec:
            raise RuntimeError(
                "docker installation not found and is required for running the agent"
            )
        docker_cmd = [
            docker_exec,
            "run",
            "--name=datadog-agent",
            "--detach",
            "--rm",
            f"--publish=8126:{self._config.tracing_port}",
            f"--publish=8125:{self._config.metrics_port}",
            "--volume=/var/run/docker.sock:/var/run/docker.sock",
            "--volume=/proc/:/host/proc/:ro",
            "--volume=/sys/fs/cgroup:/host/sys/fs/cgroup:ro",
            "--env=DD_API_KEY=%s" % self._config.api_key,
            "--env=DD_REMOTE_CONFIGURATION_ENABLED=%s"
            % ("true" if self._config.remote_configuration_enabled else "false"),
            "--env=DD_SITE=%s" % self._config.site,
            "--env=DD_DOGSTATSD_NON_LOCAL_TRAFFIC=true",
            "--env=DD_BIND_HOST=0.0.0.0",
            "datadog/agent:%s" % self._version,
        ]
        logger.debug("starting agent with command %r", " ".join(docker_cmd))
        try:
            self._proc = subprocess.run(docker_cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError("Failed to start Datadog Agent. Likely it is already running! Remove the agent_run=True setting if the Agent is being managed separately.") from e
        if wait:
            while True:
                conn = HTTPConnection(
                    self._config.agent_hostname, self._config.tracing_port, timeout=1.0
                )
                try:
                    conn.request("GET", "/info", {}, {})
                    resp = conn.getresponse()
                except Exception:
                    time.sleep(0.01)
                else:
                    if resp.status == 200:
                        break
                finally:
                    conn.close()

    def stop(self):
        if self._proc:
            subprocess.run([shutil.which("docker"), "kill", "datadog-agent"], check=True, capture_output=True)


class DDClient:
    def __init__(
        self,
        config,  # type: DDConfig
    ):
        # type: (...) -> None
        self._config = config
        ddtrace.config.service = config.service
        ddtrace.config.env = config.env
        ddtrace.config.version = config.version
        ddtrace.config._128_bit_trace_id_enabled = False
        ddtrace.config.trace_agent_host = config.agent_hostname
        ddtrace.config.trace_agent_port = config.tracing_port
        ddtrace.config._remote_config_enabled = config.remote_configuration_enabled
        self._tracer = ddtrace.tracer
        self._tracer.configure(apm_tracing_disabled=not config.tracing_enabled)
        self._logger = V2LogWriter(
            site=config.site,
            api_key=config.api_key,
            interval=0.5,
            timeout=2.0,
        )
        self._logger.start()
        self._metrics = MetricsClient(
            site=config.site,
            api_key=config.api_key,
        )
        self._profiler = Profiler(
            # url=config.agent_url,  # this url is for backend
            api_key=config.api_key,
            service=config.service,
            env=config.env,
            version=config.version,
            tracer=self._tracer,
        )
        if config.profiling_enabled:
            self._profiler.start()
        if config.runtime_metrics_enabled:
            RuntimeMetrics.enable(tracer=self._tracer)

        self._agent = DDAgent(version=config.agent_version, config=config)
        if config.agent_run:
            self._agent.start(wait=True)
            logger.info("started Datadog agent")

        if config.remote_configuration_enabled:
            from ddtrace.internal.remoteconfig.worker import remoteconfig_poller

            remoteconfig_poller.enable()

        self._llmobs = None  # type: Optional[Any]
        if config.llmobs_enabled:
            from ddtrace.llmobs import LLMObs

            LLMObs.enable(
                # deprecated in ddtrace 4.x in favour of agent_service, removed in 5.0
                ml_app=config.llmobs_ml_app,
                integrations_enabled=config.llmobs_integrations_enabled,
                agentless_enabled=config.llmobs_agentless_enabled,
                site=config.site,
                api_key=config.api_key,
                app_key=config.llmobs_app_key,
                project_name=config.llmobs_project_name,
                service=config.service,
                env=config.env,
            )
            self._llmobs = LLMObs

    def trace(self, *args, **kwargs):
        # type: (...) -> Span
        return self._tracer.trace(*args, **kwargs)

    def traced(self, *args, **kwargs):
        return self._tracer.wrap(*args, **kwargs)

    def patch(self, modules):
        # type: (List[str]) -> None
        ddtrace._monkey.patch(raise_errors=True, **{m: True for m in modules})

    def _require_llmobs(self):
        if self._llmobs is None:
            raise RuntimeError(
                "LLM Observability is not enabled. Pass llmobs_enabled=True "
                "to DDConfig (or set DD_LLMOBS_ENABLED=1) to use this API."
            )
        return self._llmobs

    def _require_llmobs_app_key(self):
        # Datasets, experiments and remote evaluators are read/written through
        # the Datadog API, which needs an app key on top of the api key.
        llmobs = self._require_llmobs()
        if not self._config.llmobs_app_key:
            raise RuntimeError(
                "An app key is required for the datasets/experiments API. Pass "
                "llmobs_app_key= to DDConfig (or set DD_APP_KEY)."
            )
        return llmobs

    # -- LLM Observability decorators ---------------------------------
    # Use as ``@ddclient.workflow(name="…")`` / ``@ddclient.llm(...)`` etc.
    # Each proxies to ``ddtrace.llmobs.decorators.<kind>``, which produces
    # the LLM Obs span of the corresponding kind around the wrapped call.

    def llm(self, *args, **kwargs):
        from ddtrace.llmobs import decorators

        return decorators.llm(*args, **kwargs)

    def workflow(self, *args, **kwargs):
        from ddtrace.llmobs import decorators

        return decorators.workflow(*args, **kwargs)

    def task(self, *args, **kwargs):
        from ddtrace.llmobs import decorators

        return decorators.task(*args, **kwargs)

    def tool(self, *args, **kwargs):
        from ddtrace.llmobs import decorators

        return decorators.tool(*args, **kwargs)

    def llm_agent(self, *args, **kwargs):
        # Named ``llm_agent`` (not ``agent``) to avoid colliding with
        # ``DDClient._agent`` (the embedded Datadog Agent runner).
        from ddtrace.llmobs import decorators

        return decorators.agent(*args, **kwargs)

    def embedding(self, *args, **kwargs):
        from ddtrace.llmobs import decorators

        return decorators.embedding(*args, **kwargs)

    def retrieval(self, *args, **kwargs):
        from ddtrace.llmobs import decorators

        return decorators.retrieval(*args, **kwargs)

    # -- LLM Observability annotation / lifecycle ---------------------

    def annotate(self, *args, **kwargs):
        # type: (...) -> None
        self._require_llmobs().annotate(*args, **kwargs)

    def annotation_context(self, *args, **kwargs):
        return self._require_llmobs().annotation_context(*args, **kwargs)

    def export_span(self, *args, **kwargs):
        return self._require_llmobs().export_span(*args, **kwargs)

    # -- LLM Observability evaluations --------------------------------
    # Evaluations come in two flavours: metrics submitted against spans that
    # already happened (``submit_evaluation``), and experiments, which run a
    # task over a dataset and score each row with evaluators.

    def submit_evaluation(
        self,
        label: str,
        value: EvalValue,
        metric_type: Optional[MetricType] = None,
        span: Optional[EvalSpan] = None,
        span_with_tag_value: Optional[Dict[str, str]] = None,
        tags: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, object]] = None,
        assessment: Optional[Literal["pass", "fail"]] = None,
        reasoning: Optional[str] = None,
        timestamp_ms: Optional[int] = None,
        eval_scope: Literal["span", "trace"] = "span",
    ) -> None:
        """Attach an evaluation metric to a span.

        ``metric_type`` is inferred from ``value`` unless given, and ``span``
        defaults to the span currently being traced, so the common case is
        just ``ddclient.submit_evaluation("relevance", 0.9)``. A span from a
        previous process can be joined by passing the dict that
        ``export_span()`` produced, or by tag with ``span_with_tag_value``.
        """
        llmobs = self._require_llmobs()
        if metric_type is None:
            metric_type = _infer_metric_type(label, value)
        if span is None and span_with_tag_value is None:
            # export_span() raises rather than returning None when there is no
            # LLM Obs span in scope (a plain traced span doesn't count).
            from ddtrace.llmobs._llmobs import LLMObsExportSpanError

            try:
                span = llmobs.export_span()
            except LLMObsExportSpanError:
                span = None
            if span is None:
                raise ValueError(
                    "No LLM Obs span is currently active to attach the %r "
                    "evaluation to. Pass span= (a span, or the dict from "
                    "export_span()) or span_with_tag_value=." % label
                )
        elif isinstance(span, Span):
            span = llmobs.export_span(span)
        llmobs.submit_evaluation(
            label=label,
            metric_type=metric_type,
            value=value,
            span=span,
            span_with_tag_value=span_with_tag_value,
            tags=tags,
            metadata=metadata,
            assessment=assessment,
            reasoning=reasoning,
            timestamp_ms=timestamp_ms,
            eval_scope=eval_scope,
        )

    def get_spans(self, *args, **kwargs) -> List[Dict[str, Any]]:
        """Query already-submitted LLM Obs spans, e.g. to evaluate them offline."""
        return self._require_llmobs().get_spans(*args, **kwargs)

    def publish_evaluator(
        self,
        evaluator: Evaluator,
        eval_name: Optional[str] = None,
        variable_mapping: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Publish an evaluator so Datadog runs it against live spans."""
        return self._require_llmobs_app_key().publish_evaluator(
            evaluator=evaluator,
            ml_app=self._config.llmobs_ml_app,
            eval_name=eval_name,
            variable_mapping=variable_mapping,
        )

    # -- LLM Observability datasets -----------------------------------

    def create_dataset(
        self,
        name: str,
        records: Optional[List["DatasetRecordNew"]] = None,
        description: str = "",
        project_name: Optional[str] = None,
        **kwargs,
    ) -> "Dataset":
        return self._require_llmobs_app_key().create_dataset(
            dataset_name=name,
            project_name=self._project_name(project_name),
            description=description,
            records=records,
            **kwargs,
        )

    def create_dataset_from_csv(
        self,
        csv_path: str,
        name: str,
        input_data_columns: List[str],
        expected_output_columns: Optional[List[str]] = None,
        description: str = "",
        project_name: Optional[str] = None,
        **kwargs,
    ) -> "Dataset":
        return self._require_llmobs_app_key().create_dataset_from_csv(
            csv_path=csv_path,
            dataset_name=name,
            input_data_columns=input_data_columns,
            expected_output_columns=expected_output_columns,
            description=description,
            project_name=self._project_name(project_name),
            **kwargs,
        )

    def pull_dataset(
        self,
        name: str,
        project_name: Optional[str] = None,
        version: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> "Dataset":
        return self._require_llmobs_app_key().pull_dataset(
            dataset_name=name,
            project_name=self._project_name(project_name),
            version=version,
            tags=tags,
        )

    # -- LLM Observability experiments --------------------------------

    def experiment(
        self,
        name: str,
        task: Task,
        dataset: "Dataset",
        evaluators: Sequence[Evaluator],
        description: str = "",
        project_name: Optional[str] = None,
        **kwargs,
    ) -> "SyncExperiment":
        """Build an experiment. Call ``.run()`` on it, or use ``run_experiment``."""
        return self._require_llmobs_app_key().experiment(
            name=name,
            task=task,
            dataset=dataset,
            evaluators=evaluators,
            description=description,
            project_name=self._project_name(project_name),
            **kwargs,
        )

    def async_experiment(
        self,
        name: str,
        task: Callable[..., Awaitable[Any]],
        dataset: "Dataset",
        evaluators: Sequence[Evaluator],
        description: str = "",
        project_name: Optional[str] = None,
        **kwargs,
    ) -> "Experiment":
        """``experiment`` for a coroutine task."""
        return self._require_llmobs_app_key().async_experiment(
            name=name,
            task=task,
            dataset=dataset,
            evaluators=evaluators,
            description=description,
            project_name=self._project_name(project_name),
            **kwargs,
        )

    def run_experiment(
        self,
        name: str,
        task: Task,
        dataset: "Dataset",
        evaluators: Sequence[Evaluator],
        jobs: int = 1,
        raise_errors: bool = False,
        sample_size: Optional[int] = None,
        **kwargs,
    ) -> "ExperimentResult":
        """Build and run an experiment in one call, returning its results."""
        experiment = self.experiment(
            name=name,
            task=task,
            dataset=dataset,
            evaluators=evaluators,
            **kwargs,
        )
        return experiment.run(
            jobs=jobs, raise_errors=raise_errors, sample_size=sample_size
        )

    def pull_experiment(self, experiment_id: str) -> "SyncExperiment":
        return self._require_llmobs_app_key().pull_experiment(experiment_id)

    def _project_name(self, project_name=None):
        # type: (Optional[str]) -> str
        return project_name or self._config.llmobs_project_name

    def _dd_log(self, log_level, msg, tags=_sentinel):
        # TODO: timestamp
        log = {
            "message": msg,
            "hostname": self._config.hostname,
            "service": self._config.service,
            "ddsource": "python",
            "status": log_level,
            "ddtags": "",
        }
        tags = [] if tags is _sentinel else tags
        tags += [
            "env:%s" % self._config.env,
            "version:%s" % self._config.version,
        ]
        log["ddtags"] = ",".join(tags)
        span = self._tracer.current_span()
        if span:
            log["dd.trace_id"] = span.trace_id
            log["dd.span_id"] = span.span_id
        self._logger.enqueue(log)

    def _log(self, log_level, msg, tags=_sentinel, *args):
        # type: (Literal["error", "info", "debug", "warn"], str, Optional[List[str]], ...) -> None
        frm = inspect.stack()[2]
        mod = inspect.getmodule(frm[0])
        msg = "%s: %s" % (mod.__name__, msg % tuple(*args))
        self._dd_log(log_level=log_level, msg=msg, tags=tags)

    def log(self, log_level, msg, tags=_sentinel, *args):
        # type: (Literal["error", "info", "debug", "warn"], str, Optional[List[str]], ...) -> None
        return self._log(log_level=log_level, msg=msg, tags=tags, *args)

    def info(self, msg, tags=_sentinel, *args):
        return self._log("info", msg, tags=tags, *args)

    def warning(self, msg, tags=_sentinel, *args):
        return self._log("warn", msg, tags=tags, *args)

    def error(self, msg, tags=_sentinel, *args):
        return self._log("error", msg, tags=tags, *args)

    def count(self, metric_name=_sentinel, count=1, tags=_sentinel):
        span = self._tracer.current_span()
        if metric_name is _sentinel:
            if not span:
                raise ValueError("No metric name possible")
            metric_name = "%s.count" % span.name

        tags = [] if tags is _sentinel else tags
        if span:
            tags += [
                "service:%s" % self._config.service,
                "env:%s" % self._config.env,
                "version:%s" % self._config.version,
            ]
        self._metrics.count(metric_name, count, tags=tags)

    def measure(self, metric_name, tags=_sentinel):
        if tags is _sentinel:
            tags = []
        return self._metrics.measure(metric_name, tags)

    def gauge(self, metric_name, val, tags=_sentinel):
        tags = [] if tags is _sentinel else tags
        tags += [
            "service:%s" % self._config.service,
            "env:%s" % self._config.env,
            "version:%s" % self._config.version,
        ]
        span = self._tracer.current_span()
        if span:
            metric_name = "%s.%s" % (span.name, metric_name)
        self._metrics.gauge(metric_name, val, tags=tags)

    def profiling_start(self, *args, **kwargs):
        # type: (...) -> None
        self._profiler.start(*args, **kwargs)

    def profiling_stop(self, *args, **kwargs):
        # type: (...) -> None
        self._profiler.stop(*args, **kwargs)

    def _flush_traces(self):
        self._tracer.flush()

    def _flush_metrics(self):
        self._metrics.flush()

    def _flush_logs(self):
        self._logger.periodic()

    def flush(self):
        self._flush_metrics()
        self._flush_traces()
        self._flush_logs()
        if self._llmobs is not None:
            self._llmobs.flush()

    @property
    def log_format(self):
        # type: () -> str
        return DD_LOG_FORMAT

    @property
    def LogHandler(self):
        # type: () -> Type[logging.Handler]
        _self = self

        class DDLogHandler(logging.Handler):
            def emit(self, record):
                # TODO: error info exc_info, exc_text, funcName
                msg = "%s: %s" % (
                    record.__dict__["name"],
                    record.__dict__["msg"] % record.__dict__["args"],
                )
                level = record.__dict__["levelname"].lower()
                _self._dd_log(msg=msg, log_level=level)

        return DDLogHandler

    def shutdown(self):
        self.flush()
        self._agent.stop()
