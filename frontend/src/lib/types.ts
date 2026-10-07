export type Role = 'admin' | 'user'

export interface Label {
  id: string
  name: string
  description: string
  color: string
  document_count?: number
  user_count?: number
}

export interface Me {
  id: string
  email: string
  role: Role
  labels: Label[]
}

export type DocumentStatus = 'uploaded' | 'processing' | 'ready' | 'failed'

export type DocType = 'policy' | 'sop' | 'circular' | 'guideline' | 'report' | 'minutes' | 'other'

export interface DocumentRow {
  id: string
  title: string
  filename: string
  doc_type: DocType
  reference_no: string | null
  /** ISO date the document was issued or took effect */
  issued_on: string | null
  page_count: number | null
  pages_processed: number
  status: DocumentStatus
  error: string | null
  created_at: string
  label_ids: string[]
}

export interface Citation {
  id: string // "S1"
  chunk_id: string
  document_id: string
  document_title: string
  doc_type?: DocType | null
  reference_no?: string | null
  issued_on?: string | null
  page_index: number
  printed_label: string | null
  snippet: string
}

export type Verdict = 'grounded' | 'partial' | 'low_confidence' | 'no_sources' | 'not_applicable' | 'unchecked'

export interface ClaimCheck {
  claim: string
  source_ids: string[]
  verdict: 'supported' | 'partial' | 'unsupported'
  citation_correct: boolean
  evidence_quote: string
  note: string
}

export interface EvalResult {
  verdict: Verdict
  grounded_score: number | null
  summary: string
  claims: ClaimCheck[]
}

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  eval: EvalResult | null
  feedback?: 1 | -1 | null
  // client-side streaming state
  status?: 'planning' | 'retrieving' | 'answering' | 'evaluating' | 'regenerating' | 'done' | 'error'
  sources?: Citation[]
}

export interface Conversation {
  id: string
  title: string
  label_ids: string[]
  updated_at: string
}

export interface AdminUser {
  id: string
  email: string
  role: Role
  created_at: string
  label_ids: string[]
}

export interface QueryLog {
  id: string
  question: string
  verdict: Verdict | null
  grounded_score: number | null
  regenerated: boolean
  latency_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  created_at: string
  label_ids: string[]
  /** Query Agent output */
  plan: QueryPlan | null
  /** What retrieval returned, in the order the Answer Agent saw it */
  retrieved: RetrievedSource[]
  /** Set when the Evaluator rejected the first draft and forced a rewrite */
  first_draft: { answer: string; eval: EvalResult } | null
  profiles: { email: string } | null
  messages: {
    content: string
    feedback: 1 | -1 | null
    feedback_note: string | null
    citations: Citation[]
    /** Evaluator Agent output for the final answer */
    eval: EvalResult | null
  } | null
}

export interface QueryPlan {
  needs_retrieval: boolean
  standalone_question: string
  sub_queries: string[]
  keywords: string[]
  direct_reply: string
}

export interface RetrievedSource {
  id: string // "S1"
  document_id: string
  document_title: string
  page_index: number
  printed_label: string | null
  /** Fused search score; null for questions logged before scores were stored */
  score: number | null
  /** The chunk that matched the search */
  matched: string
  /** Whether the final answer cited it */
  cited: boolean
}

export interface AdminStats {
  documents: number
  documents_ready: number
  pages: number
  empty_pages: number
  users: number
  queries: number
  avg_grounded: number | null
  thumbs_up: number
  thumbs_down: number
  regenerated: number
  /** Questions where no relevant document was found */
  unanswered: number
}

export type ChatEvent =
  | { type: 'conversation'; conversation_id: string }
  | { type: 'plan'; plan: { needs_retrieval: boolean; standalone_question: string; sub_queries: string[] } }
  | { type: 'sources'; sources: Citation[] }
  | { type: 'delta'; text: string }
  | { type: 'evaluating' }
  | { type: 'regenerate'; reason: string }
  | {
      type: 'final'
      answer: string
      citations: Citation[]
      eval: EvalResult
      regenerated: boolean
      message_id: string | null
    }
  | { type: 'error'; message: string }
