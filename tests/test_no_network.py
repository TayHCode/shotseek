import socket
import sys
import unittest
from tests import support


class Network(unittest.TestCase):
    def test_guard(self):
        self.assertIs(socket.socket.connect, support.denied)
        with self.assertRaises(AssertionError):
            socket.create_connection(("127.0.0.1", 9))

    def test_lazy(self):
        __import__("shotseek.cli")
        self.assertFalse({"torch", "open_clip", "faster_whisper"} & set(sys.modules))
