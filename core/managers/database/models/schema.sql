CREATE SCHEMA IF NOT EXISTS moderation;
CREATE SCHEMA IF NOT EXISTS roleplay;
CREATE SCHEMA IF NOT EXISTS pokemon;
CREATE SCHEMA IF NOT EXISTS monitor;
CREATE SCHEMA IF NOT EXISTS tickets;

CREATE TABLE IF NOT EXISTS moderation.caps (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    threshold    INTEGER DEFAULT 70,
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.spam (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    threshold    INTEGER DEFAULT 5,
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.links (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}',
    whitelist    TEXT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.invites (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}',
    whitelist    TEXT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.spoilers (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    threshold    INTEGER DEFAULT 5,
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.music (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.mention (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    threshold    INTEGER DEFAULT 5,
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.emoji (
    guild_id     BIGINT PRIMARY KEY,
    channel_ids  BIGINT[] DEFAULT '{}',
    threshold    INTEGER DEFAULT 5,
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS moderation.regex (
    id           SERIAL PRIMARY KEY,
    guild_id     BIGINT NOT NULL,
    regex        TEXT NOT NULL,
    action       TEXT DEFAULT 'delete',
    exempt_roles BIGINT[] DEFAULT '{}',
    UNIQUE (guild_id, regex)
);

CREATE TABLE IF NOT EXISTS guilds (
    guild_id           BIGINT PRIMARY KEY,
    prefix             TEXT DEFAULT ',',
    language           TEXT DEFAULT 'en',
    muted_role_id      BIGINT,
    auto_role_id       BIGINT,
    welcome_channel_id BIGINT,
    welcome_message    TEXT,
    leave_channel_id   BIGINT,
    leave_message      TEXT,
    boost_channel_id   BIGINT,
    boost_message      TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config (
    guild_id         BIGINT PRIMARY KEY,
    prefixes         TEXT[] DEFAULT ARRAY[',']::TEXT[],
    colorme          BOOLEAN DEFAULT FALSE,
    colorme_base     TEXT DEFAULT NULL,
    lastfm_reactions TEXT[] DEFAULT ARRAY[]::TEXT[]
);

CREATE TABLE IF NOT EXISTS self_prefix (
    user_id BIGINT PRIMARY KEY,
    prefix  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id     BIGINT NOT NULL,
    guild_id    BIGINT NOT NULL,
    balance     INT DEFAULT 0,
    xp          INT DEFAULT 0,
    level       INT DEFAULT 0,
    warnings    INT DEFAULT 0,
    muted_until TIMESTAMP,
    birthday    TEXT,
    timezone    TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS silenced (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS server_settings (
    guild_id                BIGINT PRIMARY KEY,
    jail_channel_id         BIGINT,
    jail_role_id            BIGINT,
    jail_message_channel_id BIGINT,
    muted_role_id           BIGINT,
    imuted_role_id          BIGINT,
    rmuted_role_id          BIGINT,
    member_base_role_id     BIGINT,
    autonick                TEXT,
    dj_role_id              BIGINT,
    premium_role_id         BIGINT,
    joinlog_channel_id      BIGINT,
    google_safety_level     BOOLEAN DEFAULT FALSE,
    disable_custom_fms      BOOLEAN DEFAULT FALSE,
    autoplay                BOOLEAN,
    jail_message            TEXT,
    jail_remove_roles       BOOLEAN DEFAULT TRUE,
    antinuke_log_channel_id BIGINT,
    antiraid_log_channel_id BIGINT,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS moderation_config (
    guild_id            BIGINT PRIMARY KEY,
    log_channel         BIGINT,
    role_change_logging BOOLEAN DEFAULT FALSE,
    ban_logging         BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS modlog_config (
    guild_id   BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS modlog_cases (
    guild_id     BIGINT NOT NULL,
    case_id      BIGINT NOT NULL,
    action       TEXT,
    target_id    BIGINT,
    moderator_id BIGINT,
    reason       TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    edited_at    TIMESTAMP,
    edited_by    BIGINT,
    PRIMARY KEY (guild_id, case_id)
);

CREATE TABLE IF NOT EXISTS invocation (
    guild_id        BIGINT NOT NULL,
    command         TEXT NOT NULL,
    message_code    TEXT,
    dm_code         TEXT,
    message_enabled BOOLEAN DEFAULT TRUE,
    dm_enabled      BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (guild_id, command)
);

CREATE TABLE IF NOT EXISTS jailed (
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    role_ids     BIGINT[] DEFAULT ARRAY[]::BIGINT[],
    moderator_id BIGINT,
    reason       TEXT,
    jailed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS mutes (
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    moderator_id BIGINT,
    mute_type    TEXT DEFAULT 'text',
    role_id      BIGINT,
    expires_at   TIMESTAMP,
    reason       TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS hardbans (
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    moderator_id BIGINT,
    reason       TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS staff_roles (
    guild_id   BIGINT NOT NULL,
    role_id    BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS command_restrictions (
    guild_id   BIGINT NOT NULL,
    command    TEXT NOT NULL,
    role_id    BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, command, role_id)
);

CREATE TABLE IF NOT EXISTS disabled_commands (
    guild_id     BIGINT NOT NULL,
    command      TEXT NOT NULL,
    object_ids   BIGINT[] DEFAULT ARRAY[]::BIGINT[],
    object_types TEXT[] DEFAULT ARRAY[]::TEXT[],
    PRIMARY KEY (guild_id, command)
);

CREATE TABLE IF NOT EXISTS disabled_modules (
    guild_id    BIGINT NOT NULL,
    module      TEXT NOT NULL,
    channel_ids BIGINT[] DEFAULT ARRAY[]::BIGINT[],
    PRIMARY KEY (guild_id, module)
);

CREATE TABLE IF NOT EXISTS disabled_events (
    guild_id    BIGINT NOT NULL,
    event       TEXT NOT NULL,
    channel_ids BIGINT[] DEFAULT ARRAY[]::BIGINT[],
    PRIMARY KEY (guild_id, event)
);

CREATE TABLE IF NOT EXISTS command_usage (
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    command_name TEXT NOT NULL,
    uses         INT DEFAULT 1,
    PRIMARY KEY (guild_id, user_id, command_name)
);

CREATE TABLE IF NOT EXISTS lockdowns (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    locked_by  BIGINT,
    reason     TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS lockdown_ignore (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id         SERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    guild_id   BIGINT NOT NULL,
    message    TEXT NOT NULL,
    time       TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL,
    content      TEXT NOT NULL,
    case_id      BIGINT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    id           SERIAL
);

CREATE TABLE IF NOT EXISTS proofs (
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT,
    moderator_id BIGINT NOT NULL,
    case_id      BIGINT NOT NULL,
    url          TEXT NOT NULL,
    id           SERIAL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sticky_roles (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    role_id    BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, role_id)
);

CREATE TABLE IF NOT EXISTS forced_nicknames (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    nickname   TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reaction_history (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    reaction   TEXT NOT NULL,
    user_id    BIGINT NOT NULL,
    ts         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, reaction, user_id)
);

CREATE TABLE IF NOT EXISTS antinuke (
    guild_id     BIGINT PRIMARY KEY,
    whitelist    BIGINT[] DEFAULT ARRAY[]::BIGINT[],
    admins       BIGINT[] DEFAULT ARRAY[]::BIGINT[],
    botadd       JSONB DEFAULT '{}'::JSONB,
    webhook      JSONB DEFAULT '{}'::JSONB,
    emoji        JSONB DEFAULT '{}'::JSONB,
    ban          JSONB DEFAULT '{}'::JSONB,
    kick         JSONB DEFAULT '{}'::JSONB,
    channel      JSONB DEFAULT '{}'::JSONB,
    role         JSONB DEFAULT '{}'::JSONB,
    vanity       JSONB DEFAULT '{}'::JSONB,
    permissions  JSONB[] DEFAULT ARRAY[]::JSONB[]
);

CREATE TABLE IF NOT EXISTS antinuke_actions (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    action     TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antiraid_config (
    guild_id     BIGINT PRIMARY KEY,
    raid_active  BOOLEAN DEFAULT FALSE,
    punish_until TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS antiraid_modules (
    guild_id      BIGINT NOT NULL,
    module        TEXT NOT NULL,
    enabled       BOOLEAN DEFAULT FALSE,
    threshold     INT DEFAULT 5,
    action        TEXT DEFAULT 'ban',
    lock_channels BOOLEAN DEFAULT FALSE,
    punish_new    BOOLEAN DEFAULT FALSE,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, module)
);

CREATE TABLE IF NOT EXISTS antiraid_whitelist (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS antiraid_locked_channels (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS honeypot (
    guild_id    BIGINT PRIMARY KEY,
    enabled     BOOLEAN DEFAULT FALSE,
    log_channel BIGINT,
    action      TEXT DEFAULT 'kick',
    message     TEXT
);

CREATE TABLE IF NOT EXISTS role_reassign (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    role_ids   BIGINT[] DEFAULT ARRAY[]::BIGINT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS log_config (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    events     TEXT[] DEFAULT ARRAY[]::TEXT[],
    color      TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS log_event_colors (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    event      TEXT NOT NULL,
    color      TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, event)
);

CREATE TABLE IF NOT EXISTS join_messages (
    guild_id      BIGINT NOT NULL,
    channel_id    BIGINT NOT NULL,
    message       TEXT NOT NULL,
    self_destruct INT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS leave_messages (
    guild_id      BIGINT NOT NULL,
    channel_id    BIGINT NOT NULL,
    message       TEXT NOT NULL,
    self_destruct INT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS boost_messages (
    guild_id      BIGINT NOT NULL,
    channel_id    BIGINT NOT NULL,
    message       TEXT NOT NULL,
    self_destruct INT,
    is_second     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, channel_id, is_second)
);

CREATE TABLE IF NOT EXISTS welcome_messages (
    guild_id      BIGINT NOT NULL,
    channel_id    BIGINT NOT NULL,
    message       TEXT NOT NULL,
    self_destruct INT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS sticky_message (
    guild_id         BIGINT NOT NULL,
    channel_id       BIGINT NOT NULL,
    code             TEXT NOT NULL,
    last_message     BIGINT,
    message_limit    INT NOT NULL DEFAULT 1,
    interval_seconds INT NOT NULL DEFAULT 0,
    message_count    INT NOT NULL DEFAULT 0,
    last_sent        TIMESTAMP,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS auto_role (
    guild_id   BIGINT NOT NULL,
    role_id    BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS button_roles (
    guild_id   BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    role_id    BIGINT NOT NULL,
    style      TEXT DEFAULT 'green',
    emoji      TEXT,
    label      TEXT DEFAULT 'Open Ticket',
    "index"    INT NOT NULL,
    PRIMARY KEY (guild_id, message_id, role_id, "index")
);

CREATE TABLE IF NOT EXISTS reaction_role (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    emoji      TEXT NOT NULL,
    role_id    BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, message_id, role_id)
);

CREATE TABLE IF NOT EXISTS vanity (
    guild_id   BIGINT PRIMARY KEY,
    channel_id BIGINT,
    role_ids   BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    template   TEXT,
    strict     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS guild_tag (
    guild_id   BIGINT PRIMARY KEY,
    channel_id BIGINT,
    role_ids   BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    template   TEXT,
    strict     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS counters (
    guild_id     BIGINT NOT NULL,
    channel_id   BIGINT NOT NULL,
    counter_type TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS saved_embeds (
    guild_id   BIGINT NOT NULL,
    name       TEXT NOT NULL,
    script     TEXT NOT NULL,
    author_id  BIGINT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, name)
);

CREATE TABLE IF NOT EXISTS ignored (
    guild_id    BIGINT NOT NULL,
    object_id   BIGINT NOT NULL,
    object_type TEXT DEFAULT 'member',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, object_id)
);

CREATE TABLE IF NOT EXISTS command_allowed (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    command  TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id, command)
);

CREATE TABLE IF NOT EXISTS aliases (
    guild_id     BIGINT NOT NULL,
    command_name TEXT NOT NULL,
    alias        TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, alias)
);

CREATE TABLE IF NOT EXISTS nuke (
    guild_id        BIGINT NOT NULL,
    channel_id      BIGINT NOT NULL,
    last_nuke       TIMESTAMP,
    nuke_threshold  INT NOT NULL DEFAULT 3600,
    message         TEXT NOT NULL DEFAULT 'first',
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS auto_responders (
    guild_id              BIGINT NOT NULL,
    trigger               TEXT NOT NULL,
    response              TEXT,
    strict                BOOLEAN NOT NULL DEFAULT FALSE,
    reply                 BOOLEAN NOT NULL DEFAULT FALSE,
    self_destruct         INT,
    delete_trigger        BOOLEAN NOT NULL DEFAULT FALSE,
    ignore_command_checks BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_role_ids      BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    denied_role_ids       BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    allowed_channel_ids   BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    denied_channel_ids    BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS auto_reactions (
    guild_id   BIGINT,
    trigger    VARCHAR(255),
    response   TEXT[],
    owner_id   BIGINT,
    strict     BOOLEAN DEFAULT FALSE,
    reply      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, trigger, response)
);

CREATE TABLE IF NOT EXISTS color_roles (
    guild_id BIGINT PRIMARY KEY,
    roles    TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS booster_roles (
    guild_id     BIGINT PRIMARY KEY,
    base_id      BIGINT,
    award_id     BIGINT,
    role_limit   INT DEFAULT 1,
    share_limit  INT DEFAULT 1,
    enabled      BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS custom_roles (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    role_id  BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS image_only (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS image_only_messages (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS blacklist (
    user_id    BIGINT,
    guild_id   BIGINT,
    reason     TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS pagination (
    guild_id     BIGINT NOT NULL,
    channel_id   BIGINT NOT NULL,
    message_id   BIGINT NOT NULL,
    creator_id   BIGINT,
    pages        TEXT[],
    current_page INT DEFAULT 0,
    left_emoji   TEXT,
    right_emoji  TEXT,
    PRIMARY KEY (guild_id, channel_id, message_id)
);

CREATE TABLE IF NOT EXISTS crypto_feeds (
    guild_id        BIGINT NOT NULL,
    channel_id      BIGINT NOT NULL,
    coin_id         TEXT NOT NULL,
    coin_label      TEXT NOT NULL,
    last_price      DOUBLE PRECISION,
    last_change     DOUBLE PRECISION,
    last_market_cap DOUBLE PRECISION,
    last_posted     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, channel_id, coin_id)
);

CREATE TABLE IF NOT EXISTS crypto_alerts (
    guild_id BIGINT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS invite_config (
    guild_id      BIGINT PRIMARY KEY,
    enabled       BOOLEAN DEFAULT FALSE,
    channel_id    BIGINT,
    message       TEXT DEFAULT '{inviter.mention} invited {invitee.mention}. They have **{invites}** {invite_word}.',
    leave_message TEXT DEFAULT '{invitee.mention} left. {inviter.mention} now has **{invites}** {invite_word}.',
    fake_remove   BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS invite_counts (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    invites  INT DEFAULT 0,
    leaves   INT DEFAULT 0,
    fake     INT DEFAULT 0,
    bonus    INT DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS invite_uses (
    guild_id   BIGINT NOT NULL,
    code       TEXT NOT NULL,
    inviter_id BIGINT,
    uses       INT DEFAULT 0,
    PRIMARY KEY (guild_id, code)
);

CREATE TABLE IF NOT EXISTS member_invites (
    guild_id   BIGINT NOT NULL,
    invitee_id BIGINT NOT NULL,
    inviter_id BIGINT,
    code       TEXT,
    joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, invitee_id)
);

CREATE TABLE IF NOT EXISTS birthday (
    user_id       BIGINT NOT NULL,
    guild_id      BIGINT NOT NULL,
    birthday_date TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS birthday_notifications (
    guild_id   BIGINT PRIMARY KEY,
    channel_id BIGINT,
    message    TEXT DEFAULT 'Happy birthday {user}!',
    role_id    BIGINT
);

CREATE TABLE IF NOT EXISTS highlights (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    keyword    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, keyword)
);

CREATE TABLE IF NOT EXISTS highlight_ignores (
    guild_id    BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    target_id   BIGINT NOT NULL,
    target_type TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, target_id, target_type)
);

CREATE TABLE IF NOT EXISTS emoji_usage (
    guild_id   BIGINT NOT NULL,
    emoji_name TEXT NOT NULL,
    uses       INT DEFAULT 0,
    PRIMARY KEY (guild_id, emoji_name)
);

CREATE TABLE IF NOT EXISTS information_config (
    guild_id             BIGINT PRIMARY KEY,
    info_channel        BIGINT,
    join_info_enabled   BOOLEAN DEFAULT FALSE,
    leave_info_enabled  BOOLEAN DEFAULT FALSE,
    edit_info_enabled   BOOLEAN DEFAULT FALSE,
    delete_info_enabled BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS roleplay_config (
    guild_id           BIGINT PRIMARY KEY,
    enabled            BOOLEAN DEFAULT FALSE,
    action_prefix      TEXT DEFAULT '*',
    action_channel     BIGINT,
    delete_original    BOOLEAN DEFAULT FALSE,
    character_tracking BOOLEAN DEFAULT FALSE,
    character_cards    BOOLEAN DEFAULT FALSE,
    card_emoji         TEXT DEFAULT '🎭'
);

CREATE TABLE IF NOT EXISTS characters (
    user_id       BIGINT NOT NULL,
    guild_id      BIGINT NOT NULL,
    name          TEXT,
    message_count INT DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS fun_config (
    guild_id          BIGINT PRIMARY KEY,
    reaction_rewards  BOOLEAN DEFAULT FALSE,
    welcome_enabled   BOOLEAN DEFAULT FALSE,
    welcome_channel   BIGINT
);

CREATE TABLE IF NOT EXISTS manipulation_config (
    guild_id          BIGINT PRIMARY KEY,
    auto_delete       BOOLEAN DEFAULT FALSE,
    delete_patterns   TEXT[] DEFAULT ARRAY[]::TEXT[],
    auto_reply        BOOLEAN DEFAULT FALSE,
    auto_replies      JSONB DEFAULT '[]'::JSONB,
    auto_role_on_join BOOLEAN DEFAULT FALSE,
    join_role_id      BIGINT
);

CREATE TABLE IF NOT EXISTS tictactoe (
    user_id BIGINT PRIMARY KEY,
    wins    INT DEFAULT 0,
    losses  INT DEFAULT 0,
    ties    INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tictactoe_guild (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    wins     INT DEFAULT 0,
    losses   INT DEFAULT 0,
    ties     INT DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS tictactoe_channel (
    channel_id BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    wins       INT DEFAULT 0,
    losses     INT DEFAULT 0,
    ties       INT DEFAULT 0,
    PRIMARY KEY (channel_id, user_id)
);

CREATE TABLE IF NOT EXISTS uwulocks (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    enabled    BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS lastfm_guild_settings (
    guild_id   BIGINT PRIMARY KEY,
    upvote     TEXT,
    downvote   TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lastfm (
    user_id   BIGINT PRIMARY KEY,
    username  TEXT NOT NULL,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lastfm_users (
    user_id   BIGINT NOT NULL,
    username  TEXT NOT NULL,
    is_global BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS lastfm_logins (
    user_id   BIGINT PRIMARY KEY,
    token     TEXT,
    session   TEXT,
    expires   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lastfm_settings (
    user_id      BIGINT PRIMARY KEY,
    nowplaying   BOOLEAN DEFAULT TRUE,
    dm_nowplaying BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS lastfm_custom_commands (
    guild_id   BIGINT NOT NULL,
    command    TEXT NOT NULL,
    response   TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, command)
);

CREATE TABLE IF NOT EXISTS lastfm_custom_blacklist (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS lastfm_hidden (
    user_id BIGINT NOT NULL,
    hidden  BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS lastfm_library_profiles (
    user_id     BIGINT NOT NULL,
    profile_url TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS lastfm_library_artists (
    user_id   BIGINT NOT NULL,
    name      TEXT NOT NULL,
    playcount INT DEFAULT 0,
    url       TEXT,
    image_url TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, name)
);

CREATE TABLE IF NOT EXISTS lastfm_library_albums (
    user_id    BIGINT NOT NULL,
    artist     TEXT NOT NULL,
    name       TEXT NOT NULL,
    playcount  INT DEFAULT 0,
    url        TEXT,
    image_url  TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, artist, name)
);

CREATE TABLE IF NOT EXISTS lastfm_library_tracks (
    user_id    BIGINT NOT NULL,
    artist     TEXT NOT NULL,
    name       TEXT NOT NULL,
    playcount  INT DEFAULT 0,
    url        TEXT,
    image_url  TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, artist, name)
);

CREATE TABLE IF NOT EXISTS lastfm_crowns (
    guild_id   BIGINT NOT NULL,
    artist     TEXT NOT NULL,
    user_id    BIGINT NOT NULL,
    playcount  INT DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, artist)
);

CREATE TABLE IF NOT EXISTS lastfm_crown_history (
    guild_id   BIGINT NOT NULL,
    artist     TEXT NOT NULL,
    user_id    BIGINT NOT NULL,
    old_count  INT DEFAULT 0,
    new_count  INT DEFAULT 0,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, artist, user_id, changed_at)
);

CREATE TABLE IF NOT EXISTS lastfm_album_artwork (
    artist    TEXT NOT NULL,
    album     TEXT NOT NULL,
    image_url TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (artist, album)
);

CREATE TABLE IF NOT EXISTS social_links (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    platform   TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roblox_links (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    roblox_id  BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS webhooks (
    guild_id   BIGINT NOT NULL,
    identifier TEXT NOT NULL,
    name       TEXT NOT NULL,
    channel_id BIGINT,
    webhook_id BIGINT,
    token      TEXT,
    owner_id   BIGINT,
    locked     BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, identifier)
);

CREATE TABLE IF NOT EXISTS guild_customize (
    guild_id          BIGINT PRIMARY KEY,
    emoji             JSONB DEFAULT '{}'::JSONB,
    color             JSONB DEFAULT '{}'::JSONB,
    voicemaster_emoji JSONB DEFAULT '{}'::JSONB,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_customize (
    user_id    BIGINT NOT NULL,
    guild_id   BIGINT NOT NULL,
    emoji      JSONB DEFAULT '{}'::JSONB,
    color      JSONB DEFAULT '{}'::JSONB,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS devlog_config (
    bot_id     BIGINT PRIMARY KEY,
    channel_id BIGINT
);

CREATE TABLE IF NOT EXISTS suggest_settings (
    guild_id      BIGINT PRIMARY KEY,
    channel_id    BIGINT,
    anonymous     BOOLEAN DEFAULT FALSE,
    dm_feedback   BOOLEAN DEFAULT FALSE,
    review_channel BIGINT
);

CREATE TABLE IF NOT EXISTS suggest_counters (
    guild_id   BIGINT PRIMARY KEY,
    total      INT DEFAULT 0,
    pending    INT DEFAULT 0,
    accepted   INT DEFAULT 0,
    denied     INT DEFAULT 0,
    implemented INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS suggestions (
    id         SERIAL PRIMARY KEY,
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT,
    message_id BIGINT,
    user_id    BIGINT NOT NULL,
    suggestion TEXT NOT NULL,
    status     TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suggest_ignored (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS suggest_votes (
    guild_id   BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    vote       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, message_id, user_id)
);

CREATE TABLE IF NOT EXISTS starboard (
    guild_id     BIGINT PRIMARY KEY,
    channel_id   BIGINT,
    threshold    INT DEFAULT 3,
    self_star    BOOLEAN DEFAULT FALSE,
    star_emoji   TEXT DEFAULT '⭐'
);

CREATE TABLE IF NOT EXISTS starboard_entry (
    guild_id       BIGINT NOT NULL,
    channel_id     BIGINT NOT NULL,
    message_id     BIGINT NOT NULL,
    star_message_id BIGINT,
    stars          INT DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, message_id)
);

CREATE TABLE IF NOT EXISTS starboard_entries (
    guild_id       BIGINT NOT NULL,
    channel_id     BIGINT NOT NULL,
    message_id     BIGINT NOT NULL,
    star_message_id BIGINT,
    stars          INT DEFAULT 0,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, message_id)
);

CREATE TABLE IF NOT EXISTS bump_reminder (
    guild_id     BIGINT PRIMARY KEY,
    channel_id   BIGINT,
    interval_min INT DEFAULT 120,
    enabled      BOOLEAN DEFAULT TRUE,
    last_bump    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pingonjoin (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    role_id    BIGINT NOT NULL,
    message    TEXT,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS giveaway_settings (
    guild_id   BIGINT PRIMARY KEY,
    channel_id BIGINT,
    role_id    BIGINT
);

CREATE TABLE IF NOT EXISTS giveaways (
    id              SERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    channel_id      BIGINT NOT NULL,
    message_id      BIGINT,
    prize           TEXT NOT NULL,
    winner_count    INT DEFAULT 1,
    host_id         BIGINT,
    ends_at         TIMESTAMP,
    ended           BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS giveaway_message_stats (
    giveaway_id INT NOT NULL,
    user_id     BIGINT NOT NULL,
    entries     INT DEFAULT 1,
    PRIMARY KEY (giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaway_voice_stats (
    giveaway_id INT NOT NULL,
    user_id     BIGINT NOT NULL,
    minutes     INT DEFAULT 0,
    PRIMARY KEY (giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaway_participation (
    giveaway_id INT NOT NULL,
    user_id     BIGINT NOT NULL,
    entries     INT DEFAULT 1,
    PRIMARY KEY (giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaway_voice_sessions (
    guild_id   BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    channel_id BIGINT,
    joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS leveling (
    guild_id BIGINT PRIMARY KEY,
    enabled  BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS level_user (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    xp       INT DEFAULT 0,
    level    INT DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_multiplier (
    guild_id    BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    multiplier  DOUBLE PRECISION DEFAULT 1.0,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS level_multiplier_voice (
    guild_id    BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    multiplier  DOUBLE PRECISION DEFAULT 1.0,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS level_rewards (
    guild_id   BIGINT NOT NULL,
    level      INT NOT NULL,
    role_id    BIGINT NOT NULL,
    message    TEXT,
    PRIMARY KEY (guild_id, level)
);

CREATE TABLE IF NOT EXISTS levels (
    guild_id BIGINT NOT NULL,
    user_id  BIGINT NOT NULL,
    xp       INT DEFAULT 0,
    level    INT DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.tiktok (
    guild_id      BIGINT NOT NULL,
    channel_id    BIGINT NOT NULL,
    user_id       TEXT NOT NULL,
    username      TEXT NOT NULL,
    template      TEXT,
    live_template TEXT,
    reposts       BOOLEAN NOT NULL DEFAULT FALSE,
    lives         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.instagram (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id    TEXT NOT NULL,
    username   TEXT NOT NULL,
    template   TEXT,
    stories    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.twitter (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id    TEXT NOT NULL,
    username   TEXT NOT NULL,
    template   TEXT,
    retweets   BOOLEAN NOT NULL DEFAULT TRUE,
    replies    BOOLEAN NOT NULL DEFAULT FALSE,
    quotes     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.youtube (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id    TEXT NOT NULL,
    username   TEXT NOT NULL,
    template   TEXT,
    shorts     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.twitch (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id    TEXT NOT NULL,
    username   TEXT NOT NULL,
    template   TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.pinterest (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id    TEXT NOT NULL,
    username   TEXT NOT NULL,
    board_id   TEXT NOT NULL DEFAULT '',
    board_name TEXT,
    template   TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, board_id)
);

CREATE TABLE IF NOT EXISTS monitor.snapchat (
    guild_id   BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    user_id    TEXT NOT NULL,
    username   TEXT NOT NULL,
    template   TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS monitor.seen (
    platform TEXT NOT NULL,
    item_id  TEXT NOT NULL,
    seen_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (platform, item_id)
);

CREATE SCHEMA IF NOT EXISTS tickets;

CREATE TABLE IF NOT EXISTS tickets.settings (
    guild_id     BIGINT PRIMARY KEY,
    category_id  BIGINT,
    log_channel  BIGINT,
    max_tickets  INT DEFAULT 5,
    panel_title  TEXT DEFAULT 'Support',
    panel_desc   TEXT DEFAULT 'Click the button to open a ticket',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tickets.open (
    guild_id     BIGINT NOT NULL,
    user_id      BIGINT NOT NULL,
    channel_id   BIGINT NOT NULL,
    ticket_id    INT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id, ticket_id)
);

CREATE TABLE IF NOT EXISTS tickets.button (
    guild_id    BIGINT NOT NULL,
    channel_id  BIGINT NOT NULL,
    message_id  BIGINT NOT NULL,
    label       TEXT DEFAULT 'Open Ticket',
    emoji       TEXT,
    style       TEXT DEFAULT 'green',
    role_id     BIGINT,
    PRIMARY KEY (guild_id, message_id)
);

CREATE TABLE IF NOT EXISTS tickets.dropdown (
    guild_id    BIGINT NOT NULL,
    channel_id  BIGINT NOT NULL,
    message_id  BIGINT NOT NULL,
    option_label TEXT,
    option_emoji TEXT,
    role_id     BIGINT,
    PRIMARY KEY (guild_id, message_id, option_label)
);

CREATE TABLE IF NOT EXISTS tickets.transcript (
    guild_id    BIGINT NOT NULL,
    channel_id  BIGINT NOT NULL,
    ticket_id   INT NOT NULL,
    user_id     BIGINT NOT NULL,
    transcript  TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_crypto_feeds_coin ON crypto_feeds(coin_id);
CREATE INDEX IF NOT EXISTS idx_join_messages_guild ON join_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_leave_messages_guild ON leave_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_boost_messages_guild ON boost_messages(guild_id);
CREATE INDEX IF NOT EXISTS idx_sticky_message_guild ON sticky_message(guild_id);
CREATE INDEX IF NOT EXISTS idx_auto_responders_guild ON auto_responders(guild_id);
CREATE INDEX IF NOT EXISTS idx_auto_reactions_guild ON auto_reactions(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_tiktok_guild ON monitor.tiktok(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_instagram_guild ON monitor.instagram(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_twitter_guild ON monitor.twitter(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_youtube_guild ON monitor.youtube(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_twitch_guild ON monitor.twitch(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_pinterest_guild ON monitor.pinterest(guild_id);
CREATE INDEX IF NOT EXISTS idx_monitor_snapchat_guild ON monitor.snapchat(guild_id);

ALTER TABLE auto_reactions ADD COLUMN IF NOT EXISTS reply BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE log_config ADD COLUMN IF NOT EXISTS color TEXT;
ALTER TABLE log_event_colors ADD COLUMN IF NOT EXISTS color TEXT;
ALTER TABLE blacklist ADD COLUMN IF NOT EXISTS reason TEXT;
ALTER TABLE pagination ADD COLUMN IF NOT EXISTS left_emoji TEXT;
ALTER TABLE pagination ADD COLUMN IF NOT EXISTS right_emoji TEXT;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS case_id BIGINT;
