#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include <boost/algorithm/string.hpp>
#include <boost/functional/hash.hpp>

#include <sys/types.h>
#include <dirent.h>

using std::cerr;
using std::cout;
using std::endl;
using std::exit;
using std::ifstream;
using std::make_pair;
using std::ofstream;
using std::pair;
using std::string;
using std::stringstream;
using std::unordered_map;
using std::unordered_set;
using std::vector;

static const string TRACES_DIR = ".traces";

typedef pair<uint32_t, uint32_t> AflTuple;

class Dir {
    DIR *dir;
public:
    Dir(string path) {
	dir = opendir(path.c_str());
	if (!dir) {
	    cerr << "Failed to open directory " << path << endl;
	    exit(1);
	}
    }
    ~Dir() {
	closedir(dir);
    }
    operator DIR*() const { return dir; }
};

template<typename T>
using TupleMap = unordered_map<AflTuple, T, boost::hash<AflTuple>>;

typedef unordered_set<AflTuple, boost::hash<AflTuple>> TupleSet;

static vector<string> readDir(const string &path) {
    Dir dir(path);

    vector<string> names;
    
    struct dirent *de;
    errno = 0;
    while ((de = readdir(dir)))
	if (de->d_type == DT_REG)
	    names.push_back(de->d_name);

    return names;
}

static string readFile(const string &path) {
    std::ifstream f(path);
    if (!f) {
	cerr << "Failed to open " << path << "." << endl;
	exit(1);
    }

    stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static vector<AflTuple> loadTrace(const string &fname) {
    string PATH = TRACES_DIR + "/" + fname;

    string contents = readFile(PATH);

    vector<AflTuple> out;
    const char *c = contents.c_str();
    while (*c) {
	bool failed = false;
	uint32_t a, b;
	{
	    char *split;
	    errno = 0;
	    a = strtoll(c, &split, 10);
	    if (errno || split == c || *split != '/')
		failed = true;
	    else {
		char *end;
		b = strtoll(split+1, &end, 10);
		if (errno || end == split+1 || *end != '\n')
		    failed = true;
		else
		    c = end+1;
	    }
	}

	if (failed) {
	    cerr << "Malformed tuple in " << PATH << ": \"" << c << "\"" << endl;
	    exit(1);
	}

	out.push_back(make_pair(a, b));
    }
    return out;
}

static ifstream::pos_type getSize(const string &path) {
    ifstream f(path.c_str(), ifstream::ate);
    if (!f) {
	cerr << "Unable to open " << f << "." << endl;
	exit(1);
    }
    return f.tellg();
}

static void copyFile(const string &src, const string &dst) {
    string data = readFile(src);
    ofstream to(dst);
    to.write(data.c_str(), data.size());
}

int main(int argc, char **argv_) {
    vector<string> argv(argv_, argv_+argc);

    if (argv.size() != 2) {
	cerr << "Usage: " << argv[0] << " input_dir" << endl;
	cerr << "NOTE: This tool should not be invoked directly!" << endl;
	exit(1);
    }

    const string &IN_DIR = argv[1];
    const string OUT_DIR = IN_DIR + ".minimized";
    
    // check that the relevant directories exist.
    {
	Dir d1(IN_DIR), d2(OUT_DIR), d3(".traces");
    }
    
    auto filenames = readDir(".traces");
    std::sort(filenames.begin(), filenames.end());
    //filenames.resize(1000); // FIXME
    uint32_t numFiles = filenames.size();

    cerr << "[*] Loading trace sets..." << endl;

    TupleMap<uint32_t> allCounted;
    TupleMap<pair<uint32_t, size_t>> smallestForTuple; // size, file_n

    for (size_t i=0; i<numFiles; i++) {
	cerr << "\r    Processing file " << i+1 << "/" << numFiles << "..." << std::flush;
	uint32_t size = getSize(IN_DIR + "/" + filenames[i]);
	vector<AflTuple> tuples = loadTrace(filenames[i]);
	for (const auto &tup : tuples) {
	    // count
	    {
		auto it = allCounted.find(tup);
		if (it == allCounted.end())
		    allCounted[tup] = 1;
		else
		    it->second++;
	    }

	    // remember smallest
	    {
		auto it = smallestForTuple.find(tup);
		if (it == smallestForTuple.end())
		    smallestForTuple[tup] = make_pair(size, i);
		else {
		    auto oldSize = it->second.first;
		    if (oldSize > size)
			it->second = make_pair(size, i);
		}
	    }
	    	    
	}
    }

    cerr << "\n[*] Choosing trace sets..." << endl;
    vector<AflTuple> rarityOrder;
    rarityOrder.resize(allCounted.size());
    {
	vector<pair<AflTuple, uint32_t>> v(allCounted.begin(), allCounted.end());
	std::sort(v.begin(), v.end(),
		  [](const pair<AflTuple, uint32_t> &a, const pair<AflTuple, uint32_t> &b) {
		      return a.second < b.second;
		  });
	int i = 0;
	for (const auto &p : v)
	    rarityOrder[i++] = p.first;
    }

    TupleSet alreadyHave;
    unordered_set<size_t> chosenFiles;

    size_t numTuples = rarityOrder.size();

    for (size_t i=0; i<numTuples; i++) {
	auto tup = rarityOrder[i];
	bool have = alreadyHave.find(tup) != alreadyHave.end();
	if (i%1000 == 0 || !have) {
	    cerr << "\r    Processing tuple " << i+1 << "/" << numTuples
		 << ", currently have " << alreadyHave.size() << "/"
		 << numTuples << " in " << chosenFiles.size()
		 << " files... ";
	}

	if (have)
	    continue;

	auto it = smallestForTuple.find(tup);
	assert(it != smallestForTuple.end());
	auto fileNum = it->second.second;
	assert(chosenFiles.count(fileNum) == 0);
	chosenFiles.insert(fileNum);

	vector<AflTuple> tuples = loadTrace(filenames[fileNum]);
	assert(std::find(tuples.begin(), tuples.end(), tup) != tuples.end());
	alreadyHave.insert(tuples.begin(), tuples.end());

	if (chosenFiles.size() == numFiles)
	    break; // no sense in continuing, we already have the entire input set
    }

    cerr << "\n[*] Narrowed down to " << chosenFiles.size()
	 << " files, copying to '" << OUT_DIR << "'..." << endl;

    for (const auto &fnum : chosenFiles) {
	const string &fname = filenames[fnum];
	copyFile(IN_DIR + "/" + fname, OUT_DIR + "/" + fname);
    }

    cerr << "[+] Done." << endl;
}
