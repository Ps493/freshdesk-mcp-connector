import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fd_connector.client import FreshdeskClient
from fd_connector.tools import Toolset
from scripts.run_eval import run
from tests import mock_freshdesk as mock


class TestEvalRunner(unittest.TestCase):
    def test_eval_suite_passes_against_mock(self):
        srv, url = mock.start()
        try:
            ts = Toolset(FreshdeskClient("", mock.API_KEY, base_url=url, sleep=lambda s: None, calls_per_minute=600, burst=100))
            res = run(ts)
            fails = [r for r in res if r[2] == "FAIL"]
            self.assertEqual(fails, [])
            self.assertGreaterEqual(len([r for r in res if r[2] == "PASS"]), 9)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
