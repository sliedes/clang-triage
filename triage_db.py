#!/usr/bin/env python3

import sqlite3 as sq
import sys, os

DB_NAME = 'triage_db.db'

#CREATE TABLE case_names (
#    case_id INTEGER PRIMARY KEY NOT NULL,
#    name TEXT NOT NULL,
#    FOREIGN KEY(case_id) REFERENCES cases(ROWID));
#CREATE INDEX case_names_name ON case_names(name);

_CREATE_TABLES_SQL = '''
CREATE TABLE cases (id INTEGER PRIMARY KEY, sha1 TEXT UNIQUE NOT NULL);

CREATE TABLE case_contents (
    case_id INTEGER PRIMARY KEY,
    contents BLOB NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id));

CREATE TABLE case_sizes (
    case_id INTEGER PRIMARY KEY,
    size INTEGER NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id));
CREATE INDEX case_sizes_size ON case_sizes(size);

CREATE TABLE test_runs (
    id INTEGER PRIMARY KEY,
    start_time INTEGER NOT NULL,
    end_time INTEGER, versions TEXT NOT NULL);
CREATE INDEX test_runs_start_time ON test_runs(start_time);

CREATE TABLE result_strings (
    id INTEGER PRIMARY KEY,
    str TEXT UNIQUE NOT NULL);

CREATE TABLE results (
    id INTEGER PRIMARY KEY,
    case_id TEXT NOT NULL,
    test_run INTEGER NOT NULL,
    result INTEGER NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id),
    FOREIGN KEY(test_run) REFERENCES test_runs(id),
    FOREIGN KEY(result) REFERENCES result_strings(str));
CREATE INDEX results_case_id ON results(case_id);
CREATE INDEX results_test_run ON results(test_run);
CREATE INDEX results_result ON results(result);
'''.strip()

def readFile(path):
    with open(path, 'rb') as f:
        return f.read()

class TriageDb(object):
    def __init__(self):
        self.conn = sq.connect('file:{}?mode=rw'.format(DB_NAME), uri=True)
        with self.conn:
            self.conn.execute('PRAGMA foreign_keys = ON')

    @staticmethod
    def create():
        conn = sq.connect('file:{}?mode=rwc'.format(DB_NAME), uri=True)
        with conn:
            conn.executescript(_CREATE_TABLES_SQL)

    def doesCaseExist(self, sha):
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM cases WHERE sha1=?', (sha,))
        res = c.fetchone()
        return bool(res[0])

    def addCase(self, sha, contents):
        self.addCases([(sha, contents)])

    # FIXME this may be slow?
    def addCases(self, cases):
        'cases: iterator of (sha, contents)'
        with self.conn:
            c = self.conn.cursor()
            for sha, contents in cases:
                self._addCaseNames(c, [sha])
                self._addCaseContents(c, [(sha, contents)])

    def _addCaseNames(self, cursor, casenames):
        cursor.executemany('INSERT INTO cases (sha1) VALUES (?)',
                           ((x,) for x in casenames))

    def _addCaseContents(self, cursor, cases):
        cursor.executemany(
            'INSERT INTO case_contents (case_id, contents) ' +
            '    SELECT id, ? ' +
            '    FROM cases ' +
            '    WHERE sha1=?',
            ((x[1], x[0]) for x in cases))
        cursor.execute(
            'INSERT INTO case_sizes (case_id, size) '  +
            '    SELECT case_id, length(contents) ' +
            '    FROM case_contents')

    def populateCases(self, cases_path):
        case_files = os.listdir(cases_path)
        case_names = [sha for sha, cpp in [x.split('.') for x in case_files]]
        print('Adding names...')
        with self.conn:
            c = self.conn.cursor()
            self._addCaseNames(c, case_names)

            # FIXME calculate sha1
            self._addCaseContents(c,
                                  ((sha, readFile(os.path.join(cases_path, fname)))
                                   for sha, fname in zip(case_names, case_files)))

    def iterateCases(self):
        'Iterate through (sha1, contents) pairs.'
        c = self.conn.cursor()
        c.execute('SELECT cases.sha1, case_contents.contents ' +
                  'FROM cases, case_contents, case_sizes '
                  'WHERE case_contents.case_id = cases.id ' +
                  '      AND case_sizes.case_id = cases.id ' +
                  'ORDER BY case_sizes.size')
        return c


def main():
    new = False
    if not os.path.exists(DB_NAME):
        print(DB_NAME + ' does not exist; creating...')
        TriageDb.create()
        new = True

    db = TriageDb()

    if new:
        db.populateCases('cases.minimized')

    for name, contents in db.iterateCases():
        print((name, len(contents)))


if __name__ == '__main__':
    main()
