import { http } from './http'

export interface DocumentInfo {
  filename: string
  filepath: string
  size_kb: number
  indexed: boolean
  chunks: number
}

export interface RetrievalChunk {
  rank: number
  content: string
  source: string
}

export interface RetrievalResult {
  original_query: string
  rewritten_query: string
  chunks: RetrievalChunk[]
}

export const listDocuments = () =>
  http.get<DocumentInfo[]>('/api/documents')

export const uploadDocument = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return http.post<{ message: string }>('/api/documents/upload', form)
}

export const indexDocuments = () =>
  http.post<{ message: string }>('/api/documents/index')

export const deleteDocument = (filename: string) =>
  http.delete(`/api/documents/${encodeURIComponent(filename)}`)

export const testRetrieval = (query: string) =>
  http.post<RetrievalResult>('/api/documents/test-retrieval', { query })
