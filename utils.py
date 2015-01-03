import os
import copy


def env_with_tmpdir(path):
    'Return a copy of os.environ with TMPDIR & friends set.'
    env = copy.copy(os.environ)
    env['TMPDIR'] = path
    env['TMP'] = path
    env['TEMP'] = path
    return env


def const(x):
    'Returns a constant function.'
    return lambda *a, **b: x


def all_files_recursive(path, followlinks=True):
    'Iterate through all non-directories, recursively.'
    for root, dirs, files in os.walk(path, followlinks=followlinks):
        for f in files:
            yield os.path.join(root, f)
