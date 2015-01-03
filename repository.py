import sys
import time
import subprocess as subp

from utils import const
from config import PROJECTS, MIN_GIT_CHECKOUT_INTERVAL, NINJA_PARAMS, BUILD


class CommitInfo(object):
    'Information of a single git commit.'

    def __git(self, fmt):
        CMD = ['git', 'show', '-s', '--format='+fmt, self.name]
        out = subp.check_output(CMD, cwd=self.path).decode('utf-8')
        assert out.endswith('\n')
        return out[:-1]

    def __init__(self, path, name=None):
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

        self.svn_revision = None
        if self.svn_id:
            url, uuid = self.svn_id.split(' ')
            self.svn_revision = int(url.split('@')[-1])

    def __str__(self):
        return 'CommitInfo(commit_id={commit_id}, short="{short}")'.format(
            commit_id=self.commit_id, short=self.short)


def git_pull(path):
    'Execute git pull in a path. Redo until success.'

    success = False
    while not success:
        try:
            subp.check_output(['git', 'pull'], cwd=path)
            success = True
        except subp.CalledProcessError as e:
            print('git pull failed with exit code %d.' % e.returncode,
                  file=sys.stderr)
            print('Output was:\n' + e.output.decode('utf-8'), file=sys.stderr)
            print('Trying again after 30 seconds...', file=sys.stderr)
            time.sleep(30)


LAST_UPDATED_TIME = 0


def update_all(versions, idle_func=const(False)):
    '''Update repositories if MIN_GIT_CHECKOUT_INTERVAL has passed. If
    not, call idle_func until it has. If idle_func returns False, just
    sleep.'''

    global LAST_UPDATED_TIME
    # run reduce or sleep until we're allowed to update again
    while True:
        elapsed = time.time() - LAST_UPDATED_TIME
        left = MIN_GIT_CHECKOUT_INTERVAL - elapsed
        if left <= 0:
            break
        print('Still {:.1f} seconds to wait before git pull.'.format(
            left), file=sys.stderr)
        if not idle_func():
            print('No idle work to do, sleeping...', file=sys.stderr)
            time.sleep(left)
    for proj, path in PROJECTS.items():
        git_pull(path)
    LAST_UPDATED_TIME = time.time()
    return True


def get_versions():
    'Returns a dict of svn revisions.'

    out = {}
    for proj, path in PROJECTS.items():
        info = CommitInfo(path)
        assert info.svn_revision, info
        out[proj] = info.svn_revision
    return out


def build():
    'Build LLVM/Clang. Returns True on success, False on failure.'

    try:
        subp.check_call(['ninja'] + NINJA_PARAMS, cwd=BUILD)
    except subp.CalledProcessError:
        print('Ninja build failed.', file=sys.stderr)
        return False
    return True


def update_and_build(idle_func=const(False)):
    '''Update and build LLVM/Clang. Returns True on success, False on
    failure.'''

    versions = get_versions()
    print('Version: ' + str(versions))
    if not update_all(versions, idle_func):
        return False
    print('Version: ' + str(get_versions()))
    return build()
