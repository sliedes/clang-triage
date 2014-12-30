#!/usr/bin/env python3

import psycopg2 as pg
import os
import time
import zlib
import sys
from enum import Enum

from config import DB_NAME, POPULATE_FROM


class CReduceResult(Enum):
    # these need not correspond with postgres's internal enum values
    ok = 1
    failed = 2
    no_crash = 3
    dumb = 4


def readFile(path):
    with open(path, 'rb') as f:
        return f.read()


class TriageDb(object):
    def __init__(self):
        self.conn = pg.connect(database=DB_NAME)
        with self.conn:
            with self.conn.cursor() as c:
                c.execute("SELECT id FROM result_strings " +
                          "WHERE str='OK'")
                self.OK_ID = c.fetchone()[0]

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
                    c.executemany(
                        'INSERT INTO case_view (sha1, z_contents, size) ' +
                        'VALUES (?, ?, ?)',
                        (sha, zlib.compress(contents), len(contents)))

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
                      'FROM case_view AS cc, case_sizes ' +
                      'WHERE case_sizes.case_id = cc.id ' +
                      'ORDER BY case_sizes.size')
            return ((x[0], zlib.decompress(x[1])) for x in c)

    def iterateDistinctReduced(self):
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT DISTINCT contents FROM creduced_contents')
            return (x[0] for x in c)

    def iterateOutputs(self):
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT output FROM outputs')
            return (zlib.decompress(x[0]) for x in c)

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
        if result == CReduceResult.ok or result == CReduceResult.dumb:
            assert contents, 'Result OK or dumb but no contents?'
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
