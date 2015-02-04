import psycopg2 as pg
import os
import time
import zlib
import hashlib
import itertools
import subprocess as subp
from enum import Enum
import sys

from utils import all_files_recursive
from config import DB_NAME, CREATE_SCHEMA_COMMAND
import schema_migration


SCHEMA_VERSION = 2


class ReduceResult(Enum):
    'A reduce result.'

    # these need not correspond with postgres's internal enum values
    ok = 1        # Reduced with creduce
    no_crash = 2  # Did not crash
    dumb = 3      # Creduce failed, reduced with dumb reducer


def read_file(path):
    'Read an entire file as binary.'

    with open(path, 'rb') as f:
        return f.read()


class DbNotInitialized(Exception):
    "Thrown by TriageDb() when the schema has not been created."
    pass


class TriageDb(object):
    'Triage database.'

    def __init__(self):
        self.conn = pg.connect(database=DB_NAME)
        with self.conn:
            with self.conn.cursor() as c:
                try:
                    c.execute("SELECT id FROM result_strings " +
                              "WHERE str='OK'")
                    self.OK_ID = c.fetchone()[0]
                except pg.ProgrammingError:
                    raise DbNotInitialized()
        with self.conn:
            version = self.__get_schema_version()
        if version > SCHEMA_VERSION:
            print('Error: Unexpectedly high schema version {} '
                  '(expected at most {})'.format(
                      version, SCHEMA_VERSION), file=sys.stderr)
            sys.exit(1)
        elif version < SCHEMA_VERSION:
            with self.conn:
                self.__migrate_schema(version)
            with self.conn:
                newver = self.__get_schema_version()
                assert newver == SCHEMA_VERSION, newver

    def __get_schema_version(self):
        with self.conn.cursor() as c:
            try:
                c.execute("SELECT value FROM params " +
                          "    WHERE name='schema_version'")
                return int(c.fetchone()[0])
            except pg.ProgrammingError:
                # version 1 did not have the params table
                return 1

    def __migrate_schema(self, version):
        assert version < SCHEMA_VERSION
        schema_migration.MIGRATE_FROM[version](self.conn)

    @staticmethod
    def createSchema():
        'Create the database schema.'
        print('Creating database schema...', file=sys.stderr)
        try:
            subp.check_call(CREATE_SCHEMA_COMMAND, stderr=subp.STDOUT)
        except subp.CalledProcessError as e:
            print('Schema creation failed.', file=sys.stderr)
            print('Output from psql:\n' + e.output, file=sys.stderr)
            raise

    def doesCaseExist(self, sha):
        'Check if a case exists in the database.'
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT COUNT(*) FROM cases WHERE sha1=%s', sha)
                return bool(c.fetchone()[0])

    def addCase(self, sha, contents):
        'Add a case. It must not aldeary exist.'
        self.addCases([(sha, contents)])

    # FIXME this may be slow?
    def addCases(self, cases):
        'Add several cases.'
        with self.conn:
            with self.conn.cursor() as c:
                c.executemany(
                    'INSERT INTO case_view (sha1, z_contents, size) ' +
                    'SELECT %s, %s, %s ' +
                    'WHERE NOT EXISTS (' +
                    '    SELECT sha1 FROM case_view WHERE sha1=%s)',
                    ((x[0], zlib.compress(x[1]), len(x[1]), x[0])
                     for x in cases))

    def populateCases(self, cases_path, stop_after=None):
        '''Add files from a directory, recursively, as cases. Filenames do not
        matter.'''
        case_files = all_files_recursive(cases_path)

        if stop_after:
            case_files = itertools.islice(case_files, 0, stop_after)

        def cases_iter():
            for fname in case_files:
                contents = read_file(os.path.join(cases_path, fname))
                sha = hashlib.sha1(contents).hexdigest()
                yield (sha, contents)

        self.addCases(cases_iter())

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
        'Iterate through distinct reduced cases.'
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT DISTINCT contents FROM reduced_contents')
            return (x[0] for x in c)

    def iterateDumbReduced(self):
        '''Iterate through distinct dumb-reduced cases. Returns a list
        of (original, reduced, reason).'''
        with self.conn:
            c = self.conn.cursor()
            # FIXME get the latest failures... and get rid of that
            # File not yet open hack.
            c.execute('''
                SELECT DISTINCT ON (contents) z_contents, contents, str
                FROM case_contents, reduced_contents, reduced_cases,
                    result_strings,
                    (SELECT DISTINCT case_id
                     FROM reduced_cases AS rc, results, result_strings
                     WHERE rc.result='dumb' AND original=case_id
                         AND results.result=result_strings.id
                         AND result_strings.str<>'OK'
                         AND result_strings.str LIKE '%File not yet open%')
                              AS ids
                WHERE case_contents.case_id=ids.case_id
                    AND reduced_contents.reduced_id=reduced_cases.id
                    AND reduced_cases.original=ids.case_id
                    AND str<>'OK'
                    AND str NOT LIKE '%File not yet open%'
                    AND str<>'Stack dump found' ''')
        return ((zlib.decompress(x[0]), x[1], x[2]) for x in c)

    def iterateOutputs(self):
        'Iterate through compiler outputs.'
        with self.conn:
            c = self.conn.cursor()
            c.execute('SELECT output FROM outputs')
            return (zlib.decompress(x[0]) for x in c)

    def getNumberOfCases(self):
        'Get the number of cases in the database.'
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT count(*) from case_contents')
                return c.fetchone()[0]

    def _addTestRun(self, versions, start_time, end_time, results):
        '''results: [(sha, result_string, output)].
        Output is ignored if result_string="OK".'''

        assert 'clang' in versions, versions
        assert 'llvm' in versions, versions
        clang_version = versions['clang']
        llvm_version = versions['llvm']
        with self.conn:
            with self.conn.cursor() as c:
                c.execute(
                    'INSERT INTO test_runs (id, start_time, end_time, '
                    '    clang_version, llvm_version) '
                    'SELECT MAX(id)+1, %s, %s, %s, %s FROM test_runs '
                    '    RETURNING id',
                    (start_time, end_time, clang_version, llvm_version))
                run_id = c.fetchone()[0]
                self._addResults(c, run_id, results)
                # delete changed reduce results where new result != OK
                c.execute("DELETE FROM reduced_cases WHERE original IN (" +
                          "    SELECT case_id FROM changed_results " +
                          "    WHERE new<>%s)",
                          (self.OK_ID, ))

    def testRun(self, versions):
        'Get a context manager for test runs.'
        return TriageDb.TestRunContext(self, versions)

    def _addResults(self, cursor, run_id, results):
        '''results: [(sha, result_string, output)].
        Output is ignored if result_string="OK".'''

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

    def getReduceWork(self):
        'Get a (sha, content) pair to run through reduce. None if none.'

        with self.conn:
            with self.conn.cursor() as c:
                c.execute(
                    'SELECT sha1, z_contents FROM unreduced_cases_view ' +
                    'ORDER BY sha1 LIMIT 1')
                r = c.fetchone()
        if r is None:
            return None
        return (r[0], zlib.decompress(r[1]))

    def addReduced(self, versions, sha, result, contents=None):
        'Add a reduced case.'

        if result == ReduceResult.ok or result == ReduceResult.dumb:
            assert contents, 'Result OK or dumb but no contents?'
        else:
            assert result == ReduceResult.no_crash, result
            assert contents is None
        llvm_version = versions['llvm']
        clang_version = versions['clang']
        with self.conn:
            with self.conn.cursor() as c:
                c.execute('SELECT id FROM cases WHERE sha1=%s', (sha, ))
                case_id = c.fetchone()
                assert case_id, sha
                case_id = case_id[0]
                c.execute('INSERT INTO reduced_cases (original, ' +
                          '    clang_version, llvm_version, result) ' +
                          'VALUES (%s, %s, %s, %s) RETURNING id', (
                              case_id, clang_version, llvm_version,
                              result.name))
                cr_id = c.fetchone()[0]
                if not contents is None:
                    c.execute('INSERT INTO reduced_contents ' +
                              '    (reduced_id, contents) ' +
                              'VALUES (%s, %s)', (cr_id, contents))

    class TestRunContext(object):
        'A context manager for test runs.'

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
            'Add a result. Output will be ignored if result_string="OK".'
            self.results.append((sha, result_string, output))
