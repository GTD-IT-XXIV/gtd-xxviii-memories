// The installed "archiver" v8 ships no bundled types and is ESM-only with a
// class-based API (ZipArchive/TarArchive/JsonArchive extends Archiver) - a
// rewrite from the older factory-function API that @types/archiver (the
// DefinitelyTyped package) still describes. This declares only the shape
// this app actually uses.
declare module "archiver" {
  import type { Transform } from "node:stream";

  export interface EntryData {
    name: string;
    [key: string]: unknown;
  }

  export class Archiver extends Transform {
    constructor(options?: Record<string, unknown>);
    append(source: NodeJS.ReadableStream | Buffer | string, data: EntryData): this;
    finalize(): Promise<void>;
  }

  export class ZipArchive extends Archiver {}
  export class TarArchive extends Archiver {}
  export class JsonArchive extends Archiver {}
}
