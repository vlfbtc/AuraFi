#!/usr/bin/env node

/** Compatibility entrypoint for the canonical dependency-free Python gate. */

import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const validator = path.resolve(scriptDir, '..', 'validate_pipeline.py');
const candidates = [process.env.AURAFI_PYTHON, 'python3.13', 'python3.12', 'python3.11', 'python3']
  .filter(Boolean);

let python = null;
for (const candidate of candidates) {
  const version = spawnSync(candidate, ['--version'], { encoding: 'utf8' });
  const output = `${version.stdout ?? ''}${version.stderr ?? ''}`;
  const match = output.match(/Python (\d+)\.(\d+)/);
  if (version.status === 0 && match && (Number(match[1]) > 3 || Number(match[2]) >= 11)) {
    python = candidate;
    break;
  }
}

if (!python) {
  console.error('FAIL  Python 3.11+ é obrigatório para executar o validador analítico.');
  process.exit(1);
}

const result = spawnSync(python, [validator], { stdio: 'inherit' });
if (result.error) {
  console.error(`FAIL  não foi possível executar ${python}: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
