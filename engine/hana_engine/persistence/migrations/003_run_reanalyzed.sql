-- Persist how many files were re-read because the analyzers changed.
--
-- The pipeline already counted them, but the counter lived only in memory: the
-- run row had no column for it, so the number died with the process and the
-- interface could not tell the user "nothing you wrote changed, yet HANA read
-- eighty-six files again". Re-reading unchanged files is surprising enough that
-- it has to be visible, and separate from files_analyzed, which answers a
-- different question.

ALTER TABLE analysis_runs ADD COLUMN files_reanalyzed INTEGER NOT NULL DEFAULT 0;
