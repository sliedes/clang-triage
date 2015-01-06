#!/usr/bin/env python3

import os
import tempfile
import sys
import string
import subprocess as subp

from run_clang import test_input, test_input_reduce
from utils import env_with_tmpdir
from config import CREDUCE_PROPERTY_SCRIPT, CREDUCE_TIMEOUT


def run_creduce(data, crash):
    'Run CReduce for the data.'

    assert crash, 'Cannot run_creduce() on a non-crashing input.'
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
            f.write(crash.reason)
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
    reduced_crash, output = test_input_reduce(reduced)
    if crash != reduced_crash:
        print('CReduced case produces different result: {} != {}'.format(
            reduced_crash, crash), file=sys.stderr)
        return None
    return reduced


PRINTABLE = string.printable.encode('ascii')


def try_remove_nonprintables(contents, crash):
    'Minimize the case wrt non-printable characters.'

    reduced = b''
    for i in range(len(contents)):
        if not contents[i] in PRINTABLE:
            if i != len(contents)-1:
                tail = contents[i+1:]
            else:
                tail = b''
            for replacement in [b'', b' ', b'_']:
                r, out = test_input_reduce(reduced + replacement + tail)
                if r == crash:
                    reduced += replacement
                    break
            else:
                # failed to remove
                reduced += contents[i:i+1]
        else:
            reduced += contents[i:i+1]
    assert (test_input_reduce(contents)[0] ==
            test_input_reduce(reduced)[0])
    return reduced


def reduce_one(data, crash):
    'CReduce this case, then minimize it wrt nonprintables.'

    res = run_creduce(data, crash)
    if not res:
        return None
    return try_remove_nonprintables(res, crash)


def main():
    data = sys.stdin.buffer.read()
    print(reduce_one(data, test_input(data)[0]))


if __name__ == '__main__':
    main()
