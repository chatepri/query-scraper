-- View: per-(client, entity, prompt, model, grounding_mode) mention rollup.
-- This is the canonical aggregation layer. Dashboards and report generators
-- should query this view, not the raw tables.
DROP VIEW IF EXISTS v_mention_rollup;
CREATE VIEW v_mention_rollup AS
SELECT
    r.client_id,
    m.entity_name,
    m.entity_type,                      -- 'client' or 'competitor'
    r.prompt_id,
    r.prompt_text,
    r.model_name,
    r.model_id,
    r.grounding_mode,                   -- 'grounded' | 'ungrounded' | 'unknown'
    COUNT(*) AS response_count,         -- # of times this prompt has been run against this model
    SUM(CASE WHEN m.is_mentioned THEN 1 ELSE 0 END) AS responses_with_mention,
    SUM(COALESCE(m.mention_count, 0)) AS total_mentions,
    AVG(COALESCE(m.mention_count, 0)) AS avg_mentions_per_response,
    AVG(CASE WHEN m.is_mentioned THEN 1.0 ELSE 0.0 END) AS mention_rate,
    AVG(m.position) AS avg_position,    -- NULL-aware in SQLite; only averages non-null positions
    MIN(r.created_at) AS first_seen,    -- rename to run_timestamp if you added that column
    MAX(r.created_at) AS last_seen
FROM mentions m
JOIN responses r ON m.response_id = r.id
GROUP BY
    r.client_id, m.entity_name, m.entity_type,
    r.prompt_id, r.model_name, r.grounding_mode;

-- Secondary view: the headline "visibility delta" — knowledge presence vs.
-- visibility for the same (client, entity, prompt, model) pair.
-- This is the metric Section 5 Finding 4 of the handoff identified as
-- the most valuable client insight.
DROP VIEW IF EXISTS v_grounding_delta;
CREATE VIEW v_grounding_delta AS
SELECT
    g.client_id,
    g.entity_name,
    g.prompt_id,
    g.model_name,
    g.mention_rate AS grounded_mention_rate,
    u.mention_rate AS ungrounded_mention_rate,
    (g.mention_rate - u.mention_rate) AS visibility_minus_knowledge_delta,
    g.total_mentions AS grounded_total_mentions,
    u.total_mentions AS ungrounded_total_mentions
FROM v_mention_rollup g
LEFT JOIN v_mention_rollup u
  ON g.client_id = u.client_id
 AND g.entity_name = u.entity_name
 AND g.prompt_id = u.prompt_id
 AND g.model_name = u.model_name
 AND u.grounding_mode = 'ungrounded'
WHERE g.grounding_mode = 'grounded';