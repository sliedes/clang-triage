#!/bin/bash

set -e

./triage_report.py >t.t
mv t.t ~/public_html/clang-triage/triage_report.xhtml

./extract_creduced.py
rm -f all_reduced.tar.bz2
tar c cr/ |pbzip2 >all_reduced.tar.bz2
mv all_reduced.tar.bz2 ~/public_html/clang-triage/

./extract_outputs.py
rm -f all_outputs.tar.bz2
tar c cr/ |pbzip2 >all_outputs.tar.bz2
mv all_outputs.tar.bz2 ~/public_html/clang-triage/
