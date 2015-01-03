import subprocess as subp
import os
import time
import copy

from config import MISC_REPORT_SAVE_DIR, CLANG_BINARY
from config import CLANG_PARAMS, CLANG_TIMEOUT_CMD
from config import REDUCTION_EXTRA_CLANG_PARAMS
from config import DUMMY_LLVM_SYMBOLIZER_PATH


def save_misc_report(prefix, data):
    'Save a miscellaneous report.'

    t = int(time.time())
    if not os.path.isdir(MISC_REPORT_SAVE_DIR):
        os.path.mkdir(MISC_REPORT_SAVE_DIR)
    for i in range(-1, 1000):
        fname = os.path.join(MISC_REPORT_SAVE_DIR, '{}-{}'.format(
            prefix, t))
        if i != -1:
            fname += '.' + str(i)
        if not os.path.exists(fname):
            with open(fname, 'wb') as f:
                f.write(data)
                return


def check_for_clang_crash(output, retval):
    '''Inspect the output and retval and return a string describing the
    crash, if any, or None if no crash.'''

    # timeout -> return value 124 (per timeout manual)
    if output.find(b'Segmentation fault') != -1:
        return 'SEGV'
    elif output.find(b'Illegal instruction') != -1:
        return 'Illegal instruction'
    a = output.find(b'Assertion ')
    if a == -1:
        a = output.find(b'UNREACHABLE ')
    if a == -1:
        a = output.find(b'terminate called after throwing an instance')
    if a != -1:
        return output[a:].split(b'\n', 1)[0].decode('utf-8')
    if output.find(b'Stack dump:') != -1:
        # The output contains a stack dump, but we couldn't determine
        # a more precise reason for the crash. Save a miscellaneous
        # report and continue.
        save_misc_report('stack-dump', output)
        return 'Stack dump found'
    if retval > 128:
        return 'Killed by signal %d' % (retval-128)
    return None


def test_input(data, extra_params=[], extra_path=[]):
    'Test the input and return (crash_reason, output).'

    CMD = CLANG_TIMEOUT_CMD + [CLANG_BINARY] + CLANG_PARAMS + extra_params
    env = copy.copy(os.environ)
    path = os.pathsep.join(extra_path + env['PATH'].split(os.pathsep))
    env['PATH'] = path
    with subp.Popen(CMD, stdin=subp.PIPE, stdout=subp.PIPE,
                    stderr=subp.STDOUT, cwd='/', env=env) as p:
        stdout = p.communicate(data)[0]
        retval = p.returncode
        return check_for_clang_crash(stdout, retval), stdout


def test_input_reduce(data):
    '''Test the input, but avoid running llvm-symbolizer since it is slow
    and we don't care about the output being symbolized.'''

    return test_input(
        data, extra_params=REDUCTION_EXTRA_CLANG_PARAMS,
        extra_path=[os.path.abspath(DUMMY_LLVM_SYMBOLIZER_PATH)])
