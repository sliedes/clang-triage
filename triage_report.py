#!/usr/bin/env python3

import psycopg2 as pg
import pystache, time, sys
from hashlib import sha1

from config import DB_NAME

DBNAME = 'clang_triage'

# show at most this many failing cases per reason
MAX_SHOW_CASES = 20

# RFC 2822
def asctime(t=None):
    fmt = '%a, %d %b %Y %H:%M:%S %z'
    if t is None:
        return time.strftime(fmt)
    else:
        return time.strftime(fmt, t)

def fetch_failures(db, run_id):
    with db.cursor() as c:
        c.execute('SELECT sha1, str, reduced ' +
                  'FROM failures_with_reduced_view ' +
                  'WHERE test_run=%s', (run_id, ))
        results = c.fetchall()
    fails_dict = dict([(x[0], x[1]) for x in results])
    reduced_dict = dict([(x[0], sha1(x[2]).hexdigest())
                         for x in results if x[2]])
    reduced_sizes = dict([(x[0], len(x[2]))
                          for x in results if x[2]])
    return fails_dict, reduced_dict, reduced_sizes

def get_reduce_queue_size(db):
    with db.cursor() as c:
        c.execute('SELECT COUNT(*) FROM unreduced_cases_view')
        return c.fetchone()[0]

def get_num_reduced(db):
    with db.cursor() as c:
        c.execute("SELECT COUNT(DISTINCT original) " +
                  "FROM creduced_cases WHERE result='ok'")
        return c.fetchone()[0]

def get_num_reduce_failed(db):
    with db.cursor() as c:
        c.execute("SELECT COUNT(DISTINCT original) " +
                  "FROM creduced_cases WHERE result='failed'")
        return c.fetchone()[0]

def case_dict(sha, reduced=None):
    d = {'case': sha, 'shortCase': sha[0:6],
         'url': 'sha/{}/{}/{}.cpp'.format(sha[0], sha[1], sha),
         'haveReduced': bool(reduced), 'isLast': False}
    if reduced:
        d['reducedUrl'] = 'cr/{}/{}/{}.cpp'.format(
            reduced[0], reduced[1], reduced)
    return d

def failure_dict(sha, reason, old_reason, reduced=None):
    d = case_dict(sha, reduced)
    d.update({'reason': reason, 'oldReason': old_reason})
    return d

def split_by(pred, xs):
    a = ([], [])

    for x in xs:
        a[bool(pred(x))].append(x)

    return a

def sort_cases(cases, reduced_dict, reduced_sizes):
    not_reduced, reduced = split_by(lambda x: x in reduced_dict, cases)
    not_reduced.sort()

    # sort reduced by size, sha
    reduced.sort(key=lambda x: (reduced_sizes[x], x))

    # move last cases which move to something already seen earlier
    unique_reduced = []
    duplicate_reduced = []
    seen = set()
    for x in reduced:
        red = reduced_dict[x]
        if red in seen:
            duplicate_reduced.append(x)
        else:
            seen.add(red)
            unique_reduced.append(x)

    return unique_reduced + not_reduced + duplicate_reduced

def main():
    with open('triage_report.pystache.xhtml') as f:
        TEMPLATE = pystache.parse(f.read())

    db = pg.connect('dbname=' + DBNAME)
    with db:
        with db.cursor() as c:
            c.execute('SELECT id, start_time, end_time, clang_version, llvm_version ' +
                      'FROM test_runs ORDER BY start_time')
            res = c.fetchall()
        test_runs = []
        old_fails = None
        prev_version = None
        for id_, start_time, end_time, clang_ver, llvm_ver in res:
            fails_dict, reduced_dict, reduced_sizes = fetch_failures(db, id_)
            all_reasons = set(fails_dict.values())
            all_reasons -= set(['OK'])
            # changed failures
            fails = [failure_dict(x[0], x[1], old_fails[x[0]],
                                  reduced_dict.get(x[0]))
                     for x in sorted(fails_dict.items())
                     if (not old_fails is None
                         and x[0] in old_fails
                         and old_fails[x[0]] != x[1])]
            old_fails = fails_dict
            version = 'clang {}, llvm {}'.format(clang_ver, llvm_ver)
            d = {'id': id_, 'date': asctime(time.localtime(start_time)),
                 'duration': '{:d}'.format(end_time-start_time),
                 'version': version, 'prevVersion': prev_version,
                 'newFailures': fails,
                 'numDistinctFailures': len(all_reasons),
                 'endTime': asctime(time.localtime(end_time)),
                 'anyChanged?': len(fails)>0}
            prev_version = version
            test_runs.append(d)

        test_runs = test_runs[::-1]
        with db.cursor() as c:
            c.execute('SELECT COUNT(*) FROM case_contents')
            num_inputs = c.fetchone()[0]

    num_runs_completed = len(test_runs)
    last_run_completed = test_runs[0]['endTime']

    context = {'testRuns': test_runs,
               'numRunsCompleted': num_runs_completed,
               'numInputs': num_inputs,
               'lastRunCompleted': last_run_completed,
               'reduceQueueSize': get_reduce_queue_size(db),
               'numReduced': get_num_reduced(db),
               'numReduceFailed': get_num_reduce_failed(db),
               'date': asctime()}

    # group failures by reason
    failures = {}
    for sha, reason in fails_dict.items():
        if not reason in failures:
            failures[reason] = []
        failures[reason].append(sha)

    if 'OK' in failures:
        del failures['OK']

    # sort cases by size of reduced, secondarily by sha1
    failures = [(x[0], sort_cases(x[1], reduced_dict, reduced_sizes))
                for x in failures.items()]
    # sort by number of test cases triggering the crash
    failures.sort(key=lambda x: len(x[1]), reverse=True)
    #print([(not z in reduced_dict,
    #        len(reduced_dict.get(z, '')), z)
    #       for z in failures[0][1]], file=sys.stderr)

    failures = [{'reason': x[0],
                 'cases': [case_dict(y, reduced_dict.get(y))
                           for y in x[1][:MAX_SHOW_CASES]],
                 'numCases': len(x[1]),
                 'plural': len(x[1]) != 1,
                 'ellipsis': len(x[1]) > MAX_SHOW_CASES}
                for x in failures]
    for f in failures:
        f['cases'][-1]['isLast'] = True

    context['failures'] = failures
    context['numDistinctFailures'] = len(failures)

    print(pystache.render(TEMPLATE, context))


if __name__ == '__main__':
    main()
