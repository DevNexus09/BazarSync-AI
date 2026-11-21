export type CopilotConfidence = "HIGH" | "MEDIUM" | "LOW" | "NO_CONTEXT"
export type CopilotLanguage = "auto" | "bn" | "en" | "banglish"
/** Language the answer text is written in; Banglish is Bangla in Latin script. */
export type CopilotReplyLanguage = "en" | "bn" | "banglish"
export type CopilotReplyScript = "bengali" | "latin"
export type CopilotSourceMode = "current" | "memory" | "both"
export type CopilotDomain =
  | "PRODUCT_CATALOG"
  | "SALES_REVENUE"
  | "PROFIT_MARGIN"
  | "INVENTORY"
  | "COMPETITOR"
  | "PRICING"
  | "PROMOTION"
  | "DEAD_STOCK"
  | "SEO_VISIBILITY"
  | "RECOMMENDATIONS"
  | "ALERTS"
  | "RAG_MEMORY"
  | "COPILOT"
export type CopilotMemorySourceType =
  | "COMPETITOR_HISTORY"
  | "PRICE_HISTORY"
  | "INVENTORY_HISTORY"
  | "INVENTORY_LIFECYCLE"
  | "SALES_HISTORY"
  | "SALES_REVENUE_SUMMARY"
  | "RECOMMENDATION"
  | "RECOMMENDATION_HISTORY"
  | "ALERT"
  | "ALERT_HISTORY"
  | "PROMOTION_PLAN"
  | "PROMOTION_RESULT"
  | "SELLER_PRICE_HISTORY"
  | "DEAD_STOCK"
  | "DEAD_STOCK_HISTORY"
  | "SEO"
  | "SEO_VISIBILITY_HISTORY"
  | "PRICING_HISTORY"
  | "COPILOT_HISTORY"
  | "ACTION_CENTER"
  | "SUPPORT_LOG"
  | "PRODUCT_PROFILE"
  | "CUSTOMER_CONTEXT"

export type CopilotConversation = {
  id: string
  conversation_id?: string
  seller_id: string
  user_id?: string | null
  title?: string | null
  last_message_preview?: string | null
  status: string
  language: string
  created_at: string
  updated_at: string
  archived_at?: string | null
  message_count?: number
  last_confidence?: string | null
  metadata_json?: Record<string, unknown> | null
}

export type CopilotMessage = {
  id: string
  seller_id: string
  conversation_id: string
  role: "USER" | "ASSISTANT" | "SYSTEM" | "TOOL"
  content: string
  language: string
  answer_confidence?: string | null
  model_id?: string | null
  prompt_version?: string | null
  token_usage_json?: Record<string, unknown> | null
  evidence_json?: unknown
  missing_context_json?: unknown
  missing_data_json?: unknown
  data_freshness_json?: unknown
  tools_used_json?: unknown
  domains_used_json?: unknown
  recommended_next_steps_json?: unknown
  action_proposal_json?: unknown
  response_metadata_json?: Record<string, unknown> | null
  answer?: string | null
  summary?: string | null
  confidence?: string | null
  question_type?: string | null
  domains_used?: string[]
  tools_used?: CopilotToolUsed[]
  evidence?: CopilotEvidence[]
  missing_data?: CopilotMissingData[]
  data_freshness?: CopilotDataFreshness[]
  recommended_next_steps?: string[]
  action_proposal?: CopilotActionProposal | null
  created_at: string
}

export type CopilotEvidence = {
  evidence_id: string
  domain?: string
  source_type: string
  source_table?: string | null
  source_id?: string | null
  product_id?: string | null
  product_name?: string | null
  title: string
  summary?: string
  snippet?: string | null
  event_time?: string | null
  freshness?: "FRESH" | "STALE" | "MISSING" | "UNKNOWN" | string
  confidence?: CopilotConfidence | string
  url?: string | null
  path?: string | null
  source_metadata?: Record<string, unknown>
}

export type CopilotToolUsed = {
  name?: string
  tool_name?: string
  domain?: string
  status: string
  duration_ms?: number
  evidence_count?: number | null
  missing_data_count?: number | null
  error?: Record<string, unknown> | null
}

export type CopilotMissingData = {
  key?: string
  domain?: string
  source_table?: string | null
  message: string
  blocking?: boolean
  next_action?: string
  setup_href?: string | null
  required_for?: string[]
  severity?: string
}

export type CopilotDataFreshness = {
  domain: string
  source_table?: string | null
  latest_available_at?: string | null
  status: "FRESH" | "STALE" | "MISSING" | "UNKNOWN" | string
  message: string
}

export type CopilotActionProposal = {
  id: string
  action_type: string
  status: string
  summary?: string
  requires_confirmation: boolean
  safety_checks?: unknown
  expected_impact?: unknown
  evidence?: unknown
}

export type CopilotAskRequest = {
  conversation_id?: string
  question: string
  product_id?: string | null
  from_date?: string | null
  to_date?: string | null
  domain_filters?: CopilotDomain[]
  language?: CopilotLanguage
  include_current_data?: boolean
  include_memory?: boolean
  memory_source_types?: CopilotMemorySourceType[]
  top_k?: number
  debug?: boolean
}

export type CopilotAskResponse = {
  conversation_id: string
  message_id: string
  answer: string
  summary?: string
  confidence: CopilotConfidence
  language: "bn" | "en"
  intent?: string
  question_type?: string | null
  domains_used?: string[]
  tools_used?: CopilotToolUsed[]
  evidence?: CopilotEvidence[]
  missing_data?: CopilotMissingData[]
  data_freshness?: CopilotDataFreshness[]
  recommended_next_steps?: string[]
  action_proposal?: CopilotActionProposal | null
  memory_coverage_warning?: boolean | string | null
  reply_language?: CopilotReplyLanguage | null
  reply_script?: CopilotReplyScript | null
  suggested_follow_ups?: string[]
}

export type CopilotStreamStage =
  | { stage: "understanding"; reply_language?: CopilotReplyLanguage | null }
  | { stage: "planning"; tools: string[] }
  | { stage: "tool"; tool: string; status: string }
  | { stage: "writing" }

export type CopilotFeatures = {
  multilingual: boolean
  languages: CopilotLanguage[]
  streaming: boolean
  follow_ups: boolean
  feedback: boolean
  conversation_memory: boolean
}

export type CopilotFeedbackRating = "up" | "down"

export type CopilotToolMetadata = {
  name: string
  version: string
  description: string
  safety_level: string
  requires_confirmation: boolean
  allowed_in_read_only_mode: boolean
  max_runtime_ms: number
  catalog_domains?: string[]
  catalog_metrics?: string[]
}

export type CopilotActionProposalTransition = {
  proposal: CopilotActionProposal
  message: string
  executed: boolean
}

export type CopilotLocalMessage =
  | {
      id: string
      role: "user"
      content: string
      /** The question never got an answer (network, timeout, rate limit...). */
      failed?: boolean
    }
  | {
      id: string
      role: "assistant"
      content: string
      summary?: string
      confidence: CopilotConfidence
      questionType?: string | null
      domainsUsed: string[]
      toolsUsed: CopilotToolUsed[]
      evidence: CopilotEvidence[]
      missingData: CopilotMissingData[]
      dataFreshness: CopilotDataFreshness[]
      recommendedNextSteps: string[]
      actionProposal: CopilotActionProposal | null
      memoryCoverageWarning?: boolean | string | null
      replyLanguage?: CopilotReplyLanguage | null
      replyScript?: CopilotReplyScript | null
      followUps?: string[]
      feedback?: CopilotFeedbackRating | null
    }
