#!/usr/bin/env python3

from triage_db import TriageDb
from sha_file_tree import make_sha_tree


def extract_outputs(path):
    db = TriageDb()
    make_sha_tree(path, db.iterateOutputs(), suffix='.txt', rm_old=False)


def main():
    extract_outputs('out')


if __name__ == '__main__':
    main()
