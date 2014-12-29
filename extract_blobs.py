#!/usr/bin/env python3

from triage_db import TriageDb
from sha_file_tree import make_sha_tree


def main():
    db = TriageDb()
    make_sha_tree('sha', (x[1] for x in db.iterateCases()),
                  suffix='.cpp', rm_old=True)


if __name__ == '__main__':
    main()
