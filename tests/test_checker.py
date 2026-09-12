from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from iptv_checker.checker import PlaylistChecker
from iptv_checker.playlist import Channel


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status = 200 if self.path == "/online" else 404
        self.send_response(status)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class PlaylistCheckerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_checks_available_and_missing_channels_in_order(self) -> None:
        base = f"http://127.0.0.1:{self.server.server_port}"
        channels = [Channel("Online", f"{base}/online"), Channel("Offline", f"{base}/missing")]

        results = PlaylistChecker(timeout=1, workers=2).check_all(channels)

        self.assertEqual([result.channel.name for result in results], ["Online", "Offline"])
        self.assertTrue(results[0].available)
        self.assertEqual(results[0].status, 200)
        self.assertFalse(results[1].available)
        self.assertEqual(results[1].status, 404)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaises(ValueError):
            PlaylistChecker(timeout=0)
        with self.assertRaises(ValueError):
            PlaylistChecker(workers=0)


if __name__ == "__main__":
    unittest.main()
