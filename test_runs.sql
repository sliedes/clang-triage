CREATE TABLE test_runs (
    id BIGINT PRIMARY KEY,
    start_time BIGINT NOT NULL,
    end_time BIGINT NOT NULL,
    clang_version INTEGER NOT NULL,
    llvm_version INTEGER NOT NULL);
CREATE INDEX test_runs_start_time ON test_runs(start_time);
CREATE UNIQUE INDEX test_runs_versions
    ON test_runs(clang_version, llvm_version);

CREATE TABLE result_strings (
    id BIGSERIAL PRIMARY KEY,
    str TEXT UNIQUE NOT NULL);

INSERT INTO result_strings (str) VALUES ('OK');

CREATE TABLE results (
    id BIGSERIAL PRIMARY KEY,
    case_id BIGINT NOT NULL,
    test_run BIGINT NOT NULL,
    result BIGINT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES case_contents(case_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY(test_run) REFERENCES test_runs(id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY(result) REFERENCES result_strings(id)
        ON UPDATE CASCADE ON DELETE CASCADE);
CREATE INDEX results_case_id ON results(case_id);
CREATE INDEX results_test_run ON results(test_run);
CREATE INDEX results_result ON results(result);
CREATE UNIQUE INDEX results_case_id_test_run ON results(case_id, test_run);

CREATE TABLE outputs (
   case_id BIGINT UNIQUE REFERENCES cases(id)
       ON UPDATE CASCADE ON DELETE CASCADE,
   output BYTEA NOT NULL);

CREATE VIEW results_view AS
    SELECT test_run, cases.id, sha1, str
    FROM result_strings AS res, results, cases
    WHERE results.case_id = cases.id
        AND results.result = res.id;

CREATE VIEW sha_output_view AS
    SELECT sha1, output
    FROM cases, outputs
    WHERE cases.id = outputs.case_id;
