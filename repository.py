from config import PROJECTS, MIN_GIT_CHECKOUT_INTERVAL, NINJA_PARAMS, BUILD
import sys, time
import subprocess as subp
from utils import const

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

        self.svn_revision = None
        if self.svn_id:
            url, uuid = self.svn_id.split(' ')
            self.svn_revision = int(url.split('@')[-1])

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

def update_all(versions, idle_func=const(False)):
    '''Update repositories if interval has passed. If not, call idle_func
    until it has. If idle_func returns False, just sleep.'''
    global LAST_UPDATED
    # run creduce or sleep until we're allowed to update again
    while True:
        elapsed = time.time() - LAST_UPDATED
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
    LAST_UPDATED = time.time()

def get_versions():
    'Returns a dict of svn revisions.'
    out = {}
    for proj, path in PROJECTS.items():
        info = CommitInfo(path)
        assert info.svn_revision, info
        out[proj] = info.svn_revision
    return out

def build():
    subp.check_call(['ninja'] + NINJA_PARAMS, cwd=BUILD)

def update_and_build(idle_func=const(False)):
    versions = get_versions()
    print('Version: ' + str(versions))
    update_all(versions, idle_func)
    print('Version: ' + str(get_versions()))
    build()
