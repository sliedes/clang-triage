#!/usr/bin/env python3

from triage_db import DB_NAME
import psycopg2 as pg
import pystache, time, sys

DBNAME = 'clang_triage'

# show at most this many failing cases per reason
MAX_SHOW_CASES = 20

def fetch_failures(cursor, run_id):
    c = cursor
    c.execute('SELECT cases.sha1, result_strings.str ' +
              'FROM cases, result_strings, results ' +
              'WHERE results.case_id=cases.id AND results.test_run=%s ' +
              '    AND result_strings.id=results.result ', (run_id, ))
    return dict(c.fetchall())

def case_dict(sha):
    return {'case': sha, 'shortCase': sha[0:6],
            'url': 'sha/{}/{}/{}.cpp'.format(sha[0], sha[1], sha)}

def failure_dict(sha, reason, old_reason):
    d = case_dict(sha)
    d.update({'reason': reason, 'oldReason': old_reason})
    return d

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
                fails_dict = fetch_failures(c, id_)
                # changed failures
                fails = [failure_dict(x[0], x[1], old_fails[x[0]])
                         for x in sorted(fails_dict.items())
                         if (not old_fails is None
                             and x[0] in old_fails
                             and old_fails[x[0]] != x[1])]
                #print((id_, fails), file=sys.stderr)
                #print(fails_dict['691c2999aed7b4b2ef5389b3775497c198a11a87'],
                #      file=sys.stderr)
                old_fails = fails_dict
                version = 'clang {}, llvm {}'.format(clang_ver, llvm_ver)
                d = {'id': id_, 'date': time.asctime(time.gmtime(start_time)),
                     'duration': '{:d}'.format(end_time-start_time),
                     'version': version, 'prevVersion': prev_version,
                     'newFailures': fails,
                     'endTime': time.asctime(time.gmtime(end_time)),
                     'anyChanged?': len(fails)>0}
                prev_version = version
                test_runs.append(d)

            test_runs = test_runs[::-1]
            c.execute('SELECT COUNT(*) FROM cases')
            num_inputs = c.fetchone()[0]

    num_runs_completed = len(test_runs)
    last_run_completed = test_runs[0]['endTime']

    # only show test runs with changed results, except for the newest one
    #test_runs[1:] = [x for x in test_runs[1:] if x['newFailures']]

    context = {'testRuns': test_runs,
               'numRunsCompleted': num_runs_completed,
               'numInputs': num_inputs,
               'lastRunCompleted': last_run_completed}

    # group failures by reason
    failures = {}
    for sha, reason in fails_dict.items():
        if not reason in failures:
            failures[reason] = []
        failures[reason].append(sha)

    if 'OK' in failures:
        del failures['OK']

    # sort cases by sha1
    failures = [(x[0], sorted(x[1])) for x in failures.items()]
    # sort by number of test cases triggering the crash
    failures.sort(key=lambda x: len(x[1]), reverse=True)

    failures = [{'reason': x[0],
                 'cases': [case_dict(y) for y in x[1][:MAX_SHOW_CASES]],
                 'numCases': len(x[1]),
                 'plural': len(x[1]) != 1,
                 'ellipsis': len(x[1]) > MAX_SHOW_CASES}
                for x in failures]
    context['failures'] = failures

    context['numDistinctFailures'] = len(failures)

    print(pystache.render(TEMPLATE, context))


if __name__ == '__main__':
    main()
