import asyncio
import os
import sys
import unittest

# Ensure backend root is in Python module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.exceptions import ProviderAuthError, ProviderRateLimitError
from app.core.retry import retry_with_backoff


class TestRetryWithBackoff(unittest.IsolatedAsyncioTestCase):
    """Test suite for retry_with_backoff decorator."""

    async def test_successful_call_no_retry(self):
        calls = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, timeout_seconds=1.0)
        async def mock_success():
            nonlocal calls
            calls += 1
            return "success_val"

        result = await mock_success()
        self.assertEqual(result, "success_val")
        self.assertEqual(calls, 1)

    async def test_transient_failure_then_success(self):
        calls = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, timeout_seconds=1.0)
        async def mock_flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ProviderRateLimitError("Rate limit exceeded")
            return "recovered"

        result = await mock_flaky()
        self.assertEqual(result, "recovered")
        self.assertEqual(calls, 3)

    async def test_non_retryable_auth_error_fails_immediately(self):
        calls = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01, timeout_seconds=1.0)
        async def mock_auth_fail():
            nonlocal calls
            calls += 1
            raise ProviderAuthError("Invalid API Key")

        with self.assertRaises(ProviderAuthError):
            await mock_auth_fail()

        # Must not retry after non-retryable auth error
        self.assertEqual(calls, 1)

    async def test_timeout_triggers_retry(self):
        calls = 0

        @retry_with_backoff(max_retries=2, base_delay=0.01, timeout_seconds=0.05)
        async def mock_slow():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.1) # Exceeds 0.05s timeout
            return "done"

        with self.assertRaises(asyncio.TimeoutError):
            await mock_slow()

        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
