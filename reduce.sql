CREATE TYPE reduce_result AS ENUM ('ok', 'dumb', 'no_crash');

CREATE TABLE reduced_cases (
    id BIGSERIAL PRIMARY KEY,
    original BIGINT UNIQUE NOT NULL REFERENCES cases(id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    clang_version INTEGER NOT NULL,
    llvm_version INTEGER NOT NULL,
    result reduce_result NOT NULL);
CREATE UNIQUE INDEX reduced_cases_original_versions_unique
ON reduced_cases (original, clang_version, llvm_version);

CREATE TABLE reduced_contents (
    reduced_id BIGINT NOT NULL
        REFERENCES reduced_cases(id) ON UPDATE CASCADE ON DELETE CASCADE,
    contents BYTEA NOT NULL);

CREATE VIEW unreduced_cases_view AS
    SELECT sha1, z_contents
    FROM case_view AS cv
    WHERE NOT EXISTS (
        SELECT * FROM reduced_cases AS red
        WHERE red.original = cv.id);

CREATE VIEW sha_reduced_view AS
    SELECT sha1, contents
    FROM cases, reduced_cases, reduced_contents
    WHERE cases.id = reduced_cases.original
        AND reduced_cases.id = reduced_contents.reduced_id;
