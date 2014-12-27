#!/usr/bin/env python3

from triage_db import TriageDb
from hashlib import sha1
import os


def main():
    db = TriageDb()

    DIGITS = '0123456789abcdef'
    if not os.path.isdir('cr'):
        os.mkdir('cr')
        for x in DIGITS:
            os.mkdir('cr/'+x)
            for y in DIGITS:
                os.mkdir('cr/'+x+'/'+y)

    for contents in db.iterateDistinctReduced():
        sha = sha1(contents).hexdigest()
        fname = 'cr/{}/{}/{}.cpp'.format(sha[0], sha[1], sha)
        if not os.path.exists(fname):
            with open(fname, 'wb') as f:
                f.write(contents)

if __name__ == '__main__':
    main()
