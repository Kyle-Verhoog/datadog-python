import random

from datadog import DDConfig, DDClient


ddcfg = DDConfig(
    agent_url="http://localhost",
    service="demo-svc",
    env="test",
    version="0.01",
    tracing_enabled=True,
)

ddclient = DDClient(config=ddcfg)


def do_work(quantity):
    with ddclient.trace("do_work") as operation:
        ddclient.count()
        operation.set_tag("quantity", quantity)
        ddclient.info("about to do some serious work")

        with ddclient.measure("work"):
            for i in range(quantity):
                pass

        ddclient.info("did some serious work")


ddclient.profiling_start()
do_work(random.randint(1_000_000, 5_000_000))
ddclient.profiling_stop()
ddclient.flush()
