#!/usr/bin/python3

# Dumps the database into JSON. The output file contains multiple
# reasonably sized JSON objects, separated by newlines.

import psycopg2 as pg

from config import DB_NAME
import json
import zlib
import sys


def bytes_to_json(obj):
    "Encode bytes as a repr(bytes) and set __method__ to 'eval'."

    if isinstance(obj, bytes):
        return {'__method__': 'eval', '__value__': repr(obj)}
    raise TypeError(repr(obj) + ' is not JSON serializable')


def dump_case_id_sha1(db, fp):
    'Dump the cases table as JSON.'

    with db.cursor() as c:
        c.execute('SELECT id, sha1 FROM cases ORDER BY id')
        results = c.fetchall()
    results = [{'id': x[0], 'sha1': x[1]} for x in results]
    json.dump({'cases': results}, fp)
    print(file=fp)


def dump_case_contents(db, fp):
    '''Dump case contents as a newline-separated series of JSON
    objects.'''

    with db.cursor() as c:
        c.execute('SELECT id, z_contents FROM case_view ORDER BY id')
        for id_, z_contents in c:
            res = {'id': id_, 'contents': zlib.decompress(z_contents)}
            json.dump({'case': res}, fp, default=bytes_to_json)
            print(file=fp)


def dump_test_runs(db, fp):
    'Dump test runs as JSON.'

    with db.cursor() as c:
        c.execute('SELECT id, start_time, end_time, clang_version, ' +
                  '    llvm_version FROM test_runs ORDER BY id')
        res = c.fetchall()
    res = [{'id': x[0], 'start_time': x[1], 'end_time': x[2],
            'clang_version': x[3], 'llvm_version': x[4]}
           for x in res]
    json.dump({'test_runs': res}, fp)
    print(file=fp)


def dump_reduced_cases(db, fp):
    '''Dump reduced case metadata as a newline-separated series of JSON
    objects.'''

    with db.cursor() as c:
        c.execute('SELECT id, original, clang_version, llvm_version, ' +
                  '    result FROM reduced_cases ORDER BY id')
        for id_, original, clang_version, llvm_version, result in c:
            res = {'id': id_, 'original': original,
                   'clang_version': clang_version,
                   'llvm_version': llvm_version, 'result': result}
            json.dump({'reduced_case': res}, fp)
            print(file=fp)


def dump_reduced_contents(db, fp):
    '''Dump reduced case contents as a newline-separated series of JSON
    objects.'''

    with db.cursor() as c:
        c.execute('SELECT reduced_id, contents FROM reduced_contents ' +
                  '    ORDER BY reduced_id')
        for id_, contents in c:
            res = {'id': id_, 'contents': bytes(contents)}
            json.dump({'reduced_case': res}, fp, default=bytes_to_json)
            print(file=fp)


def dump_outputs(db, fp):
    '''Dump clang outputs from failed cases as a newline-separated series
    of JSON objects.'''

    with db.cursor() as c:
        c.execute('SELECT case_id, output FROM outputs ' +
                  '    ORDER BY case_id')
        for id_, output in c:
            res = {'id': id_, 'output': zlib.decompress(output)}
            json.dump({'output': res}, fp, default=bytes_to_json)
            print(file=fp)


def dump_result_strings(db, fp):
    'Dump result strings as JSON.'

    with db.cursor() as c:
        c.execute('SELECT id, str FROM result_strings ORDER BY id')
        results = c.fetchall()
    results = [{'id': x[0], 'str': x[1]} for x in results]
    json.dump({'result_strings': results}, fp)
    print(file=fp)


def dump_results(db, fp):
    'Dump results as a newline-separated series of JSON objects.'

    with db.cursor() as c:
        c.execute('SELECT id, case_id, test_run, result ' +
                  '    FROM results ORDER BY id')
        for id_, case_id, test_run, result in c:
            res = {'id': id_, 'case_id': case_id, 'test_run': test_run,
                   'result': result}
            json.dump({'result': res}, fp)
            print(file=fp)


def dump_all(db, fp):
    '''Dump the entire database as a newline-separated series of JSON
    objects.'''

    dump_case_id_sha1(db, sys.stdout)
    dump_case_contents(db, sys.stdout)
    dump_test_runs(db, sys.stdout)
    dump_reduced_cases(db, sys.stdout)
    dump_reduced_contents(db, sys.stdout)
    dump_outputs(db, sys.stdout)
    dump_result_strings(db, sys.stdout)
    dump_results(db, sys.stdout)


def main():
    db = pg.connect(database=DB_NAME)
    with db:
        dump_all(db, sys.stdout)


if __name__ == '__main__':
    main()
