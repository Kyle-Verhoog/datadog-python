import json
import logging
import sys
import threading

from ddtrace.internal.compat import get_connection_response, httplib
from ddtrace.internal.periodic import PeriodicService

logger = logging.getLogger(__name__)


class V2LogWriter(PeriodicService):
    """
    v1/input:
        - max payload size: 5MB
        - max single log: 1MB
        - max array size 1000

    refs:
        - https://docs.datadoghq.com/api/latest/logs/#send-logs
    """

    def __init__(self, site, api_key, interval, timeout):
        # type: (str, str, float, float) -> None
        super(V2LogWriter, self).__init__(interval=interval)
        self._lock = threading.Lock()
        self._buffer = []
        self._timeout = timeout  # type: float
        self._api_key = api_key
        self._site = site
        self._headers = {
            "DD-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

    def enqueue(self, log):
        # type: (dict) -> None
        with self._lock:
            self._buffer.append(log)

    def periodic(self):
        if not self._buffer:
            return

        payload = json.dumps(self._buffer)
        self._buffer = []
        conn = httplib.HTTPSConnection(
            "http-intake.logs.%s" % self._site, 443, timeout=self._timeout
        )
        try:
            conn.request("POST", "/api/v2/logs", payload, self._headers)
            resp = get_connection_response(conn)
            if resp.status >= 300:
                print(
                    "ddlogs error: %s %s %s" % (resp.status, resp.read(), payload),
                    file=sys.stderr,
                )
        finally:
            conn.close()
