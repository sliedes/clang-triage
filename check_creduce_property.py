#!/usr/bin/env python3

import run_clang as rc
import sys
import os


def read_or_die(fname):
    try:
        with open(fname, 'rb') as f:
            return f.read()
    except IOError:
        print('FATAL: Unable to open %s.' % fname)
        sys.exit(1)


def main():
    fname = 'crash_reason.dat'
    if 'CLANG_TRIAGE_TMP' in os.environ:
        fname = os.path.join(os.environ['CLANG_TRIAGE_TMP'], fname)
    reason = read_or_die(fname).decode('utf-8')
    data = read_or_die('buggy.cpp')
    result = rc.test_input(data)
    if result.strip() == reason.strip():
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
