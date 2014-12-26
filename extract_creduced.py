#!/usr/bin/env python3

from triage_db import TriageDb
from hashlib import sha1
import os

def main():
    db = TriageDb()
    os.mkdir('reduced')
    for contents in db.iterateDistinctReduced():
        sha = sha1(contents).hexdigest()
        with open(os.path.join('reduced', sha+'.cpp'), 'wb') as f:
            f.write(contents)

if __name__ == '__main__':
    main()            
