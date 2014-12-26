#!/usr/bin/env python3

import psycopg2 as pg
import sys, os, time, itertools

from config import DB_NAME, POPULATE_FROM

_CREATE_TABLES_SQL = '''
CREATE TABLE cases (
    id BIGSERIAL PRIMARY KEY,
    sha1 TEXT UNIQUE NOT NULL);

CREATE TABLE case_contents (
    case_id BIGINT PRIMARY KEY REFERENCES cases(id) ON UPDATE CASCADE,
    contents BYTEA NOT NULL);

CREATE TABLE creduced_contents (
    creduced_id BIGINT NOT NULL REFERENCES creduced_cases(id) ON UPDATE CASCADE,
    contents BYTEA NOT NULL);

CREATE TABLE creduced_cases (
    id BIGSERIAL PRIMARY KEY,
    original BIGINT NOT NULL REFERENCES cases(id) ON UPDATE CASCADE,
    clang_version INTEGER NOT NULL,
    llvm_version INTEGER NOT NULL);
CREATE UNIQUE INDEX creduced_cases_original_versions_unique ON creduced_cases (original, clang_version, llvm_version);

CREATE TABLE creduce_requests (
    case_id BIGINT PRIMARY KEY REFERENCES case_contents(case_id) ON UPDATE CASCADE);

CREATE TABLE case_sizes (
    case_id BIGINT PRIMARY KEY,
    size INTEGER NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON UPDATE CASCADE);
CREATE INDEX case_sizes_size ON case_sizes(size);

CREATE TABLE test_runs (
    id BIGSERIAL PRIMARY KEY,
    start_time BIGINT NOT NULL,
    end_time BIGINT NOT NULL,
    clang_version INTEGER NOT NULL,
    llvm_version INTEGER NOT NULL);
CREATE INDEX test_runs_start_time ON test_runs(start_time);
CREATE UNIQUE INDEX test_runs_versions ON test_runs(clang_version, llvm_version);

CREATE TABLE result_strings (
    id BIGSERIAL PRIMARY KEY,
    str TEXT UNIQUE NOT NULL);

CREATE TABLE results (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    test_run BIGINT NOT NULL,
    result BIGINT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON UPDATE CASCADE,
    FOREIGN KEY(test_run) REFERENCES test_runs(id) ON UPDATE CASCADE,
    FOREIGN KEY(result) REFERENCES result_strings(id)) ON UPDATE CASCADE;
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
        with self.conn:
            with self.conn.cursor() as c:
                c.execute(_CREATE_TABLES_SQL)

    def doesCaseExist(self, sha):
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT COUNT(*) FROM cases WHERE sha1=%s', sha)
                return bool(c.fetchone()[0])

    def addCase(self, sha, contents):
        self.addCases([(sha, contents)])

    # FIXME this may be slow?
    def addCases(self, cases):
        'cases: iterator of (sha, contents)'
        with self.conn:
            with self.conn.cursor() as c:
                for sha, contents in cases:
                    self._addCaseNames(c, [sha])
                    self._addCaseContents(c, [(sha, contents)])

    def _addCaseNames(self, cursor, casenames):
        cursor.executemany('INSERT INTO cases (sha1) '
                           'SELECT %s WHERE NOT EXISTS (' +
                           '    SELECT 1 FROM cases WHERE sha1=%s)',
                           ((x, x) for x in casenames))

    def _addCaseContents(self, cursor, cases):
        cursor.executemany(
            'INSERT INTO case_contents (case_id, contents) ' +
            '    (SELECT id, %s ' +
            '     FROM cases ' +
            '     WHERE sha1=%s AND NOT EXISTS (' +
            '         SELECT 1 FROM case_contents WHERE case_id=id))',
            ((x[1], x[0]) for x in cases))
        cursor.execute(
            'INSERT INTO case_sizes (case_id, size) '  +
            '    (SELECT case_id, length(contents) ' +
            '     FROM case_contents WHERE NOT EXISTS (' +
            '         SELECT 1 FROM case_sizes ' +
            '         WHERE case_sizes.case_id=case_contents.case_id))')

    def populateCases(self, cases_path):
        case_files = os.listdir(cases_path)
        case_names = [sha for sha, cpp in [x.split('.') for x in case_files]]
        #print('Adding names...')
        with self.conn:
            with self.conn.cursor() as c:
                self._addCaseNames(c, case_names)

                # FIXME calculate sha1
                self._addCaseContents(c,
                                      ((sha, readFile(os.path.join(cases_path, fname)))
                                       for sha, fname in zip(case_names, case_files)))

    def iterateCases(self):
        'Iterate through (sha1, contents) pairs.'
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT cases.sha1, case_contents.contents ' +
                      'FROM cases, case_contents, case_sizes '
                      'WHERE case_contents.case_id = cases.id ' +
                      '      AND case_sizes.case_id = cases.id ' +
                      'ORDER BY case_sizes.size')
            return c

    def iterateDistinctReduced(self):
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT DISTINCT contents FROM creduced_contents')
            return (x[0] for x in c)

    def getNumberOfCases(self):
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT count(*) from cases')
                return c.fetchone()[0]

    def _addTestRun(self, versions, start_time, end_time, results):
        'Returns id of test run that can be passed to _testRunFinished().'
        assert 'clang' in versions, versions
        assert 'llvm' in versions, versions
        clang_version = versions['clang']
        llvm_version = versions['llvm']
        with self.conn:
            with self.conn.cursor() as c:
                c.execute(
                    'INSERT INTO test_runs ' +
                    '    (start_time, end_time, clang_version, llvm_version) ' +
                    'VALUES (%s, %s, %s, %s) RETURNING id',
                    (start_time, end_time, clang_version, llvm_version))
                run_id = c.fetchone()[0]
                self._addResults(c, run_id, results)

    def testRun(self, versions):
        'A context manager for test runs.'
        return TriageDb.TestRunContext(self, versions)

    def _addResults(self, cursor, run_id, results):
        'results: [(sha, result_string)]'
        c = cursor
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
        '''Returns (start_time, end_time) of the test run with these versions.
           If no test has been run with this version, returns None.'''
        assert 'clang' in versions, versions
        assert 'llvm' in versions, versions
        clang_version = versions['clang']
        llvm_version = versions['llvm']
        with self.conn:
            with self.conn.cursor() as c:
                # Currently there can (by design) be only one run, hence
                # the ORDER_BY and LIMIT are redundant.
                c.execute('SELECT start_time, end_time ' +
                          'FROM test_runs ' +
                          'WHERE clang_version=%s AND llvm_version=%s ' +
                          'ORDER BY start_time ' +
                          'LIMIT 1', (clang_version, llvm_version))
                return c.fetchone()

    def requestCReduces(self, shas):
        with self.conn:
            with self.conn.cursor() as c:
                c.executemany(
                    'INSERT INTO creduce_requests (case_id) ' +
                    'SELECT id FROM cases WHERE sha=%s',
                    [(x,) for x in shas])

    def removeCReduceRequest(self, sha):
        self.removeCReduceRequests([sha])

    def removeCReduceRequests(self, shas):
        with self.conn:
            with self.conn.cursor() as c:
                c.executemany(
                    'DELETE FROM creduce_requests ' +
                    'WHERE case_id IN (SELECT id FROM cases WHERE sha1=%s)',
                    [(x,) for x in shas])

    def getCReduceWork(self):
        'Get (sha, content) pair to run through creduce. None if none.'
        with self.conn:
            with self.conn.cursor() as c:
                c.execute(
                    'SELECT cases.sha1, case_contents.contents ' +
                    'FROM creduce_requests, cases, case_contents ' +
                    'WHERE creduce_requests.case_id = cases.id ' +
                    '    AND cases.id = case_contents.case_id ' +
                    '    LIMIT 1')
                return c.fetchone()

    def addCReduced(self, versions, sha, contents=None):
        llvm_version = versions['llvm']
        clang_version = versions['clang']
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT id FROM cases WHERE sha1=%s', (sha, ))
                case_id = c.fetchone()
                assert case_id, sha
                case_id = case_id[0]
                c.execute('DELETE from creduce_requests ' +
                          'WHERE case_id=%s', (case_id, ))
                content_id = None
                c.execute('INSERT INTO creduced_cases (original, ' +
                          '    clang_version, llvm_version) ' +
                          'VALUES (%s, %s, %s) RETURNING id', (
                              case_id, clang_version, llvm_version))
                cr_id = c.fetchone()[0]
                if not contents is None:
                    c.execute('INSERT INTO creduced_contents (creduced_id, contents) ' +
                              'VALUES (%s, %s)', (cr_id, contents))

    class TestRunContext(object):
        def __init__(self, db, versions):
            self.db = db
            self.versions = versions
            self.results = []

        def __enter__(self):
            self.start_time = int(time.time())
            return self

        def __exit__(self, type, value, traceback):
            # We actually don't want to commit on an exception
            if not value:
                self.db._addTestRun(self.versions,
                                    self.start_time, int(time.time()),
                                    self.results)

        def addResult(self, sha, result_string):
            self.results.append((sha, result_string))

def test(db):
    for name, contents in db.iterateCases():
        print((name, len(contents)))

def main():
    db = TriageDb()
    #db.createSchema()
    db.populateCases(POPULATE_FROM)

    test(db)


if __name__ == '__main__':
    main()
