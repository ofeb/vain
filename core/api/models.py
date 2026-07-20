from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, HttpUrl, Field


class BraveResult(BaseModel):
    url: str
    title: str
    description: str


class BraveSearch(BaseModel):
    query: str
    results: List[BraveResult]


class BraveImages(BaseModel):
    query: str
    images: List[HttpUrl]


class GitHubCommit(BaseModel):
    sha: str
    html_url: Optional[str] = None
    message: Optional[str] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    author_date: Optional[str] = None
    committer_name: Optional[str] = None
    committer_date: Optional[str] = None


class GitHubRepoOwner(BaseModel):
    login: str
    id: int
    avatar_url: Optional[HttpUrl] = None
    html_url: Optional[HttpUrl] = None
    type: Optional[str] = None


class GitHubRepo(BaseModel):
    id: int
    name: str
    full_name: Optional[str] = None
    private: bool = False
    owner: Optional[GitHubRepoOwner] = None
    description: Optional[str] = None
    fork: bool = False
    html_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pushed_at: Optional[str] = None
    stargazers_count: int = 0
    watchers_count: int = 0
    language: Optional[str] = None
    archived: bool = False
    disabled: bool = False
    open_issues_count: int = 0
    topics: List[str] = Field(default_factory=list)
    forks_count: int = 0
    license: Optional[str] = None


class GitHubUser(BaseModel):
    id: int
    login: str
    name: Optional[str] = None
    avatar_url: Optional[HttpUrl] = None
    url: Optional[str] = None
    html_url: Optional[HttpUrl] = None
    type: Optional[str] = None
    company: Optional[str] = None
    blog: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    bio: Optional[str] = None
    public_repos: int = 0
    public_gists: int = 0
    followers: int = 0
    following: int = 0
    created_at: Optional[str] = None


class InstagramComment(BaseModel):
    pk: str
    text: Optional[str] = None
    username: Optional[str] = None
    profile_pic_url: Optional[HttpUrl] = None
    created_at: Optional[int] = None


class InstagramFollower(BaseModel):
    pk: str
    username: str
    full_name: Optional[str] = None
    profile_pic_url: Optional[HttpUrl] = None
    is_private: bool = False
    is_verified: bool = False


class InstagramHighlight(BaseModel):
    id: str
    title: Optional[str] = None
    cover_url: Optional[HttpUrl] = None


class InstagramPostMedia(BaseModel):
    id: str
    image_urls: List[str] = Field(default_factory=list)
    video_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    taken_at: Optional[int] = None
    caption: Optional[str] = None
    owner_username: Optional[str] = None
    owner_full_name: Optional[str] = None


class InstagramProfile(BaseModel):
    id: str
    username: str
    full_name: Optional[str] = None
    biography: Optional[str] = None
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    profile_pic_url: Optional[HttpUrl] = None
    profile_pic_url_hd: Optional[HttpUrl] = None
    is_private: bool = False
    is_verified: bool = False
    external_url: Optional[str] = None
    is_business: bool = False


class InstagramStory(BaseModel):
    id: str
    taken_at: Optional[int] = None
    video_url: Optional[str] = None
    image_url: Optional[str] = None
    caption: Optional[str] = None


class RedditComment(BaseModel):
    id: str
    author: Optional[str] = None
    body: Optional[str] = None
    ups: int = 0
    created_utc: Optional[float] = None
    permalink: Optional[str] = None
    is_submitter: bool = False


class RedditPost(BaseModel):
    id: str
    author: Optional[str] = None
    title: Optional[str] = None
    selftext: Optional[str] = None
    url: Optional[str] = None
    permalink: Optional[str] = None
    ups: int = 0
    upvote_ratio: float = 0.0
    num_comments: int = 0
    over_18: bool = False
    is_video: bool = False
    is_self: bool = False
    stickied: bool = False
    spoiler: bool = False
    created_utc: Optional[float] = None
    thumbnail: Optional[str] = None
    link_flair_text: Optional[str] = None
    domain: Optional[str] = None
    category: Optional[str] = None
    total_awards_received: int = 0


class RedditSearch(BaseModel):
    id: str
    author: Optional[str] = None
    title: Optional[str] = None
    selftext: Optional[str] = None
    url: Optional[str] = None
    permalink: Optional[str] = None
    ups: int = 0
    upvote_ratio: float = 0.0
    num_comments: int = 0
    over_18: bool = False
    is_video: bool = False
    is_self: bool = False
    post_hint: Optional[str] = None
    is_gallery: bool = False
    created_utc: Optional[float] = None


class RedditUser(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    created: Optional[float] = None
    link_karma: int = 0
    comment_karma: int = 0
    total_karma: int = 0
    is_mod: bool = False
    verified: bool = False
    is_gold: bool = False
    icon_img: Optional[str] = None


class SubReddit(BaseModel):
    id: Optional[str] = None
    display_name: Optional[str] = None
    title: Optional[str] = None
    public_description: Optional[str] = None
    subscribers: int = 0
    created_utc: Optional[float] = None
    over18: bool = False
    community_icon: Optional[str] = None
    banner_background_image: Optional[str] = None
    wiki_enabled: Optional[bool] = None


class TikTokPost(BaseModel):
    id: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None
    play_count: int = 0
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    create_time: Optional[int] = None
    author: Optional[dict[str, Any]] = None


class TikTokProfile(BaseModel):
    id: str
    username: str
    nickname: Optional[str] = None
    bio: Optional[str] = None
    followers_count: int = 0
    following_count: int = 0
    likes_count: int = 0
    videos_count: int = 0
    avatar_url: Optional[HttpUrl] = None
    is_verified: bool = False


class TwitterMedia(BaseModel):
    type: str
    video_url: Optional[str] = None
    image_url: Optional[str] = None


class TwitterUserBiolinks(BaseModel):
    expanded_url: Optional[str] = None


class TwitterUser(BaseModel):
    username: str
    id: str
    avatar: Optional[str] = None
    banner: Optional[str] = None
    bio: Optional[str] = None
    display_name: Optional[str] = None
    location: Optional[str] = None
    verified: bool = False
    verified_type: Optional[str] = None
    created_at: Optional[str] = None
    followers: int = 0
    following: int = 0
    posts: int = 0
    liked_posts: int = 0
    tweets: int = 0
    pinned_tweets: List[str] = Field(default_factory=list)
    biolinks: List[TwitterUserBiolinks] = Field(default_factory=list)
    url: Optional[str] = None


class TwitterTweet(BaseModel):
    id: str
    text: str
    author: Optional[TwitterUser] = None
    lang: Optional[str] = None
    likes: int = 0
    replies: int = 0
    retweets: int = 0
    quote: int = 0
    retweeted: bool = False
    created_at: Optional[str] = None
    views: Optional[str] = None
    bookmarks: int = 0
    is_quote: bool = False
    quote_url: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)
    mentions: List[str] = Field(default_factory=list)
    media: List[TwitterMedia] = Field(default_factory=list)
