/** A known (labeled) person, for the review page's search/tab picker. */
export interface KnownPerson {
  person_name: string;
  og: string | null;
}

/** A single unlabeled cluster plus its presigned thumbnail + recommendation, as sent to the client card. */
export interface ReviewClusterViewModel {
  id: number;
  face_count: number;
  thumbnail_url: string | null;
  recommendation: {
    person_name: string;
    og: string | null;
    similarity: number;
  } | null;
}
