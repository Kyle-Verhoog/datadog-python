"""
https://docs.datadoghq.com/api/latest/metrics/
"""
from contextlib import contextmanager
import logging
import time
from typing import Callable
from typing import List
from typing import Literal
from typing import Optional
from typing import Tuple
from typing import TypedDict
from typing import Union
from typing_extensions import NotRequired

import requests


log = logging.getLogger(__name__)

Point = Tuple[int, Union[int, float]]
Tags = List[str]


class V1Metric(TypedDict):
    metric: str
    type: Literal["count", "gauge", "rate"]
    points: List[Point]
    tags: List[str]
    interval: NotRequired[int]


class MetricsClient(object):
    def __init__(self, site, api_key):
        self._site = site
        self._api_key = api_key
        self._metrics = []  # type: List[V1Metric]

    def count(self, name, count, interval=1, tags=None):
        # type: (str, int, int, Optional[List[str]]) -> None
        tags = tags or []
        point = (int(time.time()), count)  # type: Point
        metric = V1Metric(
            metric=name,
            type="count",
            interval=interval,
            points=[point],
            tags=tags,
        )
        self._metrics.append(metric)

    def gauge(self, name, val, tags=None):
        # type: (str, Union[int, float], Optional[List[str]]) -> None
        tags = tags or []
        point = (int(time.time()), val)  # type: Point
        metric = V1Metric(
            metric=name,
            type="gauge",
            points=[point],
            tags=tags,
        )
        self._metrics.append(metric)

    @contextmanager
    def _measure(self, name, tags):
        start = time.time_ns()
        yield
        end = time.time_ns()
        point = (int(time.time()), end - start)  # type: Point
        metric = V1Metric(
            metric=name,
            type="dist",
            points=[point],
            tags=tags,
        )
        self._metrics.append(metric)

    def measure(self, name, tags=None):
        # type: (str, Optional[Tags]) -> Callable
        return self._measure(name, tags)

    def flush(self):
        # type: () -> None
        headers = {
            "Content-Type": "text/json",
            "DD-API-KEY": self._api_key,
        }
        data = {"series": self._metrics}
        self._metrics = []
        resp = requests.post(
            "https://api.%s/api/v1/series" % self._site, headers=headers, json=data
        )
        resp.raise_for_status()
        log.debug(
            "flushed %d metrics: %s",
            len(data["series"]),
            ["%s<%s>" % (m["type"], m["metric"]) for m in data["series"]],
        )
