from config import REPORT_SAVE_DIR, TIMEOUT_CMD, CLANG_BINARY, CLANG_PARAMS
import subprocess as subp
import os, time

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
        save_data('stack-dump', output)
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
