import os
import unittest
from unittest.mock import patch

from collector import agent_loop


class AgentTransportTests(unittest.TestCase):
    def test_http_requires_explicit_opt_in_and_retry_reuses_payload(self):
        with patch.dict(os.environ, {"VAST_GUARDIAN_CENTRAL_URL": "http://lan/ingest", "VAST_GUARDIAN_INGEST_TOKEN": "secret"}, clear=False):
            with self.assertRaises(RuntimeError):
                agent_loop.send_report({})
        report = {"report_id": "same"}
        with patch.object(agent_loop, "send_report", side_effect=OSError("down")):
            pending, attempts = agent_loop.run_once(report, 0)
        self.assertIs(pending, report)
        self.assertEqual(attempts, 1)

    def test_https_request_uses_bearer_token_without_tls_override(self):
        with patch.dict(os.environ, {"VAST_GUARDIAN_CENTRAL_URL": "https://central/ingest", "VAST_GUARDIAN_INGEST_TOKEN": "secret"}, clear=False):
            with patch("collector.agent_loop.urllib.request.urlopen") as open_url:
                open_url.return_value.__enter__.return_value.status = 200
                open_url.return_value.__enter__.return_value.read.return_value = b"{}"
                agent_loop.send_report({"report_id": "x"})
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertNotIn("context", open_url.call_args.kwargs)
