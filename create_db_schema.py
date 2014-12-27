#!/usr/bin/env python3

from triage_db import TriageDb

def main():
    db = TriageDb()
    db.createSchema()

if __name__ == '__main__':
    main()
