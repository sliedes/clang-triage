import os
import copy


def env_with_tmpdir(path):
    env = copy.copy(os.environ)
    env['TMPDIR'] = path
    env['TMP'] = path
    env['TEMP'] = path
    return env


def const(x):
    'Returns a constant function.'
    return lambda *a, **b: x
