"""Import a recovered SQLite snapshot into an EMPTY PostgreSQL database.

Does not import app.py (no bootstrap side effects). Connection URL comes only
from the environment. Source is read-only; a consistent backup is saved first.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import psycopg
from psycopg import sql
from database import Postgres, TABLES, create_schema

def migrate(source, backup):
    source = Path(source).resolve()
    backup = Path(backup).resolve()
    if not source.is_file() or source == backup or backup.exists():
        raise ValueError('Source must exist; backup must be a new separate file.')
    original = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    snapshot = sqlite3.connect(backup)
    try:
        original.backup(snapshot)
        if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed.')
        snapshot.row_factory = sqlite3.Row
        target = Postgres(os.environ['DATABASE_URL'])
        try:
            create_schema(target)
            conn = target.connection
            for table in TABLES:
                if target.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
                    raise ValueError('Target is not empty. Import cancelled.')
            counts = {}
            for table in TABLES:
                present = snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if not present:
                    counts[table] = 0
                    continue
                rows = snapshot.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
                columns = [r['name'] for r in snapshot.execute(f'PRAGMA table_info({table})')]
                query = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                    sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                    sql.SQL(',').join(sql.Placeholder() for _ in columns))
                with conn.cursor() as cursor:
                    cursor.executemany(query, [tuple(row) for row in rows])
                actual = target.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
                if len(actual) != len(rows) or any(tuple(row[col] for col in columns) != tuple(src) for row, src in zip(actual, rows)):
                    raise ValueError('Verification failed. Import rolled back.')
                counts[table] = len(rows)
                target.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1), EXISTS(SELECT 1 FROM {table}))")
            if 'role' not in [r['name'] for r in snapshot.execute('PRAGMA table_info(users)')]:
                target.execute("UPDATE users SET role='admin' WHERE username='admin'")
            target.commit()
            return counts
        finally:
            target.close()
    finally:
        snapshot.close()
        original.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.source, args.backup)))
    except Exception:
        # Driver exceptions can contain hosts and connection details.
        print('Migration failed; target transaction rolled back. Check source, target and connection privately.')
        raise SystemExit(1)
