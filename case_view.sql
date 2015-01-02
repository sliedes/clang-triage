-- cases, case_contents and case_sizes are 1:1.
CREATE TABLE cases (
    id BIGSERIAL PRIMARY KEY,
    sha1 TEXT UNIQUE NOT NULL);

CREATE TABLE case_contents (
    case_id BIGINT PRIMARY KEY REFERENCES cases (id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    z_contents BYTEA NOT NULL);

-- Establish a 1:1 relationship between cases and case_contents
ALTER TABLE cases ADD CONSTRAINT cases_id_forward_fkey
    FOREIGN KEY (id) REFERENCES case_contents (case_id) DEFERRABLE;

CREATE TABLE case_sizes (
    case_id BIGINT PRIMARY KEY,
    size INTEGER NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
        ON UPDATE CASCADE ON DELETE CASCADE);
CREATE INDEX case_sizes_size ON case_sizes(size);

-- 1:1 between case_sizes and case_contents (and thus cases)
ALTER TABLE case_contents ADD CONSTRAINT case_contents_case_id_forward_fkey
    FOREIGN KEY (case_id) REFERENCES case_sizes (case_id)
        ON UPDATE CASCADE ON DELETE CASCADE DEFERRABLE;

-- Inserts into and deletes from the three 1:1 case tables can be done
-- via case_view
CREATE VIEW case_view AS
    SELECT id, sha1, z_contents, size
    FROM cases, case_contents, case_sizes
    WHERE cases.id = case_contents.case_id AND cases.id = case_sizes.case_id;

CREATE FUNCTION case_view_insert_trigger_func() RETURNS trigger AS $$
DECLARE
  id BIGINT;
BEGIN
    SET CONSTRAINTS cases_id_forward_fkey,
        case_contents_case_id_forward_fkey DEFERRED;
    INSERT INTO cases (sha1) VALUES (NEW.sha1) RETURNING cases.id INTO id;
    INSERT INTO case_contents (case_id, z_contents)
        VALUES (id, NEW.z_contents);
    INSERT INTO case_sizes (case_id, size) VALUES (id, NEW.size);
    SET CONSTRAINTS cases_id_forward_fkey,
        case_contents_case_id_forward_fkey IMMEDIATE;
    RETURN NEW;
END; $$ LANGUAGE PLPGSQL;

CREATE TRIGGER case_view_insert_trigger
    INSTEAD OF INSERT ON case_view
    FOR EACH ROW EXECUTE PROCEDURE case_view_insert_trigger_func();

CREATE FUNCTION case_view_delete_trigger_func() RETURNS trigger AS $$
BEGIN
---- We now have ON DELETE CASCADE on almost everything
--    SET CONSTRAINTS cases_id_forward_fkey,
--        case_contents_case_id_forward_fkey DEFERRED;
    DELETE FROM case_sizes WHERE case_id=OLD.id;
--    DELETE FROM case_contents WHERE case_id=OLD.id;
--    DELETE FROM cases WHERE cases.id=OLD.id;
--    SET CONSTRAINTS cases_id_forward_fkey,
--        case_contents_case_id_forward_fkey IMMEDIATE;
    RETURN OLD;
END; $$ LANGUAGE PLPGSQL;

CREATE TRIGGER case_view_delete_trigger
    INSTEAD OF DELETE ON case_view
    FOR EACH ROW EXECUTE PROCEDURE case_view_delete_trigger_func();
