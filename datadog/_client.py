import os
import time
from typing import Dict, List, Tuple, Union

import ddtrace
from ddtrace.internal.writer import AgentWriter
from ddtrace.internal.utils.formats import asbool, parse_tags_str
from ddtrace.profiling import Profiler
from ddtrace.runtime import RuntimeMetrics

from ._metrics import MetricsClient
from ._logging import LogWriterV1, LogEvent


TraceSampleRule = Tuple[str, str, float]


class _Sentinel(object):
    pass


_sentinel = _Sentinel()


_DEFAULT_CONFIG = dict(
    agent_url="http://localhost",
    datadog_site="datadoghq.com",
    tracing_enabled=True,
    tracing_patch=False,
    tracing_modules=["django", "redis", ...],
    profiling_enabled=False,
    runtime_metrics_enabled=False,
)


class DDConfig(object):
    def __init__(
        self,
        agent_url=_sentinel,  # type: Union[_Sentinel, str]
        api_key=_sentinel,  # type: Union[_Sentinel, str]
        datadog_site=_sentinel,  # type: Union[_Sentinel, str]
        service=_sentinel,  # type: Union[_Sentinel, str]
        env=_sentinel,  # type: Union[_Sentinel, str]
        version=_sentinel,  # type: Union[_Sentinel, str]
        tracing_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        tracing_patch=_sentinel,  # type: Union[_Sentinel, bool]
        tracing_modules=_sentinel,  # type: Union[_Sentinel, List[str]]
        tracing_sampling_rules=_sentinel,  # type: Union[_Sentinel, List[TraceSampleRule]]
        tracing_integration_configs=_sentinel,  # type: Union[_Sentinel, ]
        profiling_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        security_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        runtime_metrics_enabled=_sentinel,  # type: Union[_Sentinel, bool]
        default_config=_DEFAULT_CONFIG,  # type: Dict[str, str]
    ):
        # type: (...) -> None
        if agent_url is _sentinel:
            agent_url = os.getenv("DD_AGENT_URL", default_config["agent_url"])
        self.agent_url = agent_url

        if api_key is _sentinel:
            api_key = os.getenv("DD_API_KEY", api_key)
        if api_key is _sentinel:
            raise ValueError("An API key must be set")
        self.api_key = api_key

        if datadog_site is _sentinel:
            datadog_site = os.getenv("DD_SITE", default_config["datadog_site"])
        self.site = datadog_site

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

        if version is _sentinel:
            version = os.getenv("DD_VERSION", version)
        if version is _sentinel or not version:
            raise ValueError(
                "A version must be set, refer to the documentation for unified service tagging here: https://docs.datadoghq.com/getting_started/tagging/unified_service_tagging/"
            )
        self.version = version

        if tracing_enabled is _sentinel:
            tracing_enabled = asbool(
                os.getenv("DD_TRACE_ENABLED", default_config["tracing_enabled"])
            )
        self.tracing_enabled = tracing_enabled

        if tracing_modules is _sentinel:
            tracing_modules = parse_tags_str(os.getenv("DD_PATCH_MODULES"))

        if tracing_patch is _sentinel:
            tracing_patch = asbool(
                os.getenv("DD_TRACE_PATCH", default_config["tracing_patch"])
            )
        if tracing_patch:
            ddtrace.patch(*tracing_modules)

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


class DDClient(object):
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
            writer=AgentWriter(agent_url="%s:%s" % (config.agent_url, 8126)),
        )
        self._logger = LogWriterV1(
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

    def trace(self, *args, **kwargs):
        # type: (...) -> ddtrace.Span
        return self._tracer.trace(*args, **kwargs)

    def patch(self, modules):
        # type: (...) -> None
        ddtrace._monkey.patch(modules)

    def _date_fmt(self, t):
        ct = time.localtime(t)
        default_time_format = "%Y-%m-%d %H:%M:%S"
        default_msec_format = "%s,%03d"
        s = time.strftime(default_time_format, ct)
        s = default_msec_format % (s, (t - int(t)) * 1000)
        return s

    def log(self, log_level, msg, tags=_sentinel, *args):
        # (Literal["ERROR", "INFO", "DEBUG", "WARNING"], str, Optional[List[str]] ...) -> None
        t = time.time()
        date_fmt = self._date_fmt(t)
        log = {
            "date": date_fmt,
            "message": msg % tuple(*args),
            "hostname": ddtrace.internal.hostname.get_hostname(),
            "service": self._config.service,
            "ddsource": "python",
            "status": log_level,
            "ddtags": "",
        }  # type: LogEvent
        tags = [] if tags is _sentinel else tags
        tags += [
            "env:%s" % self._config.env,
            "version:%s" % self._config.version,
        ]
        span = self._tracer.current_span()
        if span:
            tags += [
                "dd.trace_id:%s" % span.trace_id,
                "dd.span_id:%s" % span.span_id,
            ]
        log["ddtags"] = ",".join(tags)
        self._logger.enqueue(log)

    def info(self, msg, tags=_sentinel, *args):
        return self.log("INFO", msg, tags=tags, *args)

    def warning(self, msg, tags=_sentinel, *args):
        return self.log("WARN", msg, tags=tags, *args)

    def error(self, msg, tags=_sentinel, *args):
        return self.log("ERROR", msg, tags=tags, *args)

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
