export type Me = {
  twitch_user_id: number
  login: string
  display_name: string
  scopes: string[]
}

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
  emotes: { name: string; count: number }[]
  sentiment_overall: number | null
  sentiment_timeline: { t: string; score: number; messages: number }[]
  sentiment_by_chatter: { login: string; score: number }[]
  presence: { slots: string[]; rows: { login: string; cells: number[] }[] }
}

export type QueueItem = {
  stream_id: number
  job_type: string
  status: string
  position: number | null
  jobs_ahead: number | null
  eta_seconds: number | null
}
