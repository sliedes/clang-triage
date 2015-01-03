#!/usr/bin/env python3

from triage_db import TriageDb
from sha_file_tree import make_sha_tree


def extract_cases(path):
    db = TriageDb()
    make_sha_tree(path, (x[1] for x in db.iterateCases()),
                  suffix='.cpp', rm_old=False)


def main():
    extract_cases('sha')


if __name__ == '__main__':
    main()
