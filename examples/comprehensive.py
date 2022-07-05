import random
import time

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
    with ddclient.trace("do.work") as operation:
        ddclient.count()
        operation.set_tag("quantity", quantity)
        ddclient.info("about to do some serious work")

        with ddclient.measure("work"):
            for i in range(quantity):
                with ddclient.trace("sub.work"):
                    time.sleep(random.randint(10, 1000) / 1000)

        ddclient.warning("uhoh")
        ddclient.error("whoops")


ddclient.profiling_start()
do_work(10)
ddclient.profiling_stop()
ddclient.flush()
