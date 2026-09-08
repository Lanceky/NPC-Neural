CREATE TABLE IF NOT EXISTS npcs (
    npc_id String,
    name String,
    tier Enum8('principal' = 1, 'background' = 2),
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY npc_id;

CREATE TABLE IF NOT EXISTS context_ticks (
    tick_id UUID DEFAULT generateUUIDv4(),
    npc_id String,
    ts DateTime64(3) DEFAULT now64(3),
    tier Enum8('principal' = 1, 'background' = 2),
    context_snippet String,
    goal String
) ENGINE = MergeTree ORDER BY (npc_id, ts);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id UUID DEFAULT generateUUIDv4(),
    npc_id String,
    ts DateTime64(3) DEFAULT now64(3),
    reasoning String,
    action String,
    mood String
) ENGINE = MergeTree ORDER BY (npc_id, ts);

CREATE TABLE IF NOT EXISTS events (
    event_id UUID DEFAULT generateUUIDv4(),
    npc_id String,
    ts DateTime64(3) DEFAULT now64(3),
    event_type String,
    payload String
) ENGINE = MergeTree ORDER BY (npc_id, ts);
