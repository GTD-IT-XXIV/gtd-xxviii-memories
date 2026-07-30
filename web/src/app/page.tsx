import Link from "next/link";

export default function Home() {
  return (
    <div className="max-w-2xl mx-auto p-10 flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">GTD Face Review</h1>
      <p className="text-sm text-gray-600">
        Internal tool for reviewing and labeling face clusters detected by
        the offline face-recognition pipeline.
      </p>
      <div className="flex gap-3">
        <Link
          href="/gallery"
          className="px-4 py-2 rounded bg-indigo-600 text-white text-sm"
        >
          Browse gallery
        </Link>
        <Link
          href="/review"
          className="px-4 py-2 rounded border border-gray-300 text-sm"
        >
          Review clusters
        </Link>
        <Link
          href="/persons"
          className="px-4 py-2 rounded border border-gray-300 text-sm"
        >
          Browse persons
        </Link>
      </div>
    </div>
  );
}
