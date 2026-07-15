export type Me = {
  twitch_user_id: number
  login: string
  display_name: string
  scopes: string[]
  is_admin: boolean
  impersonating: { as_login: string; admin_login: string } | null
}

export type ChannelOption = { login: string; display_name: string }

export type StreamListItem = {
  id: number
  started_at: string
  ended_at: string | null
  title: string | null
  category: string | null
  status: string
  messages: number
  chatters: number
  events: number
  followers: number
  peak_viewers: number
}

export type NumberComparison = {
  value: number
  previous_avg: number | null
  delta_pct: number | null
}

export type PeakOut = {
  id: number
  window_start: string
  window_end: string
  metric: string
  score: number
}

export type CitedMessage = {
  id: number
  sent_at: string
  author_login: string
  text: string
}

export type CitedSegment = {
  id: number
  started_at: string
  text: string | null
}

export type InsightOut = {
  id: number
  type: string
  content: string
  evidence: Record<string, unknown>
  feedback: string | null
  cited_messages: CitedMessage[]
  cited_segments: CitedSegment[]
  engagement_pct: number | null
}

export type StreamReport = {
  id: number
  started_at: string
  ended_at: string | null
  title: string | null
  category: string | null
  status: string
  audit: Record<string, unknown> | null
  numbers: Record<string, NumberComparison>
  peaks: PeakOut[]
  insights: InsightOut[]
}

export type TimelinePoint = { t: string; value: number }
export type EventMarker = { t: string; type: string; amount: number | null }

export type Timeline = {
  chat: TimelinePoint[]
  viewers: TimelinePoint[]
  events: EventMarker[]
  peaks: PeakOut[]
}

export type PeakDetail = {
  peak: PeakOut
  segments: {
    id: number
    started_at: string
    ended_at: string
    kind: string
    text: string | null
  }[]
  messages: { id: number; sent_at: string; author_login: string; text: string }[]
}

export type SearchHit = {
  stream_id: number
  source: 'chat' | 'transcript'
  at: string
  text: string
  author_login: string | null
}

export type ChatterMessage = { sent_at: string; text: string }
export type WordCount = { word: string; count: number }

export type ChatterOut = {
  author_login: string
  messages: number
  pct_of_total: number
  first_at: string
  last_at: string
  active_minutes: number
  peak_messages: number
  sentiment_score: number | null
  followed_during_stream: boolean
  labels: string[]
  sample_messages: ChatterMessage[]
  top_words: WordCount[]
}

export type TopicDetail = {
  insight_id: number
  window_start: string
  window_end: string
  messages_in_window: number
  chat_rate_lift: number | null
  top_chatters: { author_login: string; messages: number }[]
  top_words: WordCount[]
  sample_messages: { id: number; sent_at: string; author_login: string; text: string }[]
  cited_segments: CitedSegment[]
}

export type CommunityOut = {
  share: { login: string | null; messages: number }[]
  words: { word: string; count: number }[]
  emotes: { emote_id: string; name: string; count: number }[]
  sentiment_overall: number | null
  sentiment_timeline: { t: string; score: number; messages: number }[]
  sentiment_by_chatter: { login: string; score: number }[]
  presence: { slots: string[]; rows: { login: string; cells: number[] }[] }
}

export type ViewerDip = {
  at: string
  viewers_before: number
  viewers_after: number
  pct_drop: number
  speech_context: string | null
}

export type Retention = {
  peak_viewers: number
  final_viewers: number
  retained_pct: number
  biggest_drop_at: string | null
}

export type ClipSuggestion = {
  window_start: string
  window_end: string
  offset_seconds: number
  offset_label: string
  score: number
}

export type ActionableOut = {
  retention: Retention | null
  dips: ViewerDip[]
  clips: ClipSuggestion[]
  unanswered_questions_count: number
  unanswered_questions: { sent_at: string; author_login: string; text: string }[]
}

export type FinanceOut = {
  estimated_usd: number
  total_bits: number
  total_subs: number
  total_gifts: number
  money_events: number
  top_contributors: { login: string; estimated_usd: number; bits: number; subs: number }[]
  by_topic: { name: string; estimated_usd: number; events: number }[]
}

export type LoyalChatter = {
  author_login: string
  streams_attended: number
  total_messages: number
  last_seen: string
  followed: boolean
}

export type WeekdaySlot = {
  weekday: number
  label: string
  streams: number
  avg_peak_viewers: number
}

export type GrowthPoint = {
  stream_id: number
  started_at: string
  title: string | null
  peak_viewers: number
  avg_viewers: number
  followers_gained: number
  messages: number
  estimated_usd: number
}

export type ChannelFinance = {
  total_estimated_usd: number
  total_bits: number
  total_subs: number
  total_gifts: number
  top_contributors: { login: string; estimated_usd: number; streams: number }[]
  top_monetizing_topics: { name: string; estimated_usd: number; streams: number }[]
}

export type PastBroadcast = {
  title: string | null
  published_at: string
  duration_seconds: number
  view_count: number
  url: string
}

export type ContentBucket = {
  category: string
  estimated_usd: number
  usd_per_hour: number
  streams: number
  avg_peak_viewers: number
}

export type Engagement = {
  hype_train: { count: number; best_level: number; total_contributed: number }
  top_rewards: { title: string; redemptions: number }[]
  ads: { breaks: number; total_seconds: number; avg_viewer_change_pct: number | null }
}

export type GoalOut = {
  goal_type: string
  description: string | null
  current_amount: number
  target_amount: number
  pct: number
  created_at: string | null
}

export type Community = {
  engaged_viewer_pct: number | null
  vips: string[]
  goals: GoalOut[]
}

export type Subscribers = {
  total: number
  tiers: { tier: string; count: number }[]
  gifted_pct: number
  subs_ended: number
  top_bits: { login: string; score: number }[]
}

export type Recommendation = { content: string; facts: string[] }

export type ChannelOverview = {
  connected_at: string
  scopes: string[]
  total_streams: number
  total_messages: number
  unique_chatters: number
  total_followers_gained: number
  loyal_chatters: LoyalChatter[]
  best_weekdays: WeekdaySlot[]
  growth: GrowthPoint[]
  recurring_topics: { name: string; streams: number }[]
  finance: ChannelFinance
  past_broadcasts: PastBroadcast[]
  content_revenue: ContentBucket[]
  engagement: Engagement
  community: Community
  subscribers: Subscribers
  recommendations: Recommendation[]
}

export type FollowerKpis = {
  total: number
  enriched: number
  streamers: number
  affiliates: number
  partners: number
  new_7d: number
  new_30d: number
  avg_account_age_days: number | null
}

export type GrowthBucket = { month: string; gained: number; cumulative: number }

export type FollowerProfile = {
  login: string
  display_name: string | null
  profile_image_url: string | null
  description: string | null
  broadcaster_type: string | null
  followed_at: string
  account_created_at: string | null
}

export type FollowerComposition = {
  by_type: { label: string; count: number }[]
  by_age: { label: string; count: number }[]
  silent: number
  chatty: number
}

export type FunnelStage = { stage: string; label: string; count: number }

export type CohortRow = {
  month: string
  size: number
  chatted: number
  subscribed: number
  paid: number
}

export type TopFollower = {
  login: string
  display_name: string | null
  stage: string
  messages: number
  streams_present: number
  estimated_usd: number
  sub_months: number
  last_seen: string | null
}

export type Raid = {
  raider_login: string | null
  viewers: number
  at: string
  follows_after: number
}

export type SuspiciousFollower = {
  login: string
  display_name: string | null
  score: number
  reasons: string[]
}

export type VelocityDay = { day: string; follows: number; is_spike: boolean }

export type TopicFollows = { topic: string; follows: number }

export type FollowerSignals = {
  raids: Raid[]
  suspicious: SuspiciousFollower[]
  suspicious_total: number
  velocity: VelocityDay[]
  topic_follows: TopicFollows[]
}

export type FollowerSegment = {
  key: string
  label: string
  description: string
  count: number
  examples: string[]
  action: string | null
}

export type Reactivation = { who: string; message: string }

export type FollowerAi = {
  segments: FollowerSegment[]
  audience_summary: string | null
  reactivations: Reactivation[]
}

export type CollabCandidate = {
  login: string
  display_name: string | null
  profile_image_url: string | null
  broadcaster_type: string | null
  stream_category: string | null
  stream_language: string | null
  shared_category: boolean
  followed_at: string
}

export type FollowersOverview = {
  kpis: FollowerKpis
  growth: GrowthBucket[]
  recent: FollowerProfile[]
  notable: FollowerProfile[]
  composition: FollowerComposition
  funnel: FunnelStage[]
  cohorts: CohortRow[]
  top_value: TopFollower[]
  loyal_subscribers: TopFollower[]
  signals: FollowerSignals
  ai: FollowerAi
  collab: CollabCandidate[]
  recommendations: Recommendation[]
}

export type QueueItem = {
  stream_id: number
  job_type: string
  status: string
  position: number | null
  jobs_ahead: number | null
  eta_seconds: number | null
}
