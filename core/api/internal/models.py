from datetime import datetime

from typing import (
  Optional,
  Any,
  List
)
from pydantic import (
  BaseModel,
  ConfigDict,
  HttpUrl,
  Field,
  field_validator
)

class RedditComment(BaseModel):
  id: str
  author: str
  body: str
  ups: int
  created_utc: datetime
  permalink: str
  is_submitter: bool
  replies: List["RedditComment"]

  @field_validator("replies", mode="before")
  @classmethod
  def parse_replies(cls, v: Any) -> List["RedditComment"]:
    if isinstance(v, str) or not v:
      return []

    children = v.get("data", {}).get("children", [])
    comments = []

    for c in children:
      if c.get("kind") == "t1":
        comments.append(cls(**c['data']))

    return comments

RedditComment.model_rebuild()

class SubReddit(BaseModel):
  id: str
  display_name: str
  title: str
  public_description: str
  subscribers: int
  created_utc: datetime
  over18: bool
  community_icon: Optional[str] = None
  banner_background_image: Optional[str] = None
  wiki_enabled: Optional[bool] = None

class RedditSearch(BaseModel):
  id: str
  author: str
  title: str
  selftext: str
  url: str
  permalink: str
  ups: int
  upvote_ratio: float
  num_comments: int
  over_18: bool
  is_video: bool
  is_self: bool
  post_hint: Optional[str] = None
  is_gallery: bool = False
  gallery_data: Optional[dict] = None
  media: Optional[dict] = None
  created_utc: datetime

class RedditUser(BaseModel):
  id: str
  name: str
  created: datetime
  link_karma: int
  comment_karma: int
  total_karma: int
  is_mod: bool
  verified: bool
  is_gold: bool
  icon_img: HttpUrl

class RedditPost(BaseModel):
  id: str
  author: str
  title: str
  selftext: str
  url: str
  permalink: str
  ups: int
  upvote_ratio: float
  num_comments: int
  over_18: bool
  is_video: bool
  is_self: bool
  stickied: bool
  spoiler: bool
  created_utc: datetime
  thumbnail: Optional[str] = None
  link_flair_text: Optional[str]
  domain: str
  category: Optional[str]
  total_awards_received: int

class TwitterUserBiolinks(BaseModel):
  display_url: str
  expanded_url: str
  url: str

class TwitterUser(BaseModel):
  username: str
  id: int
  avatar: str
  banner: Optional[str]
  bio: str
  display_name: Optional[str]
  location: str
  verified: bool
  verified_type: Optional[str]
  created_at: str
  followers: int
  following: int
  posts: int
  liked_posts: int
  tweets: int
  pinned_tweets: Optional[List[str]]
  biolinks: List[TwitterUserBiolinks]
  url: str

class TwitterMedia(BaseModel):
  type: str
  video_url: Optional[str] = None
  image_url: Optional[str] = None

class TwitterTweet(BaseModel):
  id: int
  text: Optional[str]
  author: TwitterUser
  lang: str
  likes: int
  replies: int
  retweets: int
  quote: int
  retweeted: bool
  created_at: str
  views: int
  bookmarks: int
  is_quote: bool
  quote_url: Optional[str]
  hashtags: Optional[List[str]]
  mentions: Optional[List[str]]
  media: List[TwitterMedia]

class CommitAuthor(BaseModel):
  name: str
  email: str
  date: datetime

class CommitDetail(BaseModel):
  author: CommitAuthor
  message: str

class GitHubCommit(BaseModel):
  sha: str
  html_url: str
  commit: CommitDetail

class GitHubUser(BaseModel):
  id: int
  login: str
  avatar_url: HttpUrl
  url: str
  name: str
  type: str
  company: Optional[str] = None
  location: Optional[str] = None
  email: Optional[str] = None
  bio: Optional[str] = None
  public_repos: int
  followers: int
  following: int
  created_at: datetime

class GitHubRepoOwner(BaseModel):
  login: str
  id: int
  avatar_url: HttpUrl
  html_url: HttpUrl
  type: str

class GitHubRepo(BaseModel):
  id: int
  name: str
  private: bool
  owner: GitHubRepoOwner
  description: Optional[str] = None
  fork: bool
  url: str
  created_at: datetime
  updated_at: datetime
  stargazers_count: int
  watchers_count: int
  language: Optional[str]
  archived: bool
  topics: List[str] = []
  forks: int

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

class TikTokBioLinks(BaseModel):
  link: str

class TikTokStats(BaseModel):
  following: int = Field(alias="followingCount")
  followers: int = Field(alias="followerCount")
  likes: int = Field(alias="heartCount")
  videos: int = Field(alias="videoCount")

class TikTokUser(BaseModel):
  id: int
  username: str = Field(alias="uniqueId")
  nickname: str
  description: str = Field(alias="signature")
  avatar: HttpUrl = Field(alias="avatarLarger")
  is_verified: bool = Field(alias="verified")
  is_private: bool = Field(alias="privateAccount")
  stats: TikTokStats

class TikTokVideoStats(BaseModel):
  likes: int = Field(alias="diggCount")
  shares: int = Field(alias="shareCount")
  comments: int = Field(alias="commentCount")
  plays: int = Field(alias="playCount")
  saves: int = Field(alias="collectCount")

class TikTokVideo(BaseModel):
  id: int
  description: str = Field(alias="desc")
  created: datetime = Field(alias="createTime")
  stats: TikTokVideoStats
  author: TikTokUser
  url: str

class BioLinks(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  link_id: int = 0
  url: str = ""
  title: Optional[str] = None
  is_pinned: Optional[bool] = None

class InstagramUser(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  pk: int
  username: str
  full_name: str = ""
  is_private: bool = False
  is_verified: bool = False
  media_count: int = 0
  followers: int = Field(default=0, alias="follower_count")
  following: int = Field(default=0, alias="following_count")
  is_business: bool = False
  avatar: Optional[str] = Field(default=None, alias="profile_pic_url")
  biography: Optional[str] = None
  account_type: Optional[int] = None
  external_url: Optional[str] = None
  bio_links: List[BioLinks] = []

class InstagramStoryUser(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  pk: int = 0
  username: Optional[str] = None
  full_name: Optional[str] = None
  avatar: Optional[str] = Field(default=None, alias="profile_pic_url")
  is_private: Optional[bool] = None

class InstagramStory(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  id: int | str
  media_type: int = 1
  taken_at: Any = None
  user: InstagramStoryUser = Field(default_factory=InstagramStoryUser)
  image_url: Optional[str] = None
  video_url: Optional[str] = None
  video_duration: Optional[float] = 0.0
  thumnail_url: Optional[str] = None

class InstagramHighlight(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  id: int | str
  title: str = ""
  created_at: Any = None
  is_pinned_highlight: bool = False
  media_count: int = 0
  cover_media: str = ""
  user: InstagramStoryUser = Field(default_factory=InstagramStoryUser)

class InstagramCommentUser(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  pk: int = 0
  username: str = ""
  full_name: str = ""
  avatar: Optional[str] = Field(default=None, alias="profile_pic_url")
  is_private: bool = False
  is_verified: bool = False

class InstagramComment(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  pk: int
  text: str = ""
  created_at: Any = None
  user: InstagramCommentUser = Field(default_factory=InstagramCommentUser)

class InstagramMedia(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  pk: int | str = 0
  id: int | str = 0
  code: str = ""
  media_type: int = 1
  taken_at: Any = None
  like_count: int = 0
  comment_count: int = 0
  play_count: Optional[int] = None
  title: Optional[str] = None
  user: InstagramStoryUser = Field(default_factory=InstagramStoryUser)
  image_urls: Optional[List[str]] = None
  thumbnail_url: Optional[str] = None
  video_url: Optional[str] = None
  video_duration: Optional[float] = 0.0

class InstagramFollowerUser(BaseModel):
  model_config = ConfigDict(extra="ignore", populate_by_name=True)

  pk: int = 0
  username: str = ""
  full_name: str = ""
  is_private: bool = False
  is_verified: bool = False
  avatar: Optional[str] = Field(default=None, alias="profile_pic_url")