# GTD Face Review

Internal Next.js app for reviewing and labeling face clusters produced by the
separate offline Python face-recognition pipeline (scan -> detect -> embed ->
cluster). This app is the read/write "backend" (via Next.js Route Handlers /
Server Components) and UI organizers use to name clusters and browse results.
It does not run any long-lived server process of its own -- it's meant to be
deployed on Vercel.

## Data ownership

This app **does not create or migrate any database schema**. It assumes the
`photos`, `clusters`, and `faces` tables already exist in Postgres, created
and maintained by the separate Python pipeline. It only ever runs
`SELECT`/`UPDATE` statements against that existing schema.

It also assumes photo originals and thumbnails have already been uploaded to
a Cloudflare R2 bucket by that same pipeline, keyed by `photos.r2_key` /
`photos.r2_thumbnail_key` / `clusters.r2_thumbnail_key`.

## Required environment variables

See `.env.example`. All of these must be set for the app to function --
there are no fallback/mock modes:

- `DATABASE_URL` -- Neon Postgres connection string.
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`
  -- Cloudflare R2 credentials. The bucket is private; the app generates
  short-lived (1 hour) presigned GET URLs server-side for every image it
  displays, rather than exposing a public bucket URL.

## Running locally

```bash
npm install
cp .env.example .env.local   # then fill in real values
npm run dev
```

Open http://localhost:3000.

## Pages

- `/review` -- main workflow. Paginated list of `unlabeled` clusters (sorted
  by face count, descending), each with a recommended match against existing
  `labeled` clusters (cosine similarity of centroids, computed server-side
  in Node -- no vector DB extension needed at this scale). Reviewers can
  accept the suggestion, correct it (search / tab-by-group / free-text new
  name), or discard the cluster as not-a-person.
- `/persons` -- distinct labeled people with photo counts and a
  representative thumbnail.
- `/persons/[name]` -- paginated photo gallery for one person.

Labeling/discarding goes through:

- `POST /api/clusters/[id]/name` -- body `{ person_name, og? }`, sets
  `status = 'labeled'`.
- `POST /api/clusters/[id]/discard` -- sets `status = 'discarded'`.

## Stack

- Next.js App Router + TypeScript.
- `@neondatabase/serverless` (Neon's HTTP-based driver) for Postgres access
  via raw parameterized SQL -- no ORM, since the schema is small, fixed, and
  owned by the Python pipeline.
- `@aws-sdk/client-s3` + `@aws-sdk/s3-request-presigner` for R2 presigned
  URLs (R2 is S3-compatible).
- Tailwind CSS for styling (kept minimal -- this is an internal tool).

## Deploying

Standard Next.js app, importable into Vercel with no extra build
configuration. Set the environment variables above in the Vercel project
settings for all environments you deploy (Production/Preview/Development).
