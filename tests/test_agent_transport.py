import os
import unittest
from unittest.mock import patch

from collector import agent_loop, collect


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

    def test_metric_collection_error_does_not_stop_next_cycle(self):
        with patch.object(agent_loop, "agent_payload", side_effect=[RuntimeError("metrics failed"), {"report_id": "new"}]), \
             patch.object(agent_loop, "send_report", return_value={}):
            self.assertEqual(agent_loop.run_once(), (None, 0))
            self.assertEqual(agent_loop.run_once(), (None, 0))

    def test_abandoned_retry_uses_new_report_id_for_new_sample(self):
        old = {"report_id": "old"}
        fresh = {"report_id": "fresh"}
        with patch.object(agent_loop, "send_report", side_effect=OSError("down")):
            self.assertEqual(agent_loop.run_once(old, agent_loop.MAX_RETRIES - 1), (None, 0))
        with patch.object(agent_loop, "agent_payload", return_value=fresh), patch.object(agent_loop, "send_report", return_value={}):
            agent_loop.run_once()
        self.assertNotEqual(old["report_id"], fresh["report_id"])

    def test_inactive_docker_is_a_metric_value(self):
        with patch("collector.collect.subprocess.run") as run:
            run.return_value.stdout = "inactive\n"
            self.assertEqual(collect.service_state("docker"), "inactive")
