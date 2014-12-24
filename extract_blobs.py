#!/usr/bin/env python3

from triage_db import TriageDb
import os

def main():
    db = TriageDb()

    DIGITS='0123456789abcdef'
    os.mkdir('sha')
    for x in DIGITS:
        os.mkdir('sha/'+x)
        for y in DIGITS:
            os.mkdir('sha/'+x+'/'+y)
    for sha, contents in db.iterateCases():
        assert len(sha) == 40
        assert sha.lower() == sha
        fname = 'sha/{}/{}/{}.cpp'.format(sha[0], sha[1], sha)
        with open(fname, 'wb') as f:
            f.write(contents)

if __name__ == '__main__':
    main()
