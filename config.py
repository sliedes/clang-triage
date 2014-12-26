TOP = '/home/sliedes/scratch/build/clang-triage'

# git repository directory
LLVM_SRC = TOP + '/llvm.src'

# build directory
BUILD = TOP + '/clang-triage.ninja'

# Where triage_db.py should get test cases from
POPULATE_FROM = '/home/sliedes/scratch/afl/cases.minimized'

NINJA_PARAMS = ['-j8']

# timeout from GNU coreutils
TIMEOUT_CMD = ['timeout', '-k', '4', '4']

CLANG_PARAMS = ['-Werror', '-ferror-limit=5', '-std=c++11',
                '-fno-crash-diagnostics', '-xc++', '-c',
                '-o' '/dev/null', '-']

# A map from human-readable names to directories where to run git pull
PROJECTS = {'llvm' : LLVM_SRC, 'clang' : LLVM_SRC + '/tools/clang'}

# Path to tested binary
CLANG_BINARY = BUILD + '/bin/clang'

# Do not do git pull more often than this (seconds)
MIN_GIT_CHECKOUT_INTERVAL = 10*60

# Give creduce this long to complete before killing it
CREDUCE_TIMEOUT = 4*60

# Name of postgresql database to connect to
DB_NAME = 'clang_triage'

# Save miscellaneous reports in this dir (for example, outputs from
# failed clang runs where we couldn't determine the precise reason of
# failure)
MISC_REPORT_SAVE_DIR = 'saved'

CREDUCE_PROPERTY_SCRIPT = 'check_creduce_property.py'
