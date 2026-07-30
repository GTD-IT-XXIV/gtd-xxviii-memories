export interface ScanStatus {
  id: number | null
  scan_root: string | null
  status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_files_seen: number
  files_processed: number
  files_skipped_unchanged: number
  files_skipped_placeholder: number
  files_errored: number
  faces_detected: number
  current_file: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
}

export interface ClusterSummary {
  id: number
  face_count: number
  status: 'unlabeled' | 'labeled' | 'discarded' | 'merged'
  person_name: string | null
  representative_thumbnail_url: string | null
  created_at: string
}

export interface ClusterDetail extends ClusterSummary {
  faces: {
    id: number
    photo_id: number
    det_score: number
  }[]
}

export interface Paginated<T> {
  items: T[]
  total: number
}

export interface PersonSummary {
  person_name: string
  photo_count: number
  representative_thumbnail_url: string | null
}

export interface PhotoSummary {
  id: number
  filename: string
  width: number | null
  height: number | null
  taken_at: string | null
}
