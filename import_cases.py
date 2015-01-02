#!/usr/bin/python3

import argparse as argp
from triage_db import TriageDb, DbNotInitialized
import sys


def main():
    parser = argp.ArgumentParser(
        description="Import test cases to clang-triage's database.")
    parser.add_argument('srcdir', type=str,
                        help='The directory to import test cases from.')
    parser.add_argument('--stop-after', metavar='N', action='store',
                        type=int,
                        help='Stop after importing N cases. ' +
                        'This is probably only useful for testing.')
    args = parser.parse_args()

    try:
        db = TriageDb()
    except DbNotInitialized:
        TriageDb.createSchema()
        db = TriageDb()

    print('Importing cases...', file=sys.stderr)
    db.populateCases(args.srcdir, stop_after=args.stop_after)


if __name__ == '__main__':
    main()
