import logging

from datadog import DDConfig, DDClient


log = logging.getLogger(__name__)

ddcfg = DDConfig(
    agent_run=True,
    agent_version="7.47.0",
    service="demo-svc",
    env="test",
    version_use_git=True,
    tracing_enabled=True,
)

ddclient = DDClient(config=ddcfg)

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[
        ddclient.LogHandler(),
        logging.StreamHandler(),
    ],
)


with ddclient.trace("do.work") as operation:
    pass

ddclient.shutdown()
