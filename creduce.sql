CREATE TYPE creduce_result AS ENUM ('ok', 'dumb', 'no_crash');

CREATE TABLE creduced_cases (
    id BIGSERIAL PRIMARY KEY,
    original BIGINT UNIQUE NOT NULL REFERENCES cases(id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    clang_version INTEGER NOT NULL,
    llvm_version INTEGER NOT NULL,
    result creduce_result NOT NULL);
CREATE UNIQUE INDEX creduced_cases_original_versions_unique
ON creduced_cases (original, clang_version, llvm_version);

CREATE TABLE creduced_contents (
    creduced_id BIGINT NOT NULL
        REFERENCES creduced_cases(id) ON UPDATE CASCADE ON DELETE CASCADE,
    contents BYTEA NOT NULL);

CREATE VIEW unreduced_cases_view AS
    SELECT sha1, z_contents
    FROM case_view AS cv
    WHERE NOT EXISTS (
        SELECT * FROM creduced_cases AS red
        WHERE red.original = cv.id);

CREATE VIEW sha_reduced_view AS
    SELECT sha1, contents
    FROM cases, creduced_cases, creduced_contents
    WHERE cases.id = creduced_cases.original
        AND creduced_cases.id = creduced_contents.creduced_id;
