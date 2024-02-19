import inspect
import logging
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, Union, cast


import ddtrace
from ddtrace.internal.compat import get_connection_response, httplib
from ddtrace.internal.writer import AgentWriter
from ddtrace.internal.utils.formats import asbool
from ddtrace.profiling import Profiler
from ddtrace.runtime import RuntimeMetrics
from ddtrace.tracer import DD_LOG_FORMAT

from ._metrics import MetricsClient
from ._logging import V2LogWriter


logger = logging.getLogger(__name__)

TraceSampleRule = Tuple[str, str, float]
# recursive types aren't supported (yet): https://github.com/python/mypy/issues/731
# _JSON = Union[str, float, int, List["_JSON"], Dict[str, "_JSON"], None]


class _Sentinel(object):
    def __bool__(self):
        return False


_sentinel = _Sentinel()


_DEFAULT_CONFIG = dict(
    agent_hostname="localhost",
    agent_run=False,
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
)  # type: Dict[str, Any]


class DDConfig(object):
    def __init__(
        self,
        agent_hostname=_sentinel,  # type: Union[_Sentinel, str]
        agent_run=_sentinel,  # type: Union[_Sentinel, bool]
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
        default_config=_DEFAULT_CONFIG,  # type: Dict[str, Any]
    ):
        # type: (...) -> None
        if isinstance(agent_hostname, _Sentinel):
            agent_hostname = os.getenv(
                "DD_AGENT_HOST", default_config["agent_hostname"]
            )
        self.agent_hostname = agent_hostname

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
            "--publish=8126:8126",
            "--publish=8125:8125",
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
        subprocess.run(docker_cmd, check=True, capture_output=True)
        if wait:
            while True:
                conn = httplib.HTTPConnection(
                    self._config.agent_hostname, self._config.tracing_port, timeout=1.0
                )
                try:
                    conn.request("GET", "/info", {}, {})
                    resp = get_connection_response(conn)
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
        self._tracer = ddtrace.Tracer()
        self._tracer.configure(
            enabled=config.tracing_enabled,
            writer=AgentWriter(
                agent_url="http://%s:%s" % (config.agent_hostname, config.tracing_port)
            ),
        )
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

        self._agent = DDAgent(version="latest", config=config)
        if config.agent_run:
            self._agent.start(wait=True)
            logger.info("started Datadog agent")

    def trace(self, *args, **kwargs):
        # type: (...) -> ddtrace.Span
        return self._tracer.trace(*args, **kwargs)

    def traced(self, *args, **kwargs):
        return self._tracer.wrap(*args, **kwargs)

    def patch(self, modules):
        # type: (List[str]) -> None
        ddtrace._monkey.patch(raise_errors=True, **{m: True for m in modules})

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
