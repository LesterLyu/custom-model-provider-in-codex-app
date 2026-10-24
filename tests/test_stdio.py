import unittest

from windows.stdio_router import is_stdio_server


class Stdio(unittest.TestCase):
    def test_app_stdio_launch(self):
        for args in (['app-server'], ['-c', 'features.code_mode_host=true', 'app-server', '--analytics-default-enabled'],
                     ['app-server', '--listen', 'stdio://'], ['app-server', '--listen=stdio://']):
            self.assertTrue(is_stdio_server(args))

    def test_other_commands_are_delegated(self):
        for args in (['--version'], ['app-server', 'proxy'], ['app-server', 'daemon', 'status'],
                     ['app-server', 'generate-json-schema'], ['app-server', '--help'],
                     ['app-server', '--listen', 'unix://'], ['app-server', '--listen=ws://127.0.0.1:8000']):
            self.assertFalse(is_stdio_server(args))
