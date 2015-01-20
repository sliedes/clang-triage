# FIXME write a schema migration test.

import sys


def migrate_schema_v1_v2(db):
    # changes from 1 to 2:
    #   * CREATE TABLE params with schema_version row
    #   * compress test run ids, no longer use serial but max(id)+1
    with db.cursor() as c:
        print('Migrating schema v1..v2...', file=sys.stderr)
        c.execute('CREATE TABLE params ( '
                  '    name TEXT PRIMARY KEY, '
                  '    value TEXT)')
        c.execute("INSERT INTO params VALUES ('schema_version', '2')")
        c.execute('ALTER TABLE test_runs ALTER id DROP DEFAULT')
        c.execute('DROP SEQUENCE test_runs_id_seq')
    while True:
        with db.cursor() as c:
            c.execute('SELECT id FROM test_runs ORDER BY id')
            ids = [x[0] for x in c]
            maximum = ids[-1]
            new = 1
            updates = []
            for orig in ids:
                if orig != new:
                    updates.append((new, orig))
                new += 1
        if not updates:
            break
        remaining = len(updates)
        updates = updates[:10]
        print('  {} remaining...'.format(remaining), file=sys.stderr)
        with db.cursor() as c:
            c.executemany('UPDATE test_runs SET id=%s WHERE id=%s',
                          updates)


MIGRATE_FROM = {
    1: migrate_schema_v1_v2
}
