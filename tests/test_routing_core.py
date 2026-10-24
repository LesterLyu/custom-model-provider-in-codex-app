from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from codex_provider_routing.routing import Router


class DatabaseLifetime(unittest.TestCase):
    def check_connections_closed(self, create_table):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with closing(sqlite3.connect(home / 'state_5.sqlite')) as db:
                if create_table:
                    db.execute('CREATE TABLE threads (id TEXT PRIMARY KEY, model TEXT)')
                    db.execute('INSERT INTO threads VALUES (?, ?)', ('test-thread', 'sample'))
                    db.commit()
            connections = []
            real_connect = sqlite3.connect

            def track(*args, **kwargs):
                connection = real_connect(*args, **kwargs)
                connections.append(connection)
                return connection

            with patch('codex_provider_routing.routing.sqlite3.connect', side_effect=track):
                result = Router(home, {'sample': 'local'}).saved_model('test-thread')
            self.assertEqual(result, 'sample' if create_table else None)
            self.assertEqual(len(connections), 1)
            for connection in connections:
                try:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connection.execute('SELECT 1')
                finally:
                    connection.close()

    def test_successful_lookup_closes_database(self):
        self.check_connections_closed(True)

    def test_failed_query_closes_database(self):
        self.check_connections_closed(False)
