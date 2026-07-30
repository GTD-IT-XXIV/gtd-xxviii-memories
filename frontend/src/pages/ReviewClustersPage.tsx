import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiUrl } from '../api/client'
import type { ClusterSummary, Paginated, PersonSummary } from '../api/types'

const PERSON_NAMES_DATALIST_ID = 'known-person-names'

function ClusterCard({ cluster }: { cluster: ClusterSummary }) {
  const [name, setName] = useState('')
  const queryClient = useQueryClient()

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['clusters'] })
    queryClient.invalidateQueries({ queryKey: ['persons'] })
  }

  const nameMutation = useMutation({
    mutationFn: () => api.post(`/clusters/${cluster.id}/name`, { name }),
    onSuccess: invalidate,
  })
  const discardMutation = useMutation({
    mutationFn: () => api.post(`/clusters/${cluster.id}/discard`),
    onSuccess: invalidate,
  })

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-3 flex flex-col gap-2">
      <div className="aspect-square bg-gray-100 rounded-md overflow-hidden flex items-center justify-center">
        {cluster.representative_thumbnail_url ? (
          <img
            src={apiUrl(cluster.representative_thumbnail_url)}
            alt="face"
            className="w-full h-full object-cover"
          />
        ) : (
          <span className="text-gray-400 text-xs">No thumbnail</span>
        )}
      </div>
      <p className="text-xs text-gray-500">{cluster.face_count} photo(s)</p>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) nameMutation.mutate()
        }}
        className="flex gap-1"
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Person's name"
          list={PERSON_NAMES_DATALIST_ID}
          className="flex-1 min-w-0 border border-gray-300 rounded px-2 py-1 text-xs"
        />
        <button
          type="submit"
          disabled={!name.trim() || nameMutation.isPending}
          className="px-2 py-1 rounded bg-indigo-600 text-white text-xs disabled:opacity-50"
        >
          Save
        </button>
      </form>
      <p className="text-[11px] text-gray-400 -mt-1">
        Already a known person? Start typing to match their existing name exactly.
      </p>

      <button
        onClick={() => discardMutation.mutate()}
        disabled={discardMutation.isPending}
        className="text-xs text-red-600 hover:underline self-start"
      >
        Discard (not a person)
      </button>
    </div>
  )
}

export default function ReviewClustersPage() {
  const clustersQuery = useQuery({
    queryKey: ['clusters'],
    queryFn: () => api.get<Paginated<ClusterSummary>>('/clusters?status=unlabeled&limit=100'),
  })

  // Powers the name-field autocomplete so re-typing a known person's name reuses
  // the exact same string (person identity is matched by exact name).
  const personsQuery = useQuery({
    queryKey: ['persons', 'all-names'],
    queryFn: () => api.get<Paginated<PersonSummary>>('/persons?limit=1000'),
  })

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-900 mb-1">Review faces</h1>
      <p className="text-sm text-gray-500 mb-4">
        Faces the scanner couldn't automatically match to a known person. Name them or discard
        false detections. Sorted by how many photos they appear in.
      </p>

      <datalist id={PERSON_NAMES_DATALIST_ID}>
        {personsQuery.data?.items.map((p) => (
          <option key={p.person_name} value={p.person_name} />
        ))}
      </datalist>

      {clustersQuery.isLoading && <p className="text-sm text-gray-500">Loading...</p>}

      {clustersQuery.data && clustersQuery.data.items.length === 0 && (
        <p className="text-sm text-gray-500">Nothing to review right now.</p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3">
        {clustersQuery.data?.items.map((c) => (
          <ClusterCard key={c.id} cluster={c} />
        ))}
      </div>
    </div>
  )
}
