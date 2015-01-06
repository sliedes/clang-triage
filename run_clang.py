import subprocess as subp
import os
import time
import copy
from collections import namedtuple
import functools
import re

from config import MISC_REPORT_SAVE_DIR, CLANG_BINARY
from config import CLANG_PARAMS, CLANG_TIMEOUT_CMD, PROJECTS
from config import REDUCTION_EXTRA_CLANG_PARAMS
from config import DUMMY_LLVM_SYMBOLIZER_PATH, SOURCE_URLS


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


def _sort_projects():
    """Return projects in such an order that if A's source is in a
    subdirectory of B, A will be sorted before B."""

    def compare_paths(x, y):
        common = os.path.commonprefix([x, y])
        if common == x:
            return -1
        elif common == y:
            return 1
        else:
            return 0

    p = [(proj, os.path.normpath(path)) for proj, path in PROJECTS.items()]
    p.sort(key=lambda x: functools.cmp_to_key(compare_paths)(x[1]))
    return p


_PROJECTS_SORTED = _sort_projects()


def source_file_from_path(path):
    '''Convert a path to a source to a tuple of (project, relative_path).
    None if not found.'''

    path = os.path.normpath(path)

    # Need to be careful here; project locations can be and
    # typically will be beneath other project locations (like
    # clang in tools/clang under llvm), so we need to choose
    # the most specific one. For this we need to go through
    # them in the correct order.
    for proj, projpath in _PROJECTS_SORTED[::-1]:
        common = os.path.commonprefix([path, projpath])
        if common == projpath:
            return (proj, os.path.relpath(path, start=projpath))


def path_to_source_url(path):
    '''Convert a path, with an optional :lineno:column suffix, to a
    link to a source code viewer. May return None.'''

    # This will fail if there are colons in the filename. I think
    # llvm-symbolizer-annotated backtraces are not machine-readable
    # enough that everything can be taken into account.

    if not ':' in path:
        line = 0
    else:
        path, linecol = path.split(':', 1)
        line = linecol.split(':', 1)[0]
        try:
            line = int(line)
        except ValueError:
            return None

    loc = source_file_from_path(path)
    if not loc:
        return None
    proj, fname = loc

    return SOURCE_URLS[proj].format(path=fname, lineno=line)


class Crash(namedtuple('Crash', ['reason', 'srcloc'])):
    'Information about a crash.'

    __slots__ = ()

    def __new__(cls, reason, srcloc=None):
        return super(Crash, cls).__new__(cls, reason=reason, srcloc=srcloc)

    def url(self):
        '''Returns an URL to the location of the failing part in code in a
        source browser. May return None.'''

        if not srcloc:
            return None
        return path_to_source_url(self.srcloc)


# This assumes that the paths do not have spaces or colons. The output
# is not really foolproofly machine parseable.
SRCPOS_RE = re.compile(rb' (?P<path>/[^ :]+):(?P<lineno>\d+)(:(?P<col>\d+))?')

def find_crash_location(output):
    'Find path:srcloc to the crash. May return None.'

    # Right now only works for assertion failures and UNREACHABLE.

    for line in output.splitlines():
        if line.find(b'Assertion ') or line.find('UNREACHABLE '):
            m = SRCPOS_RE.search(line)
            if m:
                path = m.group('path')
                if m.group('lineno'):
                    path += b':' + m.group('lineno')
                    if m.group('col'):
                        path += b':' + m.group('col')
                return path


def check_for_clang_crash(output, retval):
    '''Inspect the output and retval and return a Crash object
    describing the crash, if any, or None if no crash.'''

    loc = find_crash_location(output)

    reason = None
    # timeout -> return value 124 (per timeout manual)
    if output.find(b'Segmentation fault') != -1:
        reason = 'SEGV'
    elif output.find(b'Illegal instruction') != -1:
        reason = 'Illegal instruction'
    else:
        a = output.find(b'Assertion ')
        if a == -1:
            a = output.find(b'UNREACHABLE ')
        if a == -1:
            a = output.find(b'terminate called after throwing an instance')
        if a != -1:
            reason = output[a:].split(b'\n', 1)[0].decode('utf-8')

    if not reason:
        if output.find(b'Stack dump:') != -1:
            # The output contains a stack dump, but we couldn't determine
            # a more precise reason for the crash. Save a miscellaneous
            # report and continue.
            save_misc_report('stack-dump', output)
            reason = 'Stack dump found'
        else:
            if retval > 128:
                reason = 'Killed by signal %d' % (retval-128)

    if reason:
        return Crash(reason, loc)


def test_input(data, extra_params=[], extra_path=[]):
    'Test the input and return (crash_object, output).'

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
