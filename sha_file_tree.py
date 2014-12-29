#!/usr/bin/env python3

import os
from hashlib import sha1
from shutil import rmtree
import sys

__all__ = ['make_sha_tree']

DIGITS = '0123456789abcdef'


def looks_like_sha_tree(path):
    assert os.path.isdir(path)
    li = os.listdir(path)
    for x in os.listdir(path):
        if not x in DIGITS:
            print("{} doesn't look like it belongs to a sha tree.".format(
                os.path.join(path, x)), file=sys.stderr)
            return False
    if len(li) != len(DIGITS):
        print("{} lacks some of the hex digit dirs.".format(path),
              file=sys.stderr)
        return False
    return True


def make_sha_tree(path, contentses, suffix='', rm_old=False):
    'Make a two-level sha tree rooted on path.'

    if rm_old and os.path.isdir(path):
        assert looks_like_sha_tree(path)
        rmtree(path)

    if not os.path.isdir(path):
        os.mkdir(path)
        for x in DIGITS:
            os.mkdir(os.path.join(path, x))
            for y in DIGITS:
                os.mkdir(os.path.join(path, x, y))

    for contents in contentses:
        sha = sha1(contents).hexdigest()
        fname = os.path.join(path, sha[0], sha[1], sha) + suffix
        if not os.path.exists(fname):
            with open(fname, 'wb') as f:
                f.write(contents)
