import sys
import unittest
from unittest.mock import MagicMock, patch

import local_start


class LocalStartTests(unittest.TestCase):
    def test_starts_on_loopback_and_runs_scheduler(self):
        fake_app = MagicMock()
        fake_socket = MagicMock()
        with patch.dict(sys.modules, {"app": fake_app}), \
                patch("local_start.socket.socket", return_value=fake_socket), \
                patch("local_start.threading.Thread") as thread:
            self.assertEqual(local_start.main(), 0)
        fake_socket.__enter__.return_value.bind.assert_called_once_with(("127.0.0.1", 5000))
        fake_app.start_scheduler.assert_called_once_with()
        fake_app.app.run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
        thread.return_value.start.assert_called_once_with()

    def test_busy_port_does_not_start_server(self):
        fake_app = MagicMock()
        fake_socket = MagicMock()
        fake_socket.__enter__.return_value.bind.side_effect = OSError("busy")
        with patch.dict(sys.modules, {"app": fake_app}), \
                patch("local_start.socket.socket", return_value=fake_socket):
            self.assertEqual(local_start.main(), 1)
        fake_app.start_scheduler.assert_not_called()
        fake_app.app.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
