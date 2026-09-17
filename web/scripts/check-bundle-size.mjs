import { gzipSync } from 'node:zlib'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

// blueprint/wp/WP09-web-foundations.md §6 — initial JS bundle must gzip under 200 KiB.
const BUDGET_BYTES = 200 * 1024
const ASSETS_DIR = join(import.meta.dirname, '..', 'dist', 'assets')

const jsFiles = readdirSync(ASSETS_DIR).filter((name) => name.endsWith('.js'))
if (jsFiles.length === 0) {
  console.error(`no .js files found in ${ASSETS_DIR} — did the build run?`)
  process.exit(1)
}

let totalGzipBytes = 0
for (const file of jsFiles) {
  const content = readFileSync(join(ASSETS_DIR, file))
  const gzipBytes = gzipSync(content).length
  totalGzipBytes += gzipBytes
  console.log(`${file}: ${(gzipBytes / 1024).toFixed(1)} KiB gzip`)
}

console.log(`total: ${(totalGzipBytes / 1024).toFixed(1)} KiB gzip (budget: ${String(BUDGET_BYTES / 1024)} KiB)`)

if (totalGzipBytes > BUDGET_BYTES) {
  console.error('bundle size budget exceeded')
  process.exit(1)
}
