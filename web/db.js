// DuckDB-WASM boot. Ported from usajobs_historical's web/shared/wasm-api.js:
// fetch the whole Parquet once and query it from memory, rather than leaving
// it on the CDN for read_parquet() to range-read. That measured faster there
// (~3.8s to pull 48 MB and query locally vs ~9.4s of per-query range reads)
// and this file is a similar size (~63 MB), so the same tradeoff applies.
import * as duckdb from 'https://esm.sh/@duckdb/duckdb-wasm';

const LOCAL_PARQUET = 'decisions.parquet';

export async function initDb(parquetUrl) {
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }));
  const worker = new Worker(workerUrl);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  const resp = await fetch(parquetUrl);
  if (!resp.ok) throw new Error(`parquet fetch failed: ${resp.status} ${resp.statusText}`);
  const bytes = new Uint8Array(await resp.arrayBuffer());
  await db.registerFileBuffer(LOCAL_PARQUET, bytes);

  const conn = await db.connect();
  conn.__src = `read_parquet('${LOCAL_PARQUET}')`;
  return conn;
}

export async function query(conn, sql, binds = []) {
  if (!conn.__src) throw new Error('connection was not created by initDb()');
  if (binds.length === 0) {
    const res = await conn.query(sql);
    return res.toArray().map(r => r.toJSON());
  }
  const stmt = await conn.prepare(sql);
  try {
    const res = await stmt.query(...binds);
    return res.toArray().map(r => r.toJSON());
  } finally {
    await stmt.close();
  }
}

export function tableRef(conn) {
  return conn.__src;
}
