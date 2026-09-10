"""Diagnostic of direct file replacement only, NOT proof of safe SQLite fd reads.

Parent-directory replacement is a separate known Linux VFS failure mode. Runtime
vector transport uses private verified copies, never this /dev/fd approach.
Only private temporary files are created by this historical diagnostic.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import platform
import sqlite3
import tempfile


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def main():
    with tempfile.TemporaryDirectory(prefix='aic-sqlite-fd-') as directory:
        root = Path(directory)
        original, replacement = root / 'map.sqlite', root / 'replacement.sqlite'
        for path, value in ((original, 'verified'), (replacement, 'unverified')):
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('CREATE TABLE marker (value TEXT)')
                connection.execute('INSERT INTO marker VALUES (?)', (value,))
                connection.commit()
        fd = os.open(original, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            with closing(sqlite3.connect(f'file:/dev/fd/{fd}?mode=ro&immutable=1', uri=True)) as connection:
                assert connection.execute('SELECT value FROM marker').fetchone()[0] == 'verified'
            before = identity(os.fstat(fd))
            os.replace(replacement, original)
            try:
                with closing(sqlite3.connect(f'file:/dev/fd/{fd}?mode=ro&immutable=1', uri=True)) as connection:
                    value = connection.execute('SELECT value FROM marker').fetchone()[0]
                    database_path = connection.execute('PRAGMA database_list').fetchone()[2]
            except sqlite3.Error:
                value, database_path = 'read_rejected', None
            unchanged = identity(os.fstat(fd)) == before
            assert value in {'verified', 'read_rejected'} or not unchanged, 'unchecked replacement accepted'
            print(json.dumps({'platform': platform.system(), 'sqlite': sqlite3.sqlite_version,
                              'value': value, 'stamp_unchanged': unchanged,
                              'database_path': database_path,
                              'scope': 'direct_file_replacement_only',
                              'runtime_safety_verified': False}))
        finally:
            os.close(fd)


if __name__ == '__main__':
    main()
