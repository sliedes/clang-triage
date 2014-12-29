#!/usr/bin/python3
#
# Standalone, this can be used a dumb reducer of crashing test cases
# given as stdin.

from run_clang import test_input
import sys

SANITY_CHECKS = True


def remove_elem_iter(data, pred):
    if SANITY_CHECKS:
        assert pred(data)
    curr = 0
    elems_since_last = 0
    while elems_since_last < len(data) and data:
        n = data[:curr] + data[curr+1:]
        if pred(n):
            yield n
            data = n
            elems_since_last = 0
        else:
            curr += 1
            elems_since_last += 1
        if curr == len(data):
            curr = 0


def unlines(xs):
    return b'\n'.join(xs)


def compose(f, g):
    return lambda *rest, **kw: f(g(*rest, **kw))


def remove_lines(data, pred):
    data = data.split(b'\n')
    return (unlines(x)
            for x in remove_elem_iter(data, compose(pred, unlines)))


def remove_bytes(data, pred):
    return remove_elem_iter(data, pred)


def verbose_pred(reason):
    def pred(data):
        print(data, file=sys.stderr)
        return test_input(data)[0]
    return pred


def dumb_reduce(data, verbose=False):
    reason = test_input(data)[0]
    assert reason != 'OK'

    pred = lambda x: test_input(x)[0] == reason
    #pred = verbose_pred(reason)

    if verbose:
        print('Original case: {} bytes'.format(len(data)), file=sys.stderr)

    res = data
    for res in remove_lines(data, pred):
        if verbose:
            print('remove_lines: {} bytes'.format(len(res)), file=sys.stderr)
    data = res
    for res in remove_bytes(data, pred):
        if verbose:
            print('remove_bytes: {} bytes'.format(len(res)), file=sys.stderr)

    return res


def main():
    sys.stdout.buffer.write(dumb_reduce(sys.stdin.buffer.read(), verbose=True))


if __name__ == '__main__':
    main()
