-- Ticket system schema
-- Safe to run multiple times (IF NOT EXISTS)

CREATE SCHEMA IF NOT EXISTS tickets;

CREATE TABLE IF NOT EXISTS tickets.settings (
    guild_id                BIGINT PRIMARY KEY,
    channel_id              BIGINT DEFAULT 0,
    message_id              BIGINT DEFAULT 0,
    max_tickets             INT,
    inactivity_timeout      INT,
    staff_role_ids          BIGINT[] DEFAULT '{}',
    blacklisted_ids         BIGINT[] DEFAULT '{}',
    transcript_destinations TEXT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tickets.open (
    id          TEXT NOT NULL,
    guild_id    BIGINT NOT NULL,
    channel_id  BIGINT NOT NULL UNIQUE,
    user_id     BIGINT NOT NULL,
    opened_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS tickets.button (
    id          TEXT NOT NULL,
    guild_id    BIGINT NOT NULL,
    category_id BIGINT,
    template    TEXT,
    topic       TEXT,
    style       TEXT DEFAULT 'green',
    emoji       TEXT,
    label       TEXT DEFAULT 'Open Ticket',
    PRIMARY KEY (guild_id, id)
);

CREATE TABLE IF NOT EXISTS tickets.dropdown (
    id          TEXT NOT NULL,
    guild_id    BIGINT NOT NULL,
    placeholder TEXT DEFAULT 'Select a category…',
    options     JSONB DEFAULT '[]',
    PRIMARY KEY (guild_id, id)
);

CREATE TABLE IF NOT EXISTS tickets.transcript (
    id          TEXT PRIMARY KEY,
    guild_id    BIGINT NOT NULL,
    channel_id  BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    messages    JSONB DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tickets_open_guild ON tickets.open (guild_id);
CREATE INDEX IF NOT EXISTS idx_tickets_open_channel ON tickets.open (channel_id);
CREATE INDEX IF NOT EXISTS idx_tickets_transcript_guild ON tickets.transcript (guild_id);
