TOP = '/home/sliedes/scratch/build/clang-triage'
LLVM_SRC = TOP + '/llvm.src'
BUILD = TOP + '/clang-triage.ninja'
TEST_CASE_DIR = '/home/sliedes/scratch/afl/cases.minimized'

NINJA_PARAMS = ['-j8']

TIMEOUT_CMD = ['timeout', '-k', '4', '4']

CLANG_PARAMS = ['-Werror', '-ferror-limit=5', '-std=c++11',
                '-fno-crash-diagnostics', '-xc++', '-c',
                '-o' '/dev/null', '-']

PROJECTS = {'llvm' : LLVM_SRC, 'clang' : LLVM_SRC + '/tools/clang'}
CLANG_BINARY = BUILD + '/bin/clang'

CREDUCE_PROPERTY_SCRIPT = 'check_creduce_property.py'

MIN_GIT_CHECKOUT_INTERVAL = 10*60 # seconds
CREDUCE_TIMEOUT = 4*60

REPORT_SAVE_DIR = 'saved'
