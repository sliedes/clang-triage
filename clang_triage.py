#!/usr/bin/env python3

import sys
import subprocess as subp
import time

from triage_db import TriageDb, CReduceResult
from repository import update_and_build, get_versions, build
from run_clang import test_input
from run_creduce import reduce_one
from dumb_reduce import dumb_reduce


def reduce_worker_one_iter(db, versions):
    work = db.getCReduceWork()
    if not work:
        return None
    sha, contents = work
    print('Running creduce for ' + sha + '... ', file=sys.stderr, end='')
    sys.stderr.flush()
    reason = test_input(contents)[0]
    if not reason:
        print('Input does not crash.', file=sys.stderr)
        db.addCReduced(versions, sha, CReduceResult.no_crash)
        return True
    reduced = reduce_one(contents, reason)
    if not reduced is None:
        print('reduced {} -> {} bytes.'.format(len(contents), len(reduced)),
              file=sys.stderr)
        db.addCReduced(versions, sha, CReduceResult.ok, reduced)
    else:
        # creduce failed, run dumb reduce that does not fail
        print('Running dumb reducer...', file=sys.stderr)
        reduced = dumb_reduce(contents)
        print('reduced {} -> {} bytes.'.format(len(contents), len(reduced)),
              file=sys.stderr)
        db.addCReduced(versions, sha, CReduceResult.ok, reduced)
    return True


def update_and_check_if_should_run(db):
    versions = get_versions()
    idle_func = lambda: reduce_worker_one_iter(db, versions)
    if not update_and_build(idle_func):
        print('Update or build failed. Skipping test.', file=sys.stderr)
        return False
    versions = get_versions()

    lastRun = db.getLastRunTimeByVersions(versions)
    if lastRun:
        print('A test run with these versions was started at {} ' +
              'and completed at {}. Skipping test.'.format(
                  time.asctime(time.localtime(lastRun[0])),
                  time.asctime(time.localtime(lastRun[1]))),
              file=sys.stderr)
        return False
    else:
        print('Version previously unseen. Running test...', file=sys.stderr)
    return True


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
        for sha, data in db.iterateCases():
            reason, output = test_input(data)
            if not reason:
                reason = 'OK'
                output = None
            else:
                numBad += 1
            #print('{}/{} ({}): {}'.format(i, numCases, sha, reason))
            print('\r{curr}/{max}  {nbad} bad ({prop:.1%})'.format(
                curr=i, max=numCases, nbad=numBad,
                prop=numBad/i), end='', file=sys.stderr)
            i += 1

            run.addResult(sha, reason, output)
            #reason = test_input(data, ['-O3'])
            #if reason:
            #    s = '{sha}\t-O3 only: {reason}'
            #    print(s.format(sha=sha, reason=reason))
        print(file=sys.stderr)


def main():
    #test_iter(True)
    while True:
        test_iter(False)
        subp.call(['./update-hook.sh'])


if __name__ == '__main__':
    main()
