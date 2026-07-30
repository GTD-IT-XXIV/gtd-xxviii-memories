import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, apiUrl } from '../api/client'
import type { Paginated, PersonSummary } from '../api/types'

export default function PersonPickerPage() {
  const [query, setQuery] = useState('')

  const personsQuery = useQuery({
    queryKey: ['persons', query],
    queryFn: () =>
      api.get<Paginated<PersonSummary>>(`/persons?limit=200${query ? `&query=${encodeURIComponent(query)}` : ''}`),
  })

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-900 mb-4">Find a person</h1>

      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by name..."
        className="w-full max-w-sm border border-gray-300 rounded-md px-3 py-2 text-sm mb-4"
      />

      {personsQuery.isLoading && <p className="text-sm text-gray-500">Loading...</p>}
      {personsQuery.data && personsQuery.data.items.length === 0 && (
        <p className="text-sm text-gray-500">No people found. Label some faces in Review first.</p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3">
        {personsQuery.data?.items.map((p) => (
          <Link
            key={p.person_name}
            to={`/people/${encodeURIComponent(p.person_name)}`}
            className="border border-gray-200 rounded-lg bg-white p-3 flex flex-col gap-2 hover:border-indigo-400 transition-colors"
          >
            <div className="aspect-square bg-gray-100 rounded-md overflow-hidden flex items-center justify-center">
              {p.representative_thumbnail_url ? (
                <img
                  src={apiUrl(p.representative_thumbnail_url)}
                  alt={p.person_name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <span className="text-gray-400 text-xs">No photo</span>
              )}
            </div>
            <p className="text-sm font-medium text-gray-900 truncate">{p.person_name}</p>
            <p className="text-xs text-gray-500">{p.photo_count} photo(s)</p>
          </Link>
        ))}
      </div>
    </div>
  )
}
