#!/usr/bin/env python3

import psycopg2 as pg
import sys, os, time, itertools

DB_NAME = 'clang_triage'
POPULATE_FROM = '/home/sliedes/scratch/afl/cases.minimized'

_CREATE_TABLES_SQL = '''
CREATE TABLE cases (
    id BIGSERIAL PRIMARY KEY,
    sha1 TEXT UNIQUE NOT NULL);

CREATE TABLE case_contents (
    case_id BIGINT PRIMARY KEY,
    contents BYTEA NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id));

CREATE TABLE case_sizes (
    case_id BIGINT PRIMARY KEY,
    size INTEGER NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id));
CREATE INDEX case_sizes_size ON case_sizes(size);

CREATE TABLE test_runs (
    id BIGSERIAL PRIMARY KEY,
    start_time BIGINT NOT NULL,
    end_time BIGINT,
    versions TEXT NOT NULL);
CREATE INDEX test_runs_start_time ON test_runs(start_time);
CREATE INDEX test_runs_versions ON test_runs(versions);

CREATE TABLE result_strings (
    id BIGSERIAL PRIMARY KEY,
    str TEXT UNIQUE NOT NULL);

CREATE TABLE results (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    test_run BIGINT NOT NULL,
    result BIGINT NOT NULL,
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
        self.conn = pg.connect('dbname=' + DB_NAME)

    def createSchema(self):
        c = self.conn.cursor()
        with self.conn:
            c.execute(_CREATE_TABLES_SQL)

    def doesCaseExist(self, sha):
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM cases WHERE sha1=%s', sha)
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
        cursor.executemany('INSERT INTO cases (sha1) VALUES (%s)',
                           ((x,) for x in casenames))

    def _addCaseContents(self, cursor, cases):
        cursor.executemany(
            'INSERT INTO case_contents (case_id, contents) ' +
            '    SELECT id, %s ' +
            '    FROM cases ' +
            '    WHERE sha1=%s',
            ((x[1], x[0]) for x in cases))
        cursor.execute(
            'INSERT INTO case_sizes (case_id, size) '  +
            '    SELECT case_id, length(contents) ' +
            '    FROM case_contents')

    def populateCases(self, cases_path):
        case_files = os.listdir(cases_path)
        case_names = [sha for sha, cpp in [x.split('.') for x in case_files]]
        #print('Adding names...')
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

    def _addTestRun(self, versions, start_time, end_time, results):
        'Returns id of test run that can be passed to _testRunFinished().'
        c = self.conn.cursor()
        with self.conn:
            c.execute('INSERT INTO test_runs (start_time, end_time, versions) ' +
                      'VALUES (%s, %s, %s) RETURNING id',
                      (start_time, end_time, versions))
            run_id = c.fetchone()[0]
            self._addResults(run_id, results)

    #def _testRunFinished(self, run_id):
    #    c = self.conn.cursor()
    #    with self.conn:
    #        c.execute('UPDATE test_runs SET end_time = %s ' +
    #                  'WHERE id = %s', (int(time.time()), run_id))

    def testRun(self, versions):
        'A context manager for test runs.'
        return TriageDb.TestRunContext(self, versions)

    def _addResults(self, run_id, results):
        'results: [(sha, result_string)]'
        c = self.conn.cursor()
        # insert result strings if they do not already exist
        unique_results = set(x[1] for x in results)
        c.executemany('INSERT INTO result_strings (str) SELECT %s ' +
                      'WHERE NOT EXISTS ( ' +
                      '    SELECT 1 from result_strings WHERE str=%s)',
                      ((x,x) for x in unique_results))
        c.executemany('INSERT INTO results (case_id, test_run, result) ' +
                      '    (SELECT cases.id, %s, result_strings.id ' +
                      '     FROM cases, result_strings ' +
                      '     WHERE cases.sha1=%s AND str=%s)',
                      [(run_id, x[0], x[1]) for x in results])

    def getLastRunTimeByVersions(self, versions):
        '''Returns (start_time, end_time) of the last test run with this version.
           If no test has been run with this version, returns None.
           If a test run has been started but not finished, returns (start_time, None).'''
        c = self.conn.cursor()
        c.execute('SELECT start_time, end_time ' +
                  'FROM test_runs ' +
                  'WHERE versions=%s ' +
                  'ORDER BY start_time ' +
                  'LIMIT 1', (versions, ))
        res = c.fetchone()
        return res

    class TestRunContext(object):
        def __init__(self, db, versions):
            self.db = db
            self.versions = versions
            self.results = []

        def __enter__(self):
            self.start_time = int(time.time())
            return self

        def __exit__(self, type, value, traceback):
            self.db._addTestRun(self.versions, self.start_time,
                                int(time.time()), self.results)

        def addResult(self, sha, result_string):
            self.results.append((sha, result_string))

def test(db):
    for name, contents in db.iterateCases():
        print((name, len(contents)))

def main():
    db = TriageDb()
    #db.createSchema()
    #db.populateCases(POPULATE_FROM)

    test(db)


if __name__ == '__main__':
    main()
