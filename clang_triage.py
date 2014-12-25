#!/usr/bin/env python3

import os, sys, subprocess as subp, tempfile, copy, time, string
from triage_db import TriageDb
from repository import update_and_build, get_versions

from config import *

def inputs():
    files = [x for x in os.listdir(TEST_CASE_DIR) if x.endswith('.cpp.lz')]
    files.sort()
    for fname in files:
        sha = fname.rsplit('.', 2)[0]
        with open(os.path.join(TEST_CASE_DIR, fname)) as f:
            data = subp.check_output(['lzip', '-d'], stdin=f)
        yield sha, data

def save_data(prefix, data):
    t = int(time.time())
    for i in range(-1,1000):
        fname = os.path.join(REPORT_SAVE_DIR, '{}-{}'.format(
            prefix, t))
        if i!= -1:
            fname += '.' + str(i)
        if not os.path.exists(fname):
            with open(fname, 'wb') as f:
                f.write(data)
                return

def check_for_clang_crash(output, retval):
    # timeout -> return value 124 (per timeout manual)
    if output.find(b'Segmentation fault') != -1:
        return 'SEGV'
    a = output.find(b'Assertion ')
    if a == -1:
        a = output.find(b'UNREACHABLE ')
    if a != -1:
        return output[a:].split(b'\n', 1)[0].decode('utf-8')
    if output.find(b'Stack dump:') != -1:
        save_data('stack-dump', output)
        return 'Stack dump found'
    if retval > 128:
        return 'Killed by signal %d' % (retval-128)
    return None

def env_with_tmpdir(path):
    env = copy.copy(os.environ)
    env['TMPDIR'] = path
    env['TMP'] = path
    env['TEMP'] = path
    return env

def test_input(data, extra_params=[]):
    CMD = TIMEOUT_CMD + [CLANG_BINARY] + CLANG_PARAMS + extra_params
    p = subp.Popen(CMD, stdin=subp.PIPE, stdout=subp.PIPE,
                   stderr=subp.STDOUT, cwd='/')
    stdout = p.communicate(data)[0]
    retval = p.returncode
    return check_for_clang_crash(stdout, retval)

def run_creduce(data):
    reason = test_input(data)
    assert reason, 'Cannot run_creduce() on a non-crashing input.'
    assert (os.path.isfile(CREDUCE_PROPERTY_SCRIPT) and
            os.access(CREDUCE_PROPERTY_SCRIPT, os.X_OK)), (
        'No %s in cwd %s (or not executable).' % (CREDUCE_PROPERTY_SCRIPT, os.getcwd()))
    with tempfile.TemporaryDirectory(prefix='clang_triage') as creduce_dir:
        # creduce may leave files, so point TMPDIR below our creduce
        # temp dir
        env_tmpdir = os.path.join(creduce_dir, 'tmp')
        os.mkdir(env_tmpdir)
        reason_fname = os.path.join(creduce_dir, 'crash_reason.dat')
        cpp_fname = os.path.join(creduce_dir, 'buggy.cpp')
        prop_script = os.path.abspath(CREDUCE_PROPERTY_SCRIPT)
        with open(reason_fname, 'w') as f:
            f.write(reason)
        with open(cpp_fname, 'wb') as f:
            f.write(data)

        env = env_with_tmpdir(env_tmpdir)
        env['CLANG_TRIAGE_TMP'] = creduce_dir
        try:
            # creduce is buggy, so execute with a timeout
            subp.check_call(['timeout', str(CREDUCE_TIMEOUT),
                             'creduce', prop_script, 'buggy.cpp'],
                            env=env, cwd=creduce_dir,
                            stdout=subp.DEVNULL, stderr=subp.DEVNULL)
        except subp.CalledProcessError as e:
            print('CReduce failed with exit code ' + str(e.returncode),
                  file=sys.stderr)
            return None
        with open(cpp_fname, 'rb') as f:
            reduced = f.read()
    reduced_reason = test_input(reduced)
    if reason != reduced_reason:
        print('CReduced case produces different result: {} != {}'.format(
            reduced_reason, reason), file=sys.stderr)
        return None
    return reduced

PRINTABLE = string.printable.encode('ascii')

def try_remove_nonprintables(contents, reason):
    reduced = b''
    for i in range(len(contents)):
        if not contents[i] in PRINTABLE:
            if i != len(contents)-1:
                tail = contents[i+1:]
            else:
                tail = b''
            for replacement in [b'', b' ', b'_']:
                r = test_input(reduced + replacement + tail)
                if r == reason:
                    reduced += replacement
                    break
            else:
                # failed to remove
                reduced += contents[i:i+1]
        else:
            reduced += contents[i:i+1]
    assert test_input(contents) == test_input(reduced)
    return reduced

def creduce_worker_one_iter(db, versions):
    work = db.getCReduceWork()
    if not work:
        return None
    sha, contents = work
    print('Running creduce for ' + sha + '...', file=sys.stderr)
    reason = test_input(contents)
    if not reason:
        print('Error: Input does not crash.', file=sys.stderr)
        db.removeCReduceRequest(sha)
        return True
    reduced = run_creduce(contents)
    if not reduced is None:
        #print('Got reduced case of {} bytes, trying to further remove nonprintables...'.format(
        #    len(reduced)))
        reduced_old = reduced
        reduced = try_remove_nonprintables(reduced, reason)
        #print('Removed {} nonprintables.'.format(len(reduced_old)-len(reduced)))
    db.addCReduced(versions, sha, reduced)
    return True

def update_and_check_if_should_run(db):
    versions = get_versions()
    idle_func = lambda: creduce_worker_one_iter(db, versions)
    update_and_build(idle_func) # sleeps or runs creduce
    versions = get_versions()

    lastRun = db.getLastRunTimeByVersions(versions)
    if lastRun:
        print('A test run with these versions was started at {} and completed at {}. Skipping test.'.format(
            time.asctime(time.localtime(lastRun[0])), time.asctime(time.localtime(lastRun[1]))),
              file=sys.stderr)
        return False
    else:
        print('Version previously unseen. Running test...', file=sys.stderr)
    return True

def test_iter(start_from_current=False):
    '''Build new version if available and execute tests.
    Returns False if no new versions were available and nothing done.'''

    db = TriageDb()

    if not start_from_current and not update_and_check_if_should_run(db):
        return False

    versions = get_versions()

    # FIXME: If we at some point support concurrent test runners, there is a
    # race between checking version and starting the test run.
    numCases = db.getNumberOfCases()
    with db.testRun(versions) as run:
        i=1
        numBad = 0
        for sha, data in db.iterateCases():
            reason = test_input(data)
            if not reason:
                reason = 'OK'
            else:
                numBad += 1
            #print('{}/{} ({}): {}'.format(i, numCases, sha, reason))
            print('\r{curr}/{max}  {nbad} bad ({prop:.1%})'.format(
                curr=i, max=numCases, nbad=numBad,
                prop=numBad/i), end='', file=sys.stderr)

            i += 1
            run.addResult(sha, reason)
            #reason = test_input(data, ['-O3'])
            #if reason:
            #    s = '{sha}\t-O3 only: {reason}'
            #    print(s.format(sha=sha, reason=reason))
        print(file=sys.stderr)

def main():
    #test_iter(True)
    while True:
        test_iter(False)


if __name__ == '__main__':
    main()
