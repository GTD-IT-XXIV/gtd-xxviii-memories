import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { ScanStatus } from '../api/types'

const POLL_INTERVAL_MS = 1500

export default function ScanSetupPage() {
  const [scanRoot, setScanRoot] = useState('')
  const queryClient = useQueryClient()

  const statusQuery = useQuery({
    queryKey: ['scan-status'],
    queryFn: () => api.get<ScanStatus>('/scan/status'),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? POLL_INTERVAL_MS : false),
  })

  const startMutation = useMutation({
    mutationFn: () => api.post<ScanStatus>('/scan/start', { scan_root: scanRoot }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['scan-status'] }),
  })

  const stopMutation = useMutation({
    mutationFn: () => api.post('/scan/stop'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['scan-status'] }),
  })

  const status = statusQuery.data
  const isRunning = status?.status === 'running'
  const pct =
    status && status.total_files_seen > 0
      ? Math.round(
          ((status.files_processed + status.files_skipped_unchanged + status.files_skipped_placeholder + status.files_errored) /
            status.total_files_seen) *
            100,
        )
      : 0

  return (
    <div className="max-w-2xl">
      <h1 className="text-xl font-semibold text-gray-900 mb-4">Scan a photo folder</h1>

      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={scanRoot}
          onChange={(e) => setScanRoot(e.target.value)}
          placeholder="C:\Users\you\OneDrive\Pictures"
          disabled={isRunning}
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm disabled:bg-gray-100"
        />
        {isRunning ? (
          <button
            onClick={() => stopMutation.mutate()}
            className="px-4 py-2 rounded-md bg-red-600 text-white text-sm font-medium hover:bg-red-700"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={() => startMutation.mutate()}
            disabled={!scanRoot || startMutation.isPending}
            className="px-4 py-2 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            Start Scan
          </button>
        )}
      </div>

      {startMutation.isError && (
        <p className="text-sm text-red-600 mb-4">{(startMutation.error as Error).message}</p>
      )}

      {status && status.status !== 'idle' && (
        <div className="border border-gray-200 rounded-lg p-4 bg-white">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium capitalize">{status.status}</span>
            <span className="text-sm text-gray-500">{pct}%</span>
          </div>
          <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden mb-3">
            <div
              className="h-full bg-indigo-600 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <dl className="grid grid-cols-2 gap-y-1 text-sm text-gray-600">
            <dt>Total files</dt>
            <dd>{status.total_files_seen}</dd>
            <dt>Processed</dt>
            <dd>{status.files_processed}</dd>
            <dt>Skipped (unchanged)</dt>
            <dd>{status.files_skipped_unchanged}</dd>
            <dt>Skipped (cloud placeholder)</dt>
            <dd>{status.files_skipped_placeholder}</dd>
            <dt>Errored</dt>
            <dd>{status.files_errored}</dd>
            <dt>Faces detected</dt>
            <dd>{status.faces_detected}</dd>
          </dl>
          {status.current_file && (
            <p className="mt-3 text-xs text-gray-400 truncate">{status.current_file}</p>
          )}
          {status.error_message && (
            <p className="mt-3 text-sm text-red-600">{status.error_message}</p>
          )}
        </div>
      )}
    </div>
  )
}
