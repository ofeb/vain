CREATE TABLE IF NOT EXISTS guilds (
    guild_id BIGINT PRIMARY KEY,
    prefix VARCHAR(10) DEFAULT ';',
    language VARCHAR(5) DEFAULT 'en',
    muted_role_id BIGINT,
    auto_role_id BIGINT,
    welcome_channel_id BIGINT,
    welcome_message TEXT,
    leave_channel_id BIGINT,
    leave_message TEXT,
    boost_channel_id BIGINT,
    boost_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config (
    guild_id BIGINT PRIMARY KEY,
    prefixes TEXT[] NOT NULL DEFAULT ARRAY[',']::TEXT[],
    colorme BOOLEAN DEFAULT FALSE,
    colorme_base BIGINT,
    lastfm_reactions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS self_prefix (
    user_id BIGINT PRIMARY KEY,
    prefix VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blacklist (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    guild_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS disabled_commands (
    guild_id BIGINT,
    command VARCHAR(100),
    object_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    object_types TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, command)
);

CREATE TABLE IF NOT EXISTS disabled_events (
    guild_id BIGINT,
    event VARCHAR(100),
    channel_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, event)
);

CREATE TABLE IF NOT EXISTS disabled_modules (
    guild_id BIGINT,
    module VARCHAR(100),
    channel_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, module)
);

CREATE TABLE IF NOT EXISTS antinuke (
    guild_id BIGINT PRIMARY KEY,
    whitelist BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    admins BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    botadd JSONB NOT NULL DEFAULT '{}'::JSONB,
    webhook JSONB NOT NULL DEFAULT '{}'::JSONB,
    emoji JSONB NOT NULL DEFAULT '{}'::JSONB,
    ban JSONB NOT NULL DEFAULT '{}'::JSONB,
    kick JSONB NOT NULL DEFAULT '{}'::JSONB,
    channel JSONB NOT NULL DEFAULT '{}'::JSONB,
    role JSONB NOT NULL DEFAULT '{}'::JSONB,
    vanity JSONB NOT NULL DEFAULT '{}'::JSONB,
    permissions JSONB[] NOT NULL DEFAULT ARRAY[]::JSONB[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antinuke_actions (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    action VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antiraid_config (
    guild_id BIGINT PRIMARY KEY,
    raid_active BOOLEAN NOT NULL DEFAULT FALSE,
    punish_until TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antiraid_modules (
    guild_id BIGINT NOT NULL,
    module VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    threshold INT NOT NULL DEFAULT 5,
    action VARCHAR(16) NOT NULL DEFAULT 'ban',
    lock_channels BOOLEAN NOT NULL DEFAULT FALSE,
    punish_new BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, module)
);

CREATE TABLE IF NOT EXISTS antiraid_whitelist (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS antiraid_locked_channels (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS suggest_settings (
    guild_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    channel_id BIGINT,
    review_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    review_channel_id BIGINT,
    threads_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    upvote_emoji TEXT NOT NULL DEFAULT chr(9989),
    downvote_emoji TEXT NOT NULL DEFAULT chr(10060),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suggest_counters (
    guild_id BIGINT PRIMARY KEY,
    next_id BIGINT NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suggestions (
    guild_id BIGINT NOT NULL,
    suggestion_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    channel_id BIGINT,
    message_id BIGINT,
    review_channel_id BIGINT,
    review_message_id BIGINT,
    thread_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, suggestion_id)
);

CREATE TABLE IF NOT EXISTS suggest_ignored (
    guild_id BIGINT NOT NULL,
    target_id BIGINT NOT NULL,
    target_type TEXT NOT NULL,
    added_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, target_id, target_type)
);

CREATE TABLE IF NOT EXISTS suggest_votes (
    guild_id BIGINT NOT NULL,
    suggestion_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    vote TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, suggestion_id, user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_message
    ON suggestions(guild_id, message_id)
    WHERE message_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_review_message
    ON suggestions(guild_id, review_message_id)
    WHERE review_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS webhooks (
    guild_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    channel_id BIGINT NOT NULL,
    webhook_id BIGINT NOT NULL,
    token TEXT NOT NULL,
    owner_id BIGINT NOT NULL,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS server_settings (
    guild_id BIGINT PRIMARY KEY,
    jail_channel_id BIGINT,
    jail_role_id BIGINT,
    jail_message_channel_id BIGINT,
    muted_role_id BIGINT,
    imuted_role_id BIGINT,
    rmuted_role_id BIGINT,
    member_base_role_id BIGINT,
    autonick TEXT,
    dj_role_id BIGINT,
    premium_role_id BIGINT,
    joinlog_channel_id BIGINT,
    google_safety_level BOOLEAN DEFAULT FALSE,
    disable_custom_fms BOOLEAN DEFAULT FALSE,
    autoplay TEXT,
    jail_message TEXT,
    jail_remove_roles BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staff_roles (
    guild_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS modlog_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS modlog_cases (
    guild_id BIGINT NOT NULL,
    case_id INT NOT NULL,
    action VARCHAR(64) NOT NULL,
    target_id BIGINT,
    moderator_id BIGINT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, case_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT,
    guild_id BIGINT,
    balance BIGINT DEFAULT 0,
    xp BIGINT DEFAULT 0,
    level INT DEFAULT 0,
    warnings INT DEFAULT 0,
    muted_until TIMESTAMP,
    birthday VARCHAR(20),
    timezone VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS moderation (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    moderator_id BIGINT,
    action_type VARCHAR(20),
    reason TEXT,
    duration VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS highlights (
    guild_id BIGINT,
    user_id BIGINT,
    keyword VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, keyword)
);

CREATE TABLE IF NOT EXISTS highlight_ignores (
    guild_id BIGINT,
    user_id BIGINT,
    target_id BIGINT,
    target_type VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, target_id, target_type)
);

CREATE TABLE IF NOT EXISTS sticky_roles (
    guild_id BIGINT,
    user_id BIGINT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, role_id)
);

CREATE TABLE IF NOT EXISTS booster_roles (
    guild_id BIGINT PRIMARY KEY,
    base_id BIGINT,
    award_id BIGINT,
    role_limit INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE booster_roles
    ADD COLUMN IF NOT EXISTS base_id BIGINT;

ALTER TABLE booster_roles
    ADD COLUMN IF NOT EXISTS award_id BIGINT;

ALTER TABLE booster_roles
    ADD COLUMN IF NOT EXISTS role_limit INT;

CREATE TABLE IF NOT EXISTS custom_roles (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_roles_guild_role
    ON custom_roles(guild_id, role_id);

CREATE TABLE IF NOT EXISTS forced_nicknames (
    guild_id BIGINT,
    user_id BIGINT,
    nickname VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS command_restrictions (
    guild_id BIGINT,
    command VARCHAR(50),
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, command, role_id)
);

CREATE TABLE IF NOT EXISTS color_roles (
    guild_id BIGINT PRIMARY KEY,
    roles TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roblox_links (
    discord_id BIGINT PRIMARY KEY,
    roblox_id BIGINT,
    username VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS snapchat_links (
    discord_id BIGINT PRIMARY KEY,
    snapchat_username VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    guild_id BIGINT,
    message TEXT,
    time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    moderator_id BIGINT,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS proofs (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    moderator_id BIGINT,
    case_id INT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auto_reactions (
    guild_id BIGINT,
    trigger VARCHAR(255),
    response TEXT[],
    owner_id BIGINT,
    strict BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger, response)
);

CREATE TABLE IF NOT EXISTS reaction_history (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    user_id BIGINT,
    reaction VARCHAR(255),
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auto_role (
    guild_id BIGINT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS button_roles (
    guild_id BIGINT,
    message_id BIGINT,
    channel_id BIGINT,
    role_id BIGINT,
    style VARCHAR(20),
    emoji VARCHAR(255),
    label VARCHAR(100),
    index INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reaction_role (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    emoji VARCHAR(255),
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, role_id)
);

CREATE TABLE IF NOT EXISTS giveaways (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    prize VARCHAR(255),
    expiration TIMESTAMP,
    winner_count INT DEFAULT 1,
    hosts BIGINT[],
    entries BIGINT[],
    max_level INT,
    min_level INT,
    required_roles BIGINT[],
    win_message_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (message_id)
);

CREATE TABLE IF NOT EXISTS counters (
    guild_id BIGINT,
    channel_id BIGINT,
    counter_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, counter_type)
);

CREATE TABLE IF NOT EXISTS clownboard (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    emoji VARCHAR(255),
    threshold INT DEFAULT 1,
    lock BOOLEAN DEFAULT FALSE,
    ignore_entries TEXT,
    attachments BOOLEAN DEFAULT FALSE,
    ts BOOLEAN DEFAULT FALSE,
    jump BOOLEAN DEFAULT FALSE,
    self_star BOOLEAN DEFAULT TRUE,
    color VARCHAR(6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clownboard_entries (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    emoji VARCHAR(255),
    clownboard_message_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, emoji)
);

CREATE TABLE IF NOT EXISTS starboard (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    emoji VARCHAR(255),
    threshold INT DEFAULT 1,
    lock BOOLEAN DEFAULT FALSE,
    ignore_entries TEXT,
    attachments BOOLEAN DEFAULT FALSE,
    ts BOOLEAN DEFAULT FALSE,
    jump BOOLEAN DEFAULT FALSE,
    self_star BOOLEAN DEFAULT TRUE,
    color VARCHAR(6),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS starboard_entries (
    guild_id BIGINT,
    channel_id BIGINT,
    message_id BIGINT,
    emoji VARCHAR(255),
    starboard_message_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, emoji)
);

CREATE TABLE IF NOT EXISTS voicemaster_configuration (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    category_id BIGINT,
    role_id BIGINT,
    bitrate INT,
    region VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voicemaster_channels (
    guild_id BIGINT,
    channel_id BIGINT,
    owner_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_id)
);

CREATE TABLE IF NOT EXISTS tictactoe (
    user_id BIGINT PRIMARY KEY,
    wins INT DEFAULT 0,
    losses INT DEFAULT 0,
    ties INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS birthday (
    user_id BIGINT,
    guild_id BIGINT,
    birthday_date DATE,
    timezone VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS birthday_notifications (
    guild_id BIGINT,
    channel_id BIGINT,
    message TEXT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS level_config (
    guild_id BIGINT PRIMARY KEY,
    enabled BOOLEAN DEFAULT TRUE,
    multiplier INT DEFAULT 1,
    message TEXT,
    role_rewards JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id BIGINT,
    level INT,
    role_id BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, level)
);

CREATE TABLE IF NOT EXISTS bump_reminder (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    role_id BIGINT,
    message TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS crypto_alerts (
    user_id BIGINT,
    guild_id BIGINT,
    coin VARCHAR(50),
    threshold DECIMAL(20, 8),
    above BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id, coin, threshold)
);

CREATE TABLE IF NOT EXISTS lastfm (
    user_id BIGINT PRIMARY KEY,
    username VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS social_links (
    user_id BIGINT,
    platform VARCHAR(50),
    link TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, platform)
);

CREATE TABLE IF NOT EXISTS timers (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    guild_id BIGINT,
    name VARCHAR(100),
    time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS emoji_usage (
    guild_id BIGINT,
    emoji_id BIGINT,
    emoji_name VARCHAR(100),
    uses INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, emoji_id)
);

CREATE TABLE IF NOT EXISTS invocation (
    guild_id BIGINT,
    command VARCHAR(50),
    dm_code TEXT,
    message_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, command)
);

CREATE TABLE IF NOT EXISTS silenced (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS command_usage (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    command_name VARCHAR(100) NOT NULL,
    uses BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, command_name)
);

CREATE TABLE IF NOT EXISTS join_messages (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    self_destruct INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS leave_messages (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    self_destruct INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS boost_messages (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    self_destruct INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS auto_responders (
    guild_id BIGINT NOT NULL,
    trigger TEXT NOT NULL,
    response TEXT,
    strict BOOLEAN NOT NULL DEFAULT TRUE,
    reply BOOLEAN NOT NULL DEFAULT FALSE,
    self_destruct INT,
    delete_trigger BOOLEAN NOT NULL DEFAULT FALSE,
    ignore_command_checks BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_role_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    denied_role_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    allowed_channel_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    denied_channel_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS autoresponder_exclusive (
    guild_id BIGINT NOT NULL,
    trigger TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS autoresponder_roles (
    guild_id BIGINT NOT NULL,
    trigger TEXT NOT NULL,
    role_id BIGINT NOT NULL,
    mode TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger, role_id, mode)
);

CREATE TABLE IF NOT EXISTS sticky_message (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    code TEXT NOT NULL,
    last_message BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS pagination (
    guild_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    creator_id BIGINT NOT NULL,
    pages TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    current_page INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id)
);

CREATE TABLE IF NOT EXISTS trackers (
    guild_id BIGINT NOT NULL,
    tracker_type VARCHAR(32) NOT NULL,
    channel_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, tracker_type)
);

CREATE INDEX IF NOT EXISTS idx_moderation_guild_user ON moderation(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_blacklist_user ON blacklist(user_id);
CREATE INDEX IF NOT EXISTS idx_blacklist_guild ON blacklist(guild_id);
CREATE INDEX IF NOT EXISTS idx_highlights_guild ON highlights(guild_id);
CREATE INDEX IF NOT EXISTS idx_highlight_ignores_guild ON highlight_ignores(guild_id);
CREATE INDEX IF NOT EXISTS idx_reminders_time ON reminders(time);
CREATE INDEX IF NOT EXISTS idx_notes_guild_user ON notes(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_auto_reactions_guild ON auto_reactions(guild_id);
CREATE INDEX IF NOT EXISTS idx_reaction_history_message ON reaction_history(message_id);
CREATE INDEX IF NOT EXISTS idx_button_roles_guild ON button_roles(guild_id);
CREATE INDEX IF NOT EXISTS idx_reaction_role_guild ON reaction_role(guild_id);
CREATE INDEX IF NOT EXISTS idx_giveaways_guild ON giveaways(guild_id);
CREATE INDEX IF NOT EXISTS idx_counters_guild ON counters(guild_id);
CREATE INDEX IF NOT EXISTS idx_clownboard_entries_guild ON clownboard_entries(guild_id);
CREATE INDEX IF NOT EXISTS idx_starboard_entries_guild ON starboard_entries(guild_id);
CREATE INDEX IF NOT EXISTS idx_voicemaster_channels_guild ON voicemaster_channels(guild_id);
CREATE INDEX IF NOT EXISTS idx_birthday_guild ON birthday(guild_id);
CREATE INDEX IF NOT EXISTS idx_birthday_user ON birthday(user_id);
CREATE INDEX IF NOT EXISTS idx_level_roles_guild ON level_roles(guild_id);
CREATE INDEX IF NOT EXISTS idx_crypto_alerts_user ON crypto_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_social_links_user ON social_links(user_id);
CREATE INDEX IF NOT EXISTS idx_timers_time ON timers(time);

CREATE INDEX IF NOT EXISTS idx_emoji_usage_guild ON emoji_usage(guild_id);
CREATE INDEX IF NOT EXISTS idx_invocation_guild ON invocation(guild_id);
CREATE INDEX IF NOT EXISTS idx_command_usage_guild_user ON command_usage(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_join_messages_guild ON join_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_leave_messages_guild ON leave_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_boost_messages_guild ON boost_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_auto_responders_guild ON auto_responders(guild_id);
CREATE INDEX IF NOT EXISTS idx_autoresponder_exclusive_guild ON autoresponder_exclusive(guild_id, trigger);
CREATE INDEX IF NOT EXISTS idx_autoresponder_roles_guild ON autoresponder_roles(guild_id, trigger);
CREATE INDEX IF NOT EXISTS idx_sticky_message_guild ON sticky_message(guild_id);
CREATE INDEX IF NOT EXISTS idx_pagination_guild ON pagination(guild_id);
CREATE INDEX IF NOT EXISTS idx_trackers_guild ON trackers(guild_id);
CREATE INDEX IF NOT EXISTS idx_antiraid_modules_guild ON antiraid_modules(guild_id);
CREATE INDEX IF NOT EXISTS idx_antinuke_actions_lookup ON antinuke_actions(guild_id, user_id, action, created_at);
CREATE INDEX IF NOT EXISTS idx_staff_roles_guild ON staff_roles(guild_id);
CREATE INDEX IF NOT EXISTS idx_modlog_cases_guild ON modlog_cases(guild_id, created_at);
CREATE INDEX IF NOT EXISTS idx_custom_roles_guild ON custom_roles(guild_id);
