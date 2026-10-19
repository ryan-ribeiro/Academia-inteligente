export type TrainingCitation = {
  chunk_id: string
  source_id: string
  title: string
  url: string
  authors: string[]
  license: string
  license_url: string
  section: string | null
  attribution?: string | null
  content_note?: string | null
  captured_at?: string | null
}

export type TrainingKnowledgeStatus = 'supported' | 'insufficient_evidence' | 'outdated' | 'unavailable'

export type TrainingKnowledge = {
  citations?: TrainingCitation[]
  knowledge_status?: TrainingKnowledgeStatus
  knowledge_limitations?: string | null
}
