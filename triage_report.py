#!/usr/bin/env python3

# FIXME this module does not use TriageDb(). Perhaps it should be
# modified to, although the queries it does are rather separate from
# what other modules do.

import psycopg2 as pg
import pystache
import time
from hashlib import sha1
import zlib
import os
import subprocess as subp

from extract_cases import extract_cases
from extract_reduced import extract_reduced
from extract_outputs import extract_outputs

from config import DB_NAME, REPORT_DIR, BZIP2_COMMAND, REPORT_FILENAME

# show at most this many failing cases per reason
MAX_SHOW_CASES = 20

REPORT_DIR = os.path.abspath(REPORT_DIR)
REPORT_FILENAME = os.path.join(REPORT_DIR, REPORT_FILENAME)
SHA_DIR = os.path.join(REPORT_DIR, 'sha')
CR_DIR = os.path.join(REPORT_DIR, 'cr')
OUT_DIR = os.path.join(REPORT_DIR, 'out')
CASES_BZ2 = os.path.join(REPORT_DIR, 'all_cases.tar.bz2')
OUTPUTS_BZ2 = os.path.join(REPORT_DIR, 'all_outputs.tar.bz2')
REDUCED_BZ2 = os.path.join(REPORT_DIR, 'all_reduced.tar.bz2')


REDUCED_DICT = None
REDUCED_SHA_DICT = None
OUTPUT_SHA_DICT = None


def fetch_reduced_dict(db):
    'Get a {case_sha1: reduced_sha1} dictionary of all reduced cases.'

    global REDUCED_DICT, REDUCED_SHA_DICT
    with db.cursor() as c:
        c.execute('SELECT sha1, contents FROM sha_reduced_view ')
        REDUCED_DICT = dict(c.fetchall())
    REDUCED_SHA_DICT = dict((k, sha1(v).hexdigest())
                            for (k, v) in REDUCED_DICT.items())


def fetch_output_dict(db):
    'Get a {case_sha1: output_sha1} dictionary of all failed cases.'

    global OUTPUT_SHA_DICT
    with db.cursor() as c:
        c.execute('SELECT sha1, output FROM sha_output_view')
        OUTPUT_SHA_DICT = dict(
            (x[0], sha1(zlib.decompress(x[1])).hexdigest())
            for x in c.fetchall())


def asctime(t=None):
    'RFC 2822 format a time.'

    fmt = '%a, %d %b %Y %H:%M:%S %z'
    if t is None:
        return time.strftime(fmt)
    else:
        return time.strftime(fmt, t)


# FIXME this function is confusing (two return values), split it.
def fetch_failures(db, run_id):
    '''Fetch a {sha1: result_str} dict of results and a {sha1: size} dict
    of reduced sizes.'''

    with db.cursor() as c:
        c.execute('SELECT sha1, str FROM results_view ' +
                  'WHERE test_run=%s', (run_id, ))
        results = c.fetchall()
    fails_dict = dict([(x[0], x[1]) for x in results])
    reduced_sizes = dict([(x[0], len(REDUCED_DICT[x[0]]))
                          for x in results if x[0] in REDUCED_DICT])
    return fails_dict, reduced_sizes


def get_reduce_queue_size(db):
    'Get the number of items in reduce queue.'

    with db.cursor() as c:
        c.execute('SELECT COUNT(*) FROM unreduced_cases_view')
        return c.fetchone()[0]


def get_num_reduced(db):
    'Get the number of reduced items.'

    with db.cursor() as c:
        c.execute("SELECT COUNT(DISTINCT original) " +
                  "FROM reduced_cases " +
                  "WHERE result='ok' OR result='dumb'")
        return c.fetchone()[0]


def get_num_dumb_reduced(db):
    'Get the number of items reduced by dumb reduce after creduce failed.'

    with db.cursor() as c:
        c.execute("SELECT COUNT(DISTINCT original) " +
                  "FROM reduced_cases " +
                  "WHERE result='dumb'")
        return c.fetchone()[0]


def get_num_distinct_reduced(db):
    'Get the number of reduced cases that are distinct.'

    with db.cursor() as c:
        c.execute("SELECT COUNT(DISTINCT contents) " +
                  "FROM reduced_contents")
        return c.fetchone()[0]


def get_num_runs_completed(db):
    'Get the number of completed test runs.'

    with db.cursor() as c:
        c.execute("SELECT COUNT(*) " +
                  "FROM test_runs")
        return c.fetchone()[0]


def case_dict(sha):
    'Create a pystache context of a case.'

    reduced = REDUCED_SHA_DICT.get(sha)
    output = OUTPUT_SHA_DICT.get(sha)
    d = {'case': sha, 'shortCase': sha[0:6],
         'url': 'sha/{}/{}/{}.cpp'.format(sha[0], sha[1], sha),
         'haveReduced': bool(reduced), 'isLast': False,
         'haveOutput': bool(output)}
    if reduced:
        d['reducedUrl'] = 'cr/{}/{}/{}.cpp'.format(
            reduced[0], reduced[1], reduced)
    if output:
        d['outputUrl'] = 'out/{}/{}/{}.txt'.format(
            output[0], output[1], output)
    return d


def build_failure_context(reason, old_reason, cases):
    'Create a pystache context of a single type of failure change.'

    ds = [case_dict(case) for case in cases]
    ds[-1]['isLast'] = True
    num_cases = len(ds)
    ellipsis = False
    if num_cases > MAX_SHOW_CASES:
        ds = ds[:MAX_SHOW_CASES]
        ellipsis = True
    d = {'reason': reason, 'oldReason': old_reason, 'cases': ds,
         'numCases': num_cases, 'ellipsis': ellipsis}
    return d


# FIXME this name is confusable with python's string splits.
def split_by(pred, xs):
    '''Split a list into two by a predicate. The first list will contain
    those values for which pred is False and the second one those for
    which it is True.'''

    a = ([], [])

    for x in xs:
        a[bool(pred(x))].append(x)

    return a


def sort_cases(cases, reduced_sizes):
    '''Sort cases into presentation order: unique reduced + not_reduced +
    duplicate_reduced.'''

    not_reduced, reduced = split_by(lambda x: x in REDUCED_DICT, cases)
    not_reduced.sort()

    # sort reduced by size, sha
    reduced.sort(key=lambda x: (reduced_sizes[x], x))

    # move last cases which reduce to something already seen earlier
    unique_reduced = []
    duplicate_reduced = []
    seen = set()
    for x in reduced:
        red = REDUCED_DICT[x]
        if red in seen:
            duplicate_reduced.append(x)
        else:
            seen.add(red)
            unique_reduced.append(x)

    return unique_reduced + not_reduced + duplicate_reduced


def group_changed_failures(changed_fails, reduced_sizes):
    '''Group by (reason, prev_reason).
    changed_fails: [(sha1, reason, prev_reason)].'''

    groups = {}
    for sha, reason, prev_reason in changed_fails:
        rt = (reason, prev_reason)
        if not rt in groups:
            groups[rt] = []
        groups[rt].append(sha)

    for x in groups:
        groups[x] = sort_cases(groups[x], reduced_sizes)

    return sorted(groups.items(), key=lambda x: (x[0][1], x[0][0], x[1]))


class TestRun:
    'A container for data of a single test run.'

    def __init__(self, db, run_id, start_time, end_time, clang_ver, llvm_ver):
        self.db = db
        self.run_id = run_id
        self.start_time = start_time
        self.end_time = end_time
        self.clang_ver = clang_ver
        self.llvm_ver = llvm_ver
        self.fails_dict, self.reduced_sizes = fetch_failures(db, run_id)
        self.version = 'clang {}, llvm {}'.format(clang_ver, llvm_ver)

    def ctx(self, prev=None):
        'Create a pystache context of a test run.'

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
            changed_fails, self.reduced_sizes)

        fails = [build_failure_context(x[0][0], x[0][1], x[1])
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


def tar_bz2(cwd, tarball, path):
    'Create a .tar.bz of a path in a directory.'

    NEW_NAME = tarball + '.new'
    with open(NEW_NAME, 'wb') as newf:
        with subp.Popen(['tar', '-c', path], stdin=subp.DEVNULL,
                        stdout=subp.PIPE, cwd=cwd) as tar:
            subp.check_call([BZIP2_COMMAND], stdin=tar.stdout,
                            stdout=newf)
    os.rename(NEW_NAME, tarball)


def mk_report_dirs():
    'Create or refresh the report directory.'

    if not os.path.isdir(REPORT_DIR):
        os.mkdir(REPORT_DIR)

    # extract_cases() wouldn't actually need to be done after the
    # first time and after adding new cases...
    extract_cases(SHA_DIR)

    extract_reduced(CR_DIR)
    extract_outputs(OUT_DIR)

    tar_bz2(REPORT_DIR, CASES_BZ2, 'sha')
    tar_bz2(REPORT_DIR, REDUCED_BZ2, 'cr')
    tar_bz2(REPORT_DIR, OUTPUTS_BZ2, 'out')


def generate_report_as_string():
    'Generate an XHTML report.'

    with open('triage_report.pystache.xhtml') as f:
        TEMPLATE = pystache.parse(f.read())

    db = pg.connect(database=DB_NAME)
    with db:
        fetch_reduced_dict(db)
        fetch_output_dict(db)
        with db.cursor() as c:
            c.execute('SELECT id, start_time, end_time, clang_version, ' +
                      '    llvm_version ' +
                      'FROM test_runs ORDER BY start_time DESC LIMIT 60')
            res = c.fetchall()[::-1]
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
    last_run_completed = test_runs[0]['endTime']

    context = {'testRuns': test_runs,
               'numRunsCompleted': get_num_runs_completed(db),
               'numInputs': num_inputs,
               'lastRunCompleted': last_run_completed,
               'reduceQueueSize': get_reduce_queue_size(db),
               'numReduced': get_num_reduced(db),
               'numDistinctReduced': get_num_distinct_reduced(db),
               'numDumbReduced': get_num_dumb_reduced(db),
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
    failures = [(x[0], sort_cases(x[1], last_run.reduced_sizes))
                for x in failures.items()]
    # sort by number of test cases triggering the crash
    failures.sort(key=lambda x: len(x[1]), reverse=True)

    failures = [{'reason': x[0],
                 'cases': [case_dict(y)
                           for y in x[1][:MAX_SHOW_CASES]],
                 'numCases': len(x[1]),
                 'plural': len(x[1]) != 1,
                 'ellipsis': len(x[1]) > MAX_SHOW_CASES}
                for x in failures]
    for f in failures:
        f['cases'][-1]['isLast'] = True

    context['totalFailures'] = sum(x['numCases'] for x in failures)

    context['failures'] = failures
    context['numDistinctFailures'] = len(failures)

    return pystache.render(TEMPLATE, context)


def generate_report():
    'Generate an XHTML report and save it to REPORT_FILENAME.'

    NEW = REPORT_FILENAME + '.new'
    with open(NEW, 'w') as f:
        f.write(generate_report_as_string())
    os.rename(NEW, REPORT_FILENAME)


def refresh_report():
    'Create or refresh the report and its supporting files.'

    mk_report_dirs()
    generate_report()


def main():
    print(generate_report_as_string())


if __name__ == '__main__':
    main()
