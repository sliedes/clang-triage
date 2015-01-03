\i case_view.sql
\i reduce.sql
\i test_runs.sql

CREATE VIEW last_2_runs_view AS
    SELECT id FROM test_runs
    ORDER BY id DESC LIMIT 2;

CREATE VIEW last_run_results AS
    SELECT * FROM results
    WHERE test_run=(SELECT MAX(id) FROM last_2_runs_view);

CREATE VIEW second_last_run_results AS
    SELECT * FROM results
    WHERE test_run=(SELECT MIN(id) FROM last_2_runs_view);

CREATE VIEW changed_results AS
    SELECT last.id AS id1, second.id AS id2, last.case_id,
        last.result AS new, second.result AS old
    FROM last_run_results AS last, second_last_run_results AS second
    WHERE last.case_id=second.case_id AND last.result<>second.result;
