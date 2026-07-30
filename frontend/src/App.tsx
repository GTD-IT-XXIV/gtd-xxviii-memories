import { NavLink, Route, Routes, Navigate } from 'react-router-dom'
import ScanSetupPage from './pages/ScanSetupPage'
import ReviewClustersPage from './pages/ReviewClustersPage'
import PersonPickerPage from './pages/PersonPickerPage'
import PersonGalleryPage from './pages/PersonGalleryPage'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-2 rounded-md text-sm font-medium ${
    isActive ? 'bg-indigo-600 text-white' : 'text-gray-600 hover:bg-gray-100'
  }`

function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto max-w-6xl px-4 py-3 flex items-center gap-2">
          <span className="font-semibold text-gray-900 mr-4">Face Search</span>
          <nav className="flex gap-1">
            <NavLink to="/scan" className={navLinkClass}>
              Scan
            </NavLink>
            <NavLink to="/review" className={navLinkClass}>
              Review Faces
            </NavLink>
            <NavLink to="/people" className={navLinkClass}>
              Find Person
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<Navigate to="/scan" replace />} />
          <Route path="/scan" element={<ScanSetupPage />} />
          <Route path="/review" element={<ReviewClustersPage />} />
          <Route path="/people" element={<PersonPickerPage />} />
          <Route path="/people/:personName" element={<PersonGalleryPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
