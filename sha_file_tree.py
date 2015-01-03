#!/usr/bin/env python3

import os
from hashlib import sha1
from shutil import rmtree
import sys

from utils import all_files_recursive

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


def make_empty_sha_tree(path):
    os.mkdir(path)
    for x in DIGITS:
        os.mkdir(os.path.join(path, x))
        for y in DIGITS:
            os.mkdir(os.path.join(path, x, y))


def rm_files_not_in(path, new_files):
    new_files = set(new_files)
    to_rm = []
    for fname in all_files_recursive(path, followlinks=False):
        d, f = os.path.split(fname)
        d, d2 = os.path.split(d)
        d, d1 = os.path.split(d)
        ERR = 'Weird s/h/sha path: ' + fname
        assert os.path.samefile(d, path), ERR
        assert d1 in DIGITS, ERR
        assert d2 in DIGITS, ERR
        assert len(f) > 2 and f[0] == d1 and f[1] == d2, ERR
        rel_fname = os.path.join(d1, d2, f)
        if rel_fname in new_files:
            new_files.remove(rel_fname)
        else:
            to_rm.append(rel_fname)

    assert not new_files, 'Did not exhaust new_files: ' + str(new_files)
    for fname in to_rm:
        os.remove(os.path.join(path, fname))


def make_sha_tree(path, contentses, suffix='', rm_old=False):
    'Make a two-level sha tree rooted on path.'

    if not os.path.isdir(path):
        make_empty_sha_tree(path)

    if rm_old:
        NEW_FILES = []

    for contents in contentses:
        sha = sha1(contents).hexdigest()
        rel_fname = os.path.join(sha[0], sha[1], sha) + suffix
        if rm_old:
            NEW_FILES.append(rel_fname)
        fname = os.path.join(path, rel_fname)
        if not os.path.exists(fname):
            with open(fname, 'wb') as f:
                f.write(contents)

    if rm_old:
        rm_files_not_in(path, NEW_FILES)
