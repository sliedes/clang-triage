#!/usr/bin/env python3

from triage_db import TriageDb
import os

def write_file(path, contents, mode='wb'):
    with open(path, mode) as f:
        f.write(contents)
    

def extract_dumb_reduced():
    'Extract all dumb-reduced cases.'

    db = TriageDb()
    #os.mkdir('dumb')
    for i, (orig, reduced, reason) in enumerate(db.iterateDumbReduced()):
        stem = 'dumb/' + str(i+1) + '-'
        write_file(stem + 'orig.cpp', orig)
        write_file(stem + 'reduced.cpp', reduced)
        write_file(stem + 'failure-reason.txt', reason + '\n', mode='w')
        


def main():
    extract_dumb_reduced()


if __name__ == '__main__':
    main()
