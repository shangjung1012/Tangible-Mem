from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from share_mem.l1 import multi_agent_agents


class _FakeStatusError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code


class MultiAgentRetryPolicyTests(unittest.TestCase):
    def test_resource_exhausted_uses_long_backoff_policy(self) -> None:
        err = _FakeStatusError(429, "RESOURCE_EXHAUSTED")

        with patch.dict(
            os.environ,
            {
                "GEMINI_MULTI_AGENT_429_BACKOFF_INITIAL_S": "7",
                "GEMINI_MULTI_AGENT_429_BACKOFF_MAX_S": "30",
            },
            clear=True,
        ):
            self.assertEqual(multi_agent_agents._retry_wait_seconds(1, err), 7.0)
            self.assertEqual(multi_agent_agents._retry_wait_seconds(3, err), 28.0)
            self.assertEqual(multi_agent_agents._retry_wait_seconds(5, err), 30.0)

    def test_non_quota_retry_keeps_short_backoff_policy(self) -> None:
        err = _FakeStatusError(503, "UNAVAILABLE")

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(multi_agent_agents._retry_wait_seconds(1, err), 2.0)
            self.assertEqual(multi_agent_agents._retry_wait_seconds(6, err), 10.0)


if __name__ == "__main__":
    unittest.main()
