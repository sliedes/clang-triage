#!/usr/bin/env python3

from triage_db import TriageDb
from sha_file_tree import make_sha_tree


def extract_creduced(path):
    db = TriageDb()
    make_sha_tree(path, db.iterateDistinctReduced(),
                  suffix='.cpp', rm_old=False)


def main():
    extract_creduced('cr')


if __name__ == '__main__':
    main()
