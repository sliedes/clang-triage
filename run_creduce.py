#!/usr/bin/env python3

import os
import tempfile
import sys
import string
import subprocess as subp

from run_clang import test_input
from utils import env_with_tmpdir
from config import CREDUCE_PROPERTY_SCRIPT, CREDUCE_TIMEOUT


def run_creduce(data, reason):
    assert reason, 'Cannot run_creduce() on a non-crashing input.'
    assert (os.path.isfile(CREDUCE_PROPERTY_SCRIPT) and
            os.access(CREDUCE_PROPERTY_SCRIPT, os.X_OK)), (
        'No %s in cwd %s (or not executable).' % (
            CREDUCE_PROPERTY_SCRIPT, os.getcwd()))
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
    reduced_reason, output = test_input(reduced)
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
                r, out = test_input(reduced + replacement + tail)
                if r == reason:
                    reduced += replacement
                    break
            else:
                # failed to remove
                reduced += contents[i:i+1]
        else:
            reduced += contents[i:i+1]
    assert test_input(contents)[0] == test_input(reduced)[0]
    return reduced


def reduce_one(data, reason):
    res = run_creduce(data, reason)
    if not res:
        return None
    return try_remove_nonprintables(res, reason)


def main():
    data = sys.stdin.buffer.read()
    print(reduce_one(data, test_input(data)[0]))

if __name__ == '__main__':
    main()
