CXXFLAGS=-O3 -g -Wall -std=c++11
LDFLAGS=

min-traces: min-traces.cpp
	~/local/llvm-3.5/bin/clang++ min-traces.cpp -o min-traces $(CXXFLAGS) $(LDFLAGS)
