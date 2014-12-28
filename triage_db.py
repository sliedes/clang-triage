#!/usr/bin/env python3

import psycopg2 as pg
import os
import time
import zlib
import sys
from enum import Enum

from config import DB_NAME, POPULATE_FROM


class CReduceResult(Enum):
    ok = 1
    failed = 2
    no_crash = 3

_CREATE_TABLES_SQL = '''
CREATE TABLE cases (
    id BIGSERIAL PRIMARY KEY,
    sha1 TEXT UNIQUE NOT NULL);

CREATE TABLE case_contents (
    case_id BIGINT PRIMARY KEY REFERENCES cases(id) ON UPDATE CASCADE,
    z_contents BYTEA NOT NULL);

CREATE TYPE creduce_result AS ENUM ('ok', 'failed', 'no_crash');

CREATE TABLE creduced_cases (
    id BIGSERIAL PRIMARY KEY,
    original BIGINT NOT NULL REFERENCES cases(id) ON UPDATE CASCADE,
    clang_version INTEGER NOT NULL,
    llvm_version INTEGER NOT NULL,
    result creduce_result NOT NULL);
CREATE UNIQUE INDEX creduced_cases_original_versions_unique
ON creduced_cases (original, clang_version, llvm_version);

CREATE TABLE creduced_contents (
    creduced_id BIGINT NOT NULL
        REFERENCES creduced_cases(id) ON UPDATE CASCADE ON DELETE CASCADE,
    contents BYTEA NOT NULL);

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
CREATE UNIQUE INDEX test_runs_versions
    ON test_runs(clang_version, llvm_version);

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
    FOREIGN KEY(result) REFERENCES result_strings(id) ON UPDATE CASCADE);
CREATE INDEX results_case_id ON results(case_id);
CREATE INDEX results_test_run ON results(test_run);
CREATE INDEX results_result ON results(result);
CREATE UNIQUE INDEX results_case_id_test_run ON results(case_id, test_run);

CREATE VIEW case_view AS
    SELECT id, sha1, z_contents
    FROM cases, case_contents
    WHERE cases.id = case_contents.case_id;

CREATE VIEW unreduced_cases_view AS
    SELECT sha1, z_contents
    FROM case_view AS cv
    WHERE NOT EXISTS (
        SELECT * FROM creduced_cases AS red
        WHERE red.original = cv.id);

CREATE VIEW failures_view AS
    SELECT test_run, cases.id, sha1, str
    FROM result_strings AS res, results, cases
    WHERE results.case_id = cases.id
        AND results.result = res.id;

CREATE VIEW failures_with_reduced_view AS
    SELECT test_run, id, sha1, str, cr.contents AS reduced
    FROM failures_view LEFT OUTER JOIN (
        SELECT DISTINCT ON (original) original, con.contents
        FROM creduced_cases AS cas, creduced_contents AS con
        WHERE con.creduced_id = cas.id) AS cr
    ON (cr.original = id), case_contents
    WHERE id = case_contents.case_id;

CREATE VIEW last_2_runs_view AS
    SELECT id FROM test_runs
    ORDER BY id DESC LIMIT 2;

CREATE VIEW last_run_results AS
    SELECT * FROM results
    WHERE test_run=(SELECT MAX(id) FROM last_2_runs_view);

CREATE VIEW second_last_run_results AS
    SELECT * FROM results
    WHERE test_run=(SELECT MIN(id) FROM last_2_runs_view);

CREATE VIEW changed_results AS
    SELECT last.id AS id1, second.id AS id2, last.case_id,
        last.result AS new, second.result AS old
    FROM last_run_results AS last, second_last_run_results AS second
    WHERE last.case_id=second.case_id AND last.result<>second.result;

CREATE TABLE outputs (
   case_id BIGINT UNIQUE REFERENCES cases(id)
       ON UPDATE CASCADE ON DELETE CASCADE,
   output BYTEA NOT NULL);
'''.strip()


def readFile(path):
    with open(path, 'rb') as f:
        return f.read()


class TriageDb(object):
    def __init__(self):
        self.conn = pg.connect('dbname=' + DB_NAME)
        with self.conn:
            with self.conn.cursor() as c:
                c.execute("SELECT id FROM result_strings " +
                          "WHERE str='OK'")
                self.OK_ID = c.fetchone()[0]

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
            'INSERT INTO case_contents (case_id, z_contents) ' +
            '    (SELECT id, %s ' +
            '     FROM cases ' +
            '     WHERE sha1=%s AND NOT EXISTS (' +
            '         SELECT 1 FROM case_contents WHERE case_id=id))',
            ((zlib.compress(x[1]), x[0]) for x in cases))
        cursor.executemany(
            'INSERT INTO case_sizes (case_id, size) ' +
            '    (SELECT id, %s ' +
            '     FROM cases WHERE sha1=%s AND NOT EXISTS (' +
            '         SELECT 1 FROM case_sizes ' +
            '         WHERE case_sizes.case_id=id))',
            ((len(x[1]), x[0]) for x in cases))

    def populateCases(self, cases_path):
        case_files = os.listdir(cases_path)
        case_names = [sha for sha, cpp in [x.split('.') for x in case_files]]
        #print('Adding names...')
        with self.conn:
            with self.conn.cursor() as c:
                self._addCaseNames(c, case_names)

                # FIXME calculate sha1
                self._addCaseContents(
                    c, ((sha, readFile(os.path.join(cases_path, fname)))
                        for sha, fname in zip(case_names, case_files)))

    def iterateCases(self):
        'Iterate through (sha1, contents) pairs.'
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT cc.sha1, cc.z_contents ' +
                      'FROM case_view AS cc, case_sizes '
                      'WHERE case_sizes.case_id = cc.id ' +
                      'ORDER BY case_sizes.size')
            return ((x[0], zlib.decompress(x[1])) for x in c)

    def iterateDistinctReduced(self):
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT DISTINCT contents FROM creduced_contents')
            return (x[0] for x in c)

    def getNumberOfCases(self):
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT count(*) from case_contents')
                return c.fetchone()[0]

    def _addTestRun(self, versions, start_time, end_time, results):
        '''results: [(sha, result_string, output)].
        Output may be None if result_string="OK".'''
        assert 'clang' in versions, versions
        assert 'llvm' in versions, versions
        clang_version = versions['clang']
        llvm_version = versions['llvm']
        with self.conn:
            with self.conn.cursor() as c:
                c.execute(
                    'INSERT INTO test_runs (start_time, end_time, ' +
                    '    clang_version, llvm_version) ' +
                    'VALUES (%s, %s, %s, %s) RETURNING id',
                    (start_time, end_time, clang_version, llvm_version))
                run_id = c.fetchone()[0]
                self._addResults(c, run_id, results)
                # delete changed creduce results where new result != OK
                c.execute("DELETE FROM creduced_cases WHERE original IN (" +
                          "    SELECT case_id FROM changed_results " +
                          "    WHERE new<>%s)",
                          (self.OK_ID, ))

    def testRun(self, versions):
        'A context manager for test runs.'
        return TriageDb.TestRunContext(self, versions)

    def _addResults(self, cursor, run_id, results):
        '''results: [(sha, result_string, output)].
        Output may be None if result_string="OK".'''
        c = cursor
        # insert result strings if they do not already exist
        unique_results = set(x[1] for x in results)
        c.executemany('INSERT INTO result_strings (str) SELECT %s ' +
                      'WHERE NOT EXISTS ( ' +
                      '    SELECT 1 from result_strings WHERE str=%s)',
                      ((x, x) for x in unique_results))
        c.executemany('INSERT INTO results (case_id, test_run, result) ' +
                      '    (SELECT cases.id, %s, result_strings.id ' +
                      '     FROM cases, result_strings ' +
                      '     WHERE cases.sha1=%s AND str=%s)',
                      [(run_id, x[0], x[1]) for x in results])
        # insert/replace outputs
        outputs = [(x[0], x[2]) for x in results if x[1] != 'OK']

        c.executemany('DELETE FROM outputs ' +
                      'WHERE case_id=(SELECT id FROM cases WHERE sha1=%s)',
                      ((x[0],) for x in outputs))
        c.executemany('INSERT INTO outputs ' +
                      'SELECT id, %s FROM cases WHERE sha1=%s',
                      [(zlib.compress(x[1]), x[0]) for x in outputs])

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

    def getCReduceWork(self):
        'Get (sha, content) pair to run through creduce. None if none.'
        with self.conn:
            with self.conn.cursor() as c:
                c.execute(
                    'SELECT sha1, z_contents FROM unreduced_cases_view ' +
                    'ORDER BY sha1 LIMIT 1')
                r = c.fetchone()
        if r is None:
            return None
        return (r[0], zlib.decompress(r[1]))

    def addCReduced(self, versions, sha, result, contents=None):
        if result == CReduceResult.ok:
            assert contents, 'Result OK but no contents?'
        else:
            assert (result == CReduceResult.failed or
                    result == CReduceResult.no_crash), result
            assert contents is None
        llvm_version = versions['llvm']
        clang_version = versions['clang']
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT id FROM cases WHERE sha1=%s', (sha, ))
                case_id = c.fetchone()
                assert case_id, sha
                case_id = case_id[0]
                c.execute('INSERT INTO creduced_cases (original, ' +
                          '    clang_version, llvm_version, result) ' +
                          'VALUES (%s, %s, %s, %s) RETURNING id', (
                              case_id, clang_version, llvm_version,
                              result.name))
                cr_id = c.fetchone()[0]
                if not contents is None:
                    c.execute('INSERT INTO creduced_contents ' +
                              '    (creduced_id, contents) ' +
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

        def addResult(self, sha, result_string, output):
            'Output will be ignored if result_string="OK".'
            self.results.append((sha, result_string, output))


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
