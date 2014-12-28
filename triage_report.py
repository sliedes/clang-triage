#!/usr/bin/env python3

import psycopg2 as pg
import pystache
import time
from hashlib import sha1

from config import DB_NAME

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


def get_num_distinct_reduced(db):
    with db.cursor() as c:
        c.execute("SELECT COUNT(DISTINCT contents) " +
                  "FROM creduced_contents")
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


# FIXME reduced cases
def build_failure_context(reason, old_reason, cases, reduced=None):
    if reduced:
        cases = zip(cases, reduced)
    else:
        cases = [(x, None) for x in cases]
    ds = [case_dict(*case) for case in cases]
    ds[-1]['isLast'] = True
    num_cases = len(ds)
    ellipsis = False
    if num_cases > MAX_SHOW_CASES:
        ds = ds[:MAX_SHOW_CASES]
        ellipsis = True
    d = {'reason': reason, 'oldReason': old_reason, 'cases': ds,
         'numCases': num_cases, 'ellipsis': ellipsis}
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

    # move last cases which reduce to something already seen earlier
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


def group_changed_failures(changed_fails, reduced_dict, reduced_sizes):
    'changed_fails: [(sha1, reason, prev_reason)]'

    groups = {}
    for sha1, reason, prev_reason in changed_fails:
        rt = (reason, prev_reason)
        if not rt in groups:
            groups[rt] = []
        groups[rt].append(sha1)

    for x in groups:
        groups[x] = sort_cases(groups[x], reduced_dict, reduced_sizes)

    return sorted(groups.items(), key=lambda x: (x[0][1], x[0][0], x[1]))


class TestRun:
    def __init__(self, db, run_id, start_time, end_time, clang_ver, llvm_ver):
        self.db = db
        self.run_id = run_id
        self.start_time = start_time
        self.end_time = end_time
        self.clang_ver = clang_ver
        self.llvm_ver = llvm_ver
        self.fails_dict, self.reduced_dict, self.reduced_sizes = (
            fetch_failures(db, run_id))
        self.version = 'clang {}, llvm {}'.format(clang_ver, llvm_ver)

    def ctx(self, prev=None):
        prev_fails = {}
        prev_version = []
        if prev:
            prev_fails = prev.fails_dict
            prev_version = prev.version
        all_reasons = set(self.fails_dict.values())
        all_reasons -= set(['OK'])

        changed_fails = [
            (x[0], x[1], prev_fails[x[0]])
            for x in sorted(self.fails_dict.items())
            if x[0] in prev_fails and prev_fails[x[0]] != x[1]]

        # group changed failures by (old, new)
        changed_fails = group_changed_failures(
            changed_fails, self.reduced_dict, self.reduced_sizes)

        fails = [
            build_failure_context(
                x[0][0], x[0][1], x[1],
                [self.reduced_dict.get(y) for y in x[1]])
            for x in changed_fails]

        d = {'id': self.run_id,
             'date': asctime(time.localtime(self.start_time)),
             'duration': '{:d}'.format(self.end_time-self.start_time),
             'version': self.version, 'prevVersion': prev_version,
             'newFailures': fails,
             'numDistinctFailures': len(all_reasons),
             'endTime': asctime(time.localtime(self.end_time)),
             'anyChanged?': len(fails) > 0}
        return d


def main():
    with open('triage_report.pystache.xhtml') as f:
        TEMPLATE = pystache.parse(f.read())

    db = pg.connect('dbname=' + DB_NAME)
    with db:
        with db.cursor() as c:
            c.execute('SELECT id, start_time, end_time, clang_version, ' +
                      '    llvm_version ' +
                      'FROM test_runs ORDER BY start_time')
            res = c.fetchall()
        test_runs = []

        prev_run = None
        for run_id, start_time, end_time, clang_ver, llvm_ver in res:
            test_run = TestRun(db, run_id, start_time, end_time,
                               clang_ver, llvm_ver)
            test_runs.append(test_run.ctx(prev_run))
            prev_run = test_run
        last_run = prev_run

        test_runs = test_runs[::-1]
        with db.cursor() as c:
            c.execute('SELECT COUNT(*) FROM case_contents')
            num_inputs = c.fetchone()[0]

    assert test_runs, 'No test runs found.'
    num_runs_completed = len(test_runs)
    last_run_completed = test_runs[0]['endTime']

    context = {'testRuns': test_runs,
               'numRunsCompleted': num_runs_completed,
               'numInputs': num_inputs,
               'lastRunCompleted': last_run_completed,
               'reduceQueueSize': get_reduce_queue_size(db),
               'numReduced': get_num_reduced(db),
               'numDistinctReduced': get_num_distinct_reduced(db),
               'numReduceFailed': get_num_reduce_failed(db),
               'date': asctime()}

    # group failures by reason
    failures = {}
    for sha, reason in last_run.fails_dict.items():
        if not reason in failures:
            failures[reason] = []
        failures[reason].append(sha)

    if 'OK' in failures:
        del failures['OK']

    # sort cases by size of reduced, secondarily by sha1
    failures = [(x[0], sort_cases(x[1], last_run.reduced_dict,
                                  last_run.reduced_sizes))
                for x in failures.items()]
    # sort by number of test cases triggering the crash
    failures.sort(key=lambda x: len(x[1]), reverse=True)

    failures = [{'reason': x[0],
                 'cases': [case_dict(y, last_run.reduced_dict.get(y))
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
