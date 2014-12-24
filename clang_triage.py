#!/usr/bin/env python3

import os, sys, subprocess as subp, tempfile, copy, time
from triage_db import TriageDb

TOP = '/home/sliedes/scratch/build/clang-triage'
LLVM_SRC = TOP + '/llvm.src'
BUILD = TOP + '/clang-triage.ninja'
TEST_CASE_DIR = '/home/sliedes/scratch/afl/cases.minimized'

NINJA_PARAMS = ['-j8']

TIMEOUT_CMD = ['timeout', '-k', '4', '4']

CLANG_PARAMS = ['-Werror', '-ferror-limit=5', '-std=c++11',
                '-fno-crash-diagnostics', '-xc++', '-c',
                '-o' '/dev/null', '-']

PROJECTS = {'llvm' : LLVM_SRC, 'clang' : LLVM_SRC + '/tools/clang'}

CLANG_BINARY = BUILD + '/bin/clang'

CREDUCE_PROPERTY_SCRIPT = 'check_creduce_property.py'

MIN_GIT_CHECKOUT_INTERVAL = 10*60 # seconds


class CommitInfo(object):
    def __git(self, fmt):
        CMD = ['git', 'show', '-s', '--format='+fmt, self.name]
        out = subp.check_output(CMD, cwd=self.path).decode('utf-8')
        assert out.endswith('\n')
        return out[:-1]

    def __init__(self, path, name = None):
        self.path = path

        if not name:
            name = 'HEAD'

        self.name = name
        self.commit_id = self.__git('%H')
        self.author = self.__git('%an <%ae>')
        self.date = self.__git('%ad')
        self.date_ts = int(self.__git('%at'))
        self.short = self.__git('%s')
        self.body = self.__git('%B')

        self.svn_id = None
        for line in self.body.splitlines():
            if line.startswith('git-svn-id: '):
                self.svn_id = line.split(' ', 1)[1]

    def __str__(self):
        return 'CommitInfo(commit_id={commit_id}, short="{short}")'.format(
            commit_id = self.commit_id, short = self.short)


def git_pull(path):
    try:
        subp.check_output(['git', 'pull'], cwd=path)
    except subp.CalledProcessError as e:
        print('git pull failed with exit code %d.' % e.returncode,
              file=sys.stderr)
        print('Output was:\n' + e.output.decode('utf-8'), file=sys.stderr)
        raise


LAST_UPDATED = 0

def update_all():
    global LAST_UPDATED
    elapsed = time.time() - LAST_UPDATED
    left = MIN_GIT_CHECKOUT_INTERVAL - elapsed
    if left > 0:
        print('Sleeping for {:.1f} seconds...'.format(left),
              file=sys.stderr)
        time.sleep(left)
    for proj, path in PROJECTS.items():
        git_pull(path)
    LAST_UPDATED = time.time()

def get_versions():
    out = {}
    for proj, path in PROJECTS.items():
        info = CommitInfo(path)
        out[proj] = info.svn_id
    return out

def get_versions_str():
    return str(sorted(get_versions().items()))

def build():
    subp.check_call(['ninja'] + NINJA_PARAMS, cwd=BUILD)

def inputs():
    files = [x for x in os.listdir(TEST_CASE_DIR) if x.endswith('.cpp.lz')]
    files.sort()
    for fname in files:
        sha = fname.rsplit('.', 2)[0]
        with open(os.path.join(TEST_CASE_DIR, fname)) as f:
            data = subp.check_output(['lzip', '-d'], stdin=f)
        yield sha, data


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
        return 'Stack dump found'
    if retval > 128:
        return 'Killed by signal %d' % (retval-128)
    return None


def test_input(data, extra_params=[]):
    CMD = TIMEOUT_CMD + [CLANG_BINARY] + CLANG_PARAMS + extra_params
    p = subp.Popen(CMD, stdin=subp.PIPE, stdout=subp.PIPE,
                   stderr=subp.STDOUT, cwd='/')
    stdout = p.communicate(data)[0]
    retval = p.returncode
    return check_for_clang_crash(stdout, retval)


def update_and_build():
    print('Version: ' + get_versions_str())
    update_all()
    print('Version: ' + get_versions_str())
    build()


def run_creduce(data):
    reason = test_input(data)
    assert reason, 'Cannot run_creduce() on a non-crashing input.'
    assert (os.path.isfile(CREDUCE_PROPERTY_SCRIPT) and
            os.access(CREDUCE_PROPERTY_SCRIPT, os.X_OK)), (
        'No %s in cwd %s (or not executable).' % (CREDUCE_PROPERTY_SCRIPT, os.getcwd()))
    with tempfile.TemporaryDirectory(prefix='clang_triage') as creduce_dir:
        # creduce may leave files from killed compilers, so point
        # TMPDIR below our creduce temp dir
        env_tmpdir = os.path.join(creduce_dir, 'tmp')
        os.mkdir(env_tmpdir)
        reason_fname = os.path.join(creduce_dir, 'crash_reason.dat')
        cpp_fname = os.path.join(creduce_dir, 'buggy.cpp')
        prop_script = os.path.abspath(CREDUCE_PROPERTY_SCRIPT)
        with open(reason_fname, 'w') as f:
            f.write(reason)
        with open(cpp_fname, 'wb') as f:
            f.write(data)

        env = copy.copy(os.environ)
        env['TMPDIR'] = env_tmpdir
        env['CLANG_TRIAGE_TMP'] = creduce_dir
        subp.check_call(['creduce', prop_script, 'buggy.cpp'],
                        env=env, cwd=creduce_dir)
        with open(cpp_fname, 'rb') as f:
            return f.read()

def update_and_check_if_should_run(db):
    update_and_build() # sleeps
    versions = get_versions_str()

    lastRun = db.getLastRunTimeByVersions(versions)
    if lastRun:
        print('A test run with this version was started at {} and completed at {}. Skipping test.'.format(
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

    versions = get_versions_str()

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
