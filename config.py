TOP = '/home/sliedes/scratch/build/clang-triage'

# git repository directory
LLVM_SRC = TOP + '/llvm.src'

# build directory
BUILD = TOP + '/clang-triage.ninja'

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

REDUCTION_EXTRA_CLANG_PARAMS = []
TRIAGE_EXTRA_CLANG_PARAMS = []

# A map from human-readable names to directories where to run git pull
PROJECTS = {'llvm': LLVM_SRC, 'clang': LLVM_SRC + '/tools/clang'}

# Path to tested binary
CLANG_BINARY = BUILD + '/bin/clang'

# Do not do git pull more often than this (seconds)
MIN_GIT_CHECKOUT_INTERVAL = 10*60

# Give creduce this long to complete before killing it
CREDUCE_TIMEOUT = 2*60 + 30

# Name of postgresql database to connect to
DB_NAME = 'clang_triage'

# Save miscellaneous reports in this dir (for example, outputs from
# failed clang runs where we couldn't determine the precise reason of
# failure)
MISC_REPORT_SAVE_DIR = 'saved'


# --- Generally you should not need to change anything below this.


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
