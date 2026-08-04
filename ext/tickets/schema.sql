-- Tickets schema auto-synced on cog load
CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    message_id BIGINT,
    max_tickets INT DEFAULT 1,
    inactivity_timeout INT,
    staff_role_ids JSONB DEFAULT '[]',
    blacklisted_ids JSONB DEFAULT '[]',
    transcript_destinations JSONB DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS ticket_buttons (
    id TEXT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    category_id BIGINT,
    template TEXT,
    topic TEXT,
    style TEXT DEFAULT 'blurple',
    emoji TEXT,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_dropdowns (
    id TEXT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    placeholder TEXT DEFAULT 'Select an option'
);

CREATE TABLE IF NOT EXISTS ticket_dropdown_options (
    id TEXT PRIMARY KEY,
    dropdown_id TEXT NOT NULL REFERENCES ticket_dropdowns(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    emoji TEXT,
    description TEXT,
    category_id BIGINT,
    template TEXT,
    topic TEXT
);
