CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  filename TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime REAL NOT NULL,
  content_hash TEXT,
  width INTEGER,
  height INTEGER,
  taken_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  error_message TEXT,
  last_scanned_at TEXT,
  created_at TEXT NOT NULL,
  -- r2_key / r2_thumbnail_key: only populated by the Postgres/R2 multi-machine batch
  -- scan (scripts/run_batch_scan_cli.py); always NULL for local SQLite dev. Kept in
  -- sync with app/db/models.py so the SQLAlchemy models match this schema exactly.
  r2_key TEXT,
  r2_thumbnail_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status);
CREATE INDEX IF NOT EXISTS idx_photos_path ON photos(path);

CREATE TABLE IF NOT EXISTS clusters (
  id INTEGER PRIMARY KEY,
  person_name TEXT,
  centroid BLOB NOT NULL,
  face_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'unlabeled',
  merged_into_cluster_id INTEGER REFERENCES clusters(id),
  representative_face_id INTEGER,
  representative_thumbnail_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  -- r2_thumbnail_key / og: see photos.r2_key comment above re: batch-scan-only /
  -- reference-import-only columns kept in sync with app/db/models.py.
  r2_thumbnail_key TEXT,
  og TEXT
);
CREATE INDEX IF NOT EXISTS idx_clusters_person_name ON clusters(person_name);
CREATE INDEX IF NOT EXISTS idx_clusters_status ON clusters(status);

CREATE TABLE IF NOT EXISTS faces (
  id INTEGER PRIMARY KEY,
  photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
  bbox_x REAL NOT NULL,
  bbox_y REAL NOT NULL,
  bbox_w REAL NOT NULL,
  bbox_h REAL NOT NULL,
  det_score REAL NOT NULL,
  embedding BLOB NOT NULL,
  cluster_id INTEGER REFERENCES clusters(id),
  thumbnail_path TEXT,
  created_at TEXT NOT NULL,
  r2_thumbnail_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);

CREATE TABLE IF NOT EXISTS scan_runs (
  id INTEGER PRIMARY KEY,
  scan_root TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  total_files_seen INTEGER DEFAULT 0,
  files_processed INTEGER DEFAULT 0,
  files_skipped_unchanged INTEGER DEFAULT 0,
  files_skipped_placeholder INTEGER DEFAULT 0,
  files_errored INTEGER DEFAULT 0,
  faces_detected INTEGER DEFAULT 0,
  current_file TEXT,
  error_message TEXT
);
