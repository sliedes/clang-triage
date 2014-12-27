#!/usr/bin/env python3

import sys
import resource
import shutil
import os

from collections import Counter

ULIMIT_V = int(1e6)
PARAMS = []


def fatal(s, exitcode=1):
    print(s, file=sys.stderr)
    sys.exit(exitcode)


def assert_executable(fname):
    if not (os.path.isfile(fname) and
            os.access(fname, os.X_OK)):
        fatal("Error: Binary '%s' not found or is not executable." % fname)


def assert_dir(path):
    if not (os.path.isdir(path)):
        fatal("Error: Directory '%s' not found." % path)


def load_trace_pandas(fname):
    p = pandas.read_csv('.traces/' + fname, delimiter='/', header=None,
                        dtype=int)
    #return map(tuple, p.to_records(index=False))
    return list(p.itertuples(index=False))


def load_trace_no_pandas(fname):
    tuples = []
    with open('.traces/' + fname) as f:
        for line in f:
            a, b = map(int, line.rstrip().split('/'))
            tuples.append((a, b))
    return tuples


# We use read_csv from pandas because python is too slow...
try:
    import pandas
    load_trace = load_trace_pandas
except ImportError:
    print('Warning: Failed to import pandas. This will be slower...')
    load_trace = load_trace_no_pandas


def save_trace(fname, tuples):
    with open('.traces/{}'.format(fname), 'w') as f:
        for a, b in tuples:
            print('{:#05d}/{:d}'.format(a, b), file=f)


def exec_showmap(path):
    # FIXME
    NAME = os.path.split(path)[1]
    assert NAME
    return load_trace(NAME)

    #env = copy.copy(os.environ)
    #env['AFL_SINK_OUTPUT'] = '1'
    #env['AFL_QUIET'] = '1'


def find_showmap():
    '''Try to find afl-showmap in AFL_PATH or, if unset, in $PATH.'''
    global SHOWMAP
    if 'AFL_PATH' in os.environ:
        SHOWMAP = os.path.join(os.environ['AFL_PATH'], 'afl-showmap')
    else:
        SHOWMAP = shutil.which('afl-showmap')

    if not SHOWMAP:
        fatal("Error: Cannot find 'afl-showmap' - please set AFL_PATH.")


def set_limits():
    resource.setrlimit(resource.RLIMIT_VMEM, ULIMIT_V)


USAGE_STR = '''
Usage: {argv[0]} /path/to/corpus_dir /path/to/tested_binary

Note: The tested binary must accept input on stdin and require no additional
parameters. For more complex use cases, you need to edit this script.
'''.strip().format(argv=sys.argv)


def main():
    if len(sys.argv) != 3:
        fatal(USAGE_STR)

    DIR, BIN = sys.argv[1:3]

    assert_executable(BIN)
    assert_dir(DIR)
    find_showmap()

    FILES = sorted(os.listdir(DIR))
    FILES = FILES[:1000]
    if not FILES:
        fatal('No inputs in the target directory - nothing to be done.',
              exitcode=0)

    #if os.path.exists('.traces'):
    #    shutil.rmtree('.traces')
    #os.mkdir('.traces')

    # FIXME support for AFL_EDGES_ONLY?
    OUT_DIR = DIR + ".minimized"

    #if os.path.exists(OUT_DIR):
    #    shutil.rmtree(OUT_DIR)
    #os.mkdir(OUT_DIR)

    print('[*] Evaluating {} input files (this may take a while)...'.format(
        len(FILES)))

    all_counted = Counter()
    smallest_input_for_tuple = {}
    for i, fname in enumerate(FILES):
        print('\r    Processing file {cur}/{count}... '.format(
            cur=i+1, count=len(FILES)), end='')
        REL_FNAME = os.path.join(DIR, fname)
        SIZE = os.path.getsize(REL_FNAME)
        tuples = exec_showmap(REL_FNAME)
        all_counted.update(tuples)
        for t in tuples:
            if (not t in smallest_input_for_tuple or
                    smallest_input_for_tuple[t][0] > SIZE):
                smallest_input_for_tuple[t] = (SIZE, i)

    print()
    print('[*] Choosing trace sets...')
    RARITY_ORDER = [x[0] for x in all_counted.most_common()][::-1]
    already_have = set()
    chosen_files = set()
    for i, tup in enumerate(RARITY_ORDER):
        if (i % 1000 == 0 or not tup in already_have):
            print(('\r    Processing tuple {curr}/{total}, currently have ' +
                   '{curr_have}/{total} in {files} files... ').format(
                curr=i+1, total=len(RARITY_ORDER),
                curr_have=len(already_have), files=len(chosen_files)),
                end='')
        if not tup in already_have:
            size, file_n = smallest_input_for_tuple[tup]
            assert not file_n in chosen_files
            chosen_files.add(file_n)
            already_have.update(load_trace(FILES[file_n]))
            print('Chose {file_n} for {tup[0]}/{tup[1]}'.format(
                file_n=file_n, fname=FILES[file_n], tup=tup))
        if len(chosen_files) == len(FILES):
            # no sense in continuing, we already have the entire input set
            break
    print()

    print("[*] Narrowed down to {count} files, copying to " +
          "'{out_dir}'...".format(count=len(chosen_files), out_dir=OUT_DIR))
    #for file_i in chosen_files:
    #    shutil.copy(os.path.join(DIR, FILES[file_i]), OUT_DIR)

    #shutil.rmtree('.traces')
    print("[+] Done.")


if __name__ == '__main__':
    main()
