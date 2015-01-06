import os

HOME = os.path.expanduser('~')

##### These are probably the most important variables to change:

# This directory does not itself affect anything, but is used in other
# configuration variables.
TOP = HOME + '/scratch/build/clang-triage'

# The directory to save the HTML report to
REPORT_DIR = HOME + '/public_html/clang-triage'

# Change to bzip2 if you don't have the (parallel) pbzip2
BZIP2_COMMAND = 'pbzip2'

##### You might get away without changing these:

# Name of postgresql database to connect to
DB_NAME = 'clang_triage'

# git repository directory
LLVM_SRC = TOP + '/llvm.src'

# build directory
BUILD = TOP + '/clang-triage.ninja'

# The filename of the actual XHTML report file under REPORT_DIR
REPORT_FILENAME = 'triage_report.xhtml'

# Parameters to give to ninja to build LLVM. For example, -j8 to run
# on 8 cores (the default is derived from number of cores available).
NINJA_PARAMS = []

# seconds; will wait additional this many seconds for it to terminate
# after SIGTERM and then kill it
CLANG_TIMEOUT = 4

# common for both triage and reduction
CLANG_PARAMS = ['-Werror', '-ferror-limit=5', '-std=c++11',
                '-fno-crash-diagnostics', '-xc++', '-c',
                '-o' '/dev/null', '-']

# Extra clang parameters to use when reducing. If you could disable
# some slow diagnostics, you could do it here.
REDUCTION_EXTRA_CLANG_PARAMS = []

# Extra clang parameters to use when triaging.
TRIAGE_EXTRA_CLANG_PARAMS = []

# A map from human-readable names to directories where to run git pull
PROJECTS = {'llvm': LLVM_SRC, 'clang': LLVM_SRC + '/tools/clang'}

# A map from projects to where to link source locations. An empty map
# is OK (no linking will be done).
SOURCE_URLS = {
    'llvm': 'https://github.com/llvm-mirror/llvm/blob/master/{path}#L{lineno}',
    'clang': 'https://github.com/llvm-mirror/clang/blob/master/{path}#L{lineno}'
}

# Path to binary to test
CLANG_BINARY = BUILD + '/bin/clang'

# Do not do git pull more often than this (seconds)
MIN_GIT_CHECKOUT_INTERVAL = 10*60

# Give creduce this long to complete before killing it
CREDUCE_TIMEOUT = 2*60 + 30

# Save miscellaneous reports in this dir (for example, outputs from
# failed clang runs where we couldn't determine the precise reason of
# failure)
MISC_REPORT_SAVE_DIR = 'saved'


##### Generally you should not need to change anything below this.


CREDUCE_PROPERTY_SCRIPT = 'check_creduce_property.py'

# This path is used to disable llvm-symbolizer. It should contain a
# symlink named llvm-symbolizer pointing to /bin/false.
DUMMY_LLVM_SYMBOLIZER_PATH = 'dummy-llvm-symbolizer'

# Postgresql command to create schema.
CREATE_SCHEMA_COMMAND = [
    'psql', '-v', 'ON_ERROR_STOP=1', '--quiet', '-d', DB_NAME,
    '-f', 'create_schema.sql']

# timeout from GNU coreutils
CLANG_TIMEOUT_CMD = ['timeout', '-k', str(CLANG_TIMEOUT), str(CLANG_TIMEOUT)]
