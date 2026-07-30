import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api, apiUrl, ApiError } from '../api/client'
import type { Paginated, PhotoSummary } from '../api/types'
import { useSelectionStore } from '../state/useSelectionStore'

const PAGE_SIZE = 60

export default function PersonGalleryPage() {
  const { personName = '' } = useParams()
  const decodedName = decodeURIComponent(personName)
  const [offset, setOffset] = useState(0)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)

  const selected = useSelectionStore((s) => s.selected)
  const toggle = useSelectionStore((s) => s.toggle)
  const selectAll = useSelectionStore((s) => s.selectAll)
  const clear = useSelectionStore((s) => s.clear)

  const photosQuery = useQuery({
    queryKey: ['person-photos', decodedName, offset],
    queryFn: () =>
      api.get<Paginated<PhotoSummary>>(
        `/persons/${encodeURIComponent(decodedName)}/photos?limit=${PAGE_SIZE}&offset=${offset}`,
      ),
  })

  useEffect(() => {
    clear()
    setOffset(0)
  }, [decodedName, clear])

  const items = photosQuery.data?.items ?? []
  const total = photosQuery.data?.total ?? 0

  async function downloadSelection(photoIds: number[]) {
    setDownloadError(null)
    setDownloading(true)
    try {
      const res = await fetch(apiUrl('/download/zip'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ photo_ids: photoIds }),
      })
      if (!res.ok) throw new ApiError(res.status, await res.text())
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${decodedName.replace(/[^\w-]+/g, '_')}_photos.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : 'Download failed')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-900 mb-1">{decodedName}</h1>
      <p className="text-sm text-gray-500 mb-4">{total} photo(s) found</p>

      <div className="flex items-center gap-3 mb-4 sticky top-0 bg-gray-50 py-2 z-10">
        <button
          onClick={() => selectAll(items.map((p) => p.id))}
          className="text-xs px-3 py-1.5 rounded-md bg-gray-200 text-gray-800 hover:bg-gray-300"
        >
          Select all on page
        </button>
        <button
          onClick={clear}
          className="text-xs px-3 py-1.5 rounded-md bg-gray-200 text-gray-800 hover:bg-gray-300"
        >
          Clear selection
        </button>
        <span className="text-xs text-gray-500">{selected.size} selected</span>
        <div className="flex-1" />
        <button
          onClick={() => downloadSelection(Array.from(selected))}
          disabled={selected.size === 0 || downloading}
          className="text-xs px-3 py-1.5 rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {downloading ? 'Preparing ZIP...' : `Download ${selected.size} selected`}
        </button>
        <button
          onClick={() => downloadSelection(items.map((p) => p.id))}
          disabled={items.length === 0 || downloading}
          className="text-xs px-3 py-1.5 rounded-md bg-indigo-100 text-indigo-700 hover:bg-indigo-200 disabled:opacity-50"
        >
          Download all on page
        </button>
      </div>

      {downloadError && <p className="text-sm text-red-600 mb-3">{downloadError}</p>}

      <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-3">
        {items.map((photo) => (
          <label
            key={photo.id}
            className="relative border border-gray-200 rounded-lg bg-white overflow-hidden cursor-pointer group"
          >
            <input
              type="checkbox"
              checked={selected.has(photo.id)}
              onChange={() => toggle(photo.id)}
              className="absolute top-2 left-2 z-10 w-4 h-4"
            />
            <img
              src={apiUrl(`/photos/${photo.id}/thumbnail`)}
              alt={photo.filename}
              className="w-full aspect-square object-cover group-hover:opacity-90"
            />
          </label>
        ))}
      </div>

      <div className="flex justify-center gap-3 mt-6">
        <button
          onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          disabled={offset === 0}
          className="text-xs px-3 py-1.5 rounded-md bg-gray-200 disabled:opacity-50"
        >
          Previous
        </button>
        <button
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
          disabled={offset + PAGE_SIZE >= total}
          className="text-xs px-3 py-1.5 rounded-md bg-gray-200 disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  )
}
