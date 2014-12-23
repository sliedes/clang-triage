#!/usr/bin/env python3

import sqlite3 as sq
import sys, os, time

DB_NAME = 'triage_db.db'
POPULATE_FROM = '/home/sliedes/scratch/afl/cases.minimized'

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
    end_time INTEGER,
    versions TEXT NOT NULL);
CREATE INDEX test_runs_start_time ON test_runs(start_time);
CREATE INDEX test_runs_versions ON test_runs(versions);

CREATE TABLE result_strings (
    id INTEGER PRIMARY KEY,
    str TEXT UNIQUE NOT NULL);

CREATE TABLE results (
    id INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL,
    test_run INTEGER NOT NULL,
    result INTEGER NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id),
    FOREIGN KEY(test_run) REFERENCES test_runs(id),
    FOREIGN KEY(result) REFERENCES result_strings(id));
CREATE INDEX results_case_id ON results(case_id);
CREATE INDEX results_test_run ON results(test_run);
CREATE INDEX results_result ON results(result);
CREATE UNIQUE INDEX results_case_id_test_run ON results(case_id, test_run);
'''.strip()

def readFile(path):
    with open(path, 'rb') as f:
        return f.read()

class TriageDb(object):
    def __init__(self):
        self.conn = sq.connect('file:{}?mode=rw'.format(DB_NAME), uri=True)
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
            self.conn.commit()

    def iterateCases(self):
        'Iterate through (sha1, contents) pairs.'
        c = self.conn.cursor()
        c.execute('SELECT cases.sha1, case_contents.contents ' +
                  'FROM cases, case_contents, case_sizes '
                  'WHERE case_contents.case_id = cases.id ' +
                  '      AND case_sizes.case_id = cases.id ' +
                  'ORDER BY case_sizes.size')
        return c

    def getNumberOfCases(self):
        c = self.conn.cursor()
        c.execute('SELECT count(*) from cases')
        return c.fetchone()[0]

    def _addTestRun(self, versions):
        'Returns id of test run that can be passed to _testRunFinished().'
        c = self.conn.cursor()
        with self.conn:
            c.execute('INSERT INTO test_runs (start_time, versions) ' +
                      'VALUES (?, ?)', (int(time.time()), versions))
        return c.lastrowid

    def _testRunFinished(self, run_id):
        c = self.conn.cursor()
        with self.conn:
            c.execute('UPDATE test_runs SET end_time = ? ' +
                      'WHERE id = ?', (int(time.time()), run_id))

    def testRun(self, versions):
        'A context manager for test runs.'
        return TriageDb.TestRunContext(self, versions)

    def _addResult(self, run_id, sha, result_string):
        c = self.conn.cursor()
        # first check if the result string is known
        c.execute('SELECT id FROM result_strings ' +
                  'WHERE str=?', (result_string, ))
        str_id = c.fetchone()
        if not str_id is None:
            str_id = str_id[0]
        with self.conn:
            if str_id is None:
                c.execute('INSERT INTO result_strings (str) VALUES (?)',
                          (result_string,))
                str_id = c.lastrowid
            #print('Result: run_id={}, sha={}, str_id={}'.format(
            #    run_id, sha, str_id))
            c.execute('INSERT INTO results (case_id, test_run, result) ' +
                      '    SELECT (SELECT id FROM cases WHERE sha1=?), '
                      '        ?, ?', (sha, run_id, str_id))

    def getLastRunTimeByVersion(self, versions):
        '''Returns (start_time, end_time) of the last test run with this version.
           If no test has been run with this version, returns None.
           If a test run has been started but not finished, returns (start_time, None).'''
        c = self.conn.cursor()
        c.execute('SELECT start_time, end_time ' +
                  'FROM test_runs ' +
                  'WHERE versions=? ' +
                  'ORDER BY start_time ' +
                  'LIMIT 1', (versions, ))
        res = c.fetchone()
        return res

    class TestRunContext(object):
        def __init__(self, db, versions):
            self.db = db
            self.versions = versions

        def __enter__(self):
            self.run_id = self.db._addTestRun(self.versions)
            return self

        def __exit__(self, type, value, traceback):
            self.db._testRunFinished(self.run_id)

        def addResult(self, sha, result_string):
            self.db._addResult(self.run_id, sha, result_string)


def test(db):
    for name, contents in db.iterateCases():
        print((name, len(contents)))

    #with db.testRun('version 1') as run:
    #    run.addResult('21b79d40b266c4f209d86247c031982e25891dc1', 'error')

def main():
    new = False
    if not os.path.exists(DB_NAME):
        print(DB_NAME + ' does not exist; creating...')
        TriageDb.create()
        new = True

    db = TriageDb()
    if new:
        db.populateCases(POPULATE_FROM)

    test(db)


if __name__ == '__main__':
    main()
