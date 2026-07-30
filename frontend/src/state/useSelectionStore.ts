import { create } from 'zustand'

interface SelectionState {
  selected: Set<number>
  toggle: (id: number) => void
  selectAll: (ids: number[]) => void
  clear: () => void
  isSelected: (id: number) => boolean
}

export const useSelectionStore = create<SelectionState>((set, get) => ({
  selected: new Set<number>(),
  toggle: (id) =>
    set((state) => {
      const next = new Set(state.selected)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selected: next }
    }),
  selectAll: (ids) => set({ selected: new Set(ids) }),
  clear: () => set({ selected: new Set() }),
  isSelected: (id) => get().selected.has(id),
}))
