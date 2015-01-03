#!/usr/bin/env python3

from triage_db import TriageDb
from sha_file_tree import make_sha_tree


def extract_outputs(path):
    'Make or update a s/h/sha tree of outputs. Removes old outputs.'

    db = TriageDb()
    # Unlike cases and reduced cases, we wish to remove old outputs.
    # They vary a lot, and we can't just accumulate them forever.
    make_sha_tree(path, db.iterateOutputs(), suffix='.txt', rm_old=True)


def main():
    extract_outputs('out')


if __name__ == '__main__':
    main()
