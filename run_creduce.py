#!/usr/bin/env python3

import clang_triage as tri
import sys

def main():
    print(tri.run_creduce(sys.stdin.buffer.read()))

if __name__ == '__main__':
    main()
