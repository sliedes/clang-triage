#!/usr/bin/env python3

import sys
import time
import multiprocessing as mp
import argparse as argp
import shutil

from triage_db import TriageDb, ReduceResult
from repository import update_and_build, get_versions, build
from run_clang import test_input, test_input_reduce
from run_creduce import reduce_one
from dumb_reduce import dumb_reduce
from triage_report import refresh_report

from config import TRIAGE_EXTRA_CLANG_PARAMS, BZIP2_COMMAND
from config import LLVM_SYMBOLIZER_MISSING_IS_FATAL


REDUCES_SINCE_REPORT = 0


def maybe_refresh_report(unconditional=False):
    '''Refresh the XHTML report if either unconditional is True or new
    cases have been reduced since the report was last refreshed.'''

    global REDUCES_SINCE_REPORT

    if unconditional or REDUCES_SINCE_REPORT:
        refresh_report()
        REDUCES_SINCE_REPORT = 0


def reduce_worker_one_iter(db, versions):
    'Fetch reduce work and process it. Returns True if there was work.'

    global REDUCES_SINCE_REPORT

    work = db.getReduceWork()
    if not work:
        maybe_refresh_report()
        return False
    sha, contents = work
    print('Running creduce for ' + sha + '... ', file=sys.stderr, end='')
    sys.stderr.flush()
    crash = test_input_reduce(contents)[0]
    assert test_input(contents, [])[0] == crash
    if not crash:
        print('Input does not crash.', file=sys.stderr)
        db.addReduced(versions, sha, ReduceResult.no_crash)
        REDUCES_SINCE_REPORT += 1
        return True
    reduced = reduce_one(contents, crash)
    if not reduced is None:
        print('reduced {} -> {} bytes.'.format(len(contents), len(reduced)),
              file=sys.stderr)
        db.addReduced(versions, sha, ReduceResult.ok, reduced)
    else:
        # creduce failed, run dumb reduce that does not fail
        print('Running dumb reducer...', file=sys.stderr)
        reduced = dumb_reduce(contents)
        print('reduced {} -> {} bytes.'.format(len(contents), len(reduced)),
              file=sys.stderr)
        db.addReduced(versions, sha, ReduceResult.dumb, reduced)
        REDUCES_SINCE_REPORT += 1
    return True


def update_and_check_if_should_run(db):
    '''git update and build repositories and see if the versions have
    already been tested.'''

    versions = get_versions()
    idle_func = lambda: reduce_worker_one_iter(db, versions)
    if not update_and_build(idle_func):
        print('Update or build failed. Skipping test.', file=sys.stderr)
        return False
    versions = get_versions()

    lastRun = db.getLastRunTimeByVersions(versions)
    if lastRun:
        print(('A test run with these versions was started at {start} ' +
               'and completed at {end}. Skipping test.').format(
            start=time.asctime(time.localtime(lastRun[0])),
            end=time.asctime(time.localtime(lastRun[1]))),
            file=sys.stderr)
        return False
    else:
        print('Version previously unseen. Running test...', file=sys.stderr)
    return True


def triage_test_func(sha_data):
    'A test function to be run by the worker threads.'
    return (sha_data[0],
            test_input(sha_data[1], TRIAGE_EXTRA_CLANG_PARAMS))


def test_iter(start_from_current=False):
    '''Build new version if available and execute tests.
    Returns False if no new versions were available and nothing done.'''

    db = TriageDb()

    if start_from_current:
        if not build():
            start_from_current = False

    if not start_from_current:
        if not update_and_check_if_should_run(db):
            return False

    versions = get_versions()

    # FIXME: If we at some point support concurrent test runners, there is a
    # race between checking version and starting the test run.
    numCases = db.getNumberOfCases()
    with db.testRun(versions) as run:
        i = 1
        numBad = 0
        with mp.Pool() as pool:
            for sha, (crash, output) in pool.imap_unordered(
                    triage_test_func, db.iterateCases()):
                if not crash:
                    reason = 'OK'
                    output = None
                else:
                    reason = crash.reason
                    numBad += 1
                print('\r{curr}/{max}  {nbad} bad ({prop:.1%})'.format(
                    curr=i, max=numCases, nbad=numBad,
                    prop=numBad/i), end='', file=sys.stderr)
                i += 1

                run.addResult(sha, reason, output)
        print(file=sys.stderr)


def check_prereqs():
    WARN = [('psql', 'Schema creation will not work.')]

    if not LLVM_SYMBOLIZER_MISSING_IS_FATAL:
        WARN.append(('llvm-symbolizer',
                     'Recorded outputs may be less useful.'))

    for prog, warn in WARN:
        if shutil.which(prog) is None:
            print('WARNING: No {} found in PATH. {}'.format(prog, warn),
                  file=sys.stderr)

    REQS = ['git', 'ninja', 'creduce', 'timeout', 'tar', BZIP2_COMMAND]

    if LLVM_SYMBOLIZER_MISSING_IS_FATAL:
        REQS.append('llvm-symbolizer')

    err = False
    for prog in REQS:
        if shutil.which(prog) is None:
            print('Error: No {} in PATH.'.format(prog), file=sys.stderr)
            err = True

    if err:
        sys.exit(1)


def main():
    global REDUCES_SINCE_REPORT

    check_prereqs()

    mp.set_start_method('forkserver')

    parser = argp.ArgumentParser(description='Clang triage daemon.')

    # FIXME doesn't work because of db constraint violation.
    # Perhaps we should have an option for replacing a test run? Or
    # relax the constraint and order test runs in some other way than
    # by versions?
    parser.add_argument(
        '--start-from-current', action='store_true',
        help='Run test immediately once after git pull even if this '
        'version has already been tested.')
    args = parser.parse_args()

    start_from_current = args.start_from_current

    while True:
        test_iter(start_from_current)
        start_from_current = False
        maybe_refresh_report(unconditional=True)


if __name__ == '__main__':
    main()
