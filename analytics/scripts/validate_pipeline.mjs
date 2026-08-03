#!/usr/bin/env node

/**
 * Dependency-free static gate for the controlled AuraFi analytical dataset.
 * It does not run dbt, connect to PostgreSQL, or access the network.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const analyticsRoot = path.resolve(scriptDir, '..');
const dbtRoot = path.join(analyticsRoot, 'dbt');
const checks = [];
const errors = [];

const requiredSeedColumns = [
  'event_id', 'event_type', 'test_case_id', 'is_test_data', 'source_system',
  'occurred_at', 'user_pseudo_id', 'user_version', 'user_valid_from',
  'user_valid_to', 'market_source', 'market_mode', 'observed_at',
  'retrieved_at', 'is_stale', 'read_only',
];
const requiredModels = [
  'stg_test_events', 'dim_tempo', 'dim_usuario', 'dim_perfil_risco',
  'dim_protocolo', 'dim_ativo', 'dim_blockchain', 'dim_canal',
  'fato_recomendacao', 'fato_yield_observacao', 'fato_interacao_conversacional',
  'aura_star_schema', 'mvp_metrics',
];
const piiPatterns = [
  ['email', /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/],
  ['wallet', /\b0x[a-fA-F0-9]{40}\b/],
];

function pass(message) { checks.push(message); }
function fail(message) { errors.push(message); }
function read(filePath) { return fs.readFileSync(filePath, 'utf8'); }
function exists(filePath) { return fs.existsSync(filePath); }

function parseCsv(input) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < input.length; i += 1) {
    const char = input[i];
    const next = input[i + 1];
    if (char === '"' && quoted && next === '"') { field += '"'; i += 1; continue; }
    if (char === '"') { quoted = !quoted; continue; }
    if (char === ',' && !quoted) { row.push(field); field = ''; continue; }
    if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') i += 1;
      row.push(field); field = '';
      if (row.some((value) => value.length > 0)) rows.push(row);
      row = [];
      continue;
    }
    field += char;
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  const headers = rows.shift() ?? [];
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ''])));
}

function parseTimestamp(value, label) {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp) || !/[zZ]|[+-]\d{2}:?\d{2}$/.test(value)) {
    fail(`${label}: timestamp inválido ou sem timezone: ${value}`);
    return null;
  }
  return timestamp;
}

function validateSeed() {
  const seedPath = path.join(dbtRoot, 'seeds', 'mvp_test_events.csv');
  if (!exists(seedPath)) { fail(`seed ausente: ${seedPath}`); return; }
  const rows = parseCsv(read(seedPath));
  const headers = rows.length > 0 ? Object.keys(rows[0]) : [];
  const missing = requiredSeedColumns.filter((column) => !headers.includes(column));
  if (missing.length > 0) fail(`seed sem colunas obrigatórias: ${missing.join(', ')}`);
  else pass(`seed tem ${rows.length} registros e contrato mínimo completo`);
  if (rows.length === 0) { fail('seed vazio'); return; }

  const eventIds = new Set();
  const users = new Map();
  const modes = new Set();
  rows.forEach((row, index) => {
    const line = index + 2;
    if (!row.event_id) fail(`linha ${line}: event_id vazio`);
    if (eventIds.has(row.event_id)) fail(`linha ${line}: event_id duplicado: ${row.event_id}`);
    eventIds.add(row.event_id);
    if (row.is_test_data.toLowerCase() !== 'true') fail(`linha ${line}: is_test_data precisa ser true`);
    if (row.source_system !== 'synthetic_fixture') fail(`linha ${line}: source_system não identifica dataset controlado`);
    if (!/^user_pseudo_[a-z0-9_]+$/.test(row.user_pseudo_id)) fail(`linha ${line}: user_pseudo_id não parece pseudonimizado`);
    if (!users.has(row.user_pseudo_id)) users.set(row.user_pseudo_id, []);
    users.get(row.user_pseudo_id).push(row);
    for (const column of ['occurred_at', 'user_valid_from', 'observed_at', 'retrieved_at']) parseTimestamp(row[column], `linha ${line}/${column}`);
    const observedAt = parseTimestamp(row.observed_at, `linha ${line}/observed_at`);
    const retrievedAt = parseTimestamp(row.retrieved_at, `linha ${line}/retrieved_at`);
    if (observedAt !== null && retrievedAt !== null && retrievedAt < observedAt) fail(`linha ${line}: retrieved_at anterior a observed_at`);
    if (row.market_mode) modes.add(row.market_mode);
    for (const [kind, pattern] of piiPatterns) {
      if (Object.values(row).some((value) => pattern.test(value ?? ''))) fail(`linha ${line}: padrão de ${kind} encontrado no dataset`);
    }
  });
  if (modes.has('test') && modes.has('fallback')) pass('seed cobre degradação controlada com modos test e fallback');
  else fail('seed precisa cobrir os modos test e fallback');
  for (const [userId, userRows] of users) {
    if (userRows.some((row) => !row.user_version || !row.user_valid_from)) fail(`usuário ${userId}: versão SCD2 incompleta`);
    if (!userRows.some((row) => !row.user_valid_to)) fail(`usuário ${userId}: SCD2 sem versão corrente`);
  }
  if (errors.length === 0) pass('pseudonimização e marcadores de versão SCD2 verificados no seed');
}

function collectSqlFiles(directory) {
  if (!exists(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(directory, entry.name);
    return entry.isDirectory() ? collectSqlFiles(entryPath) : entry.name.endsWith('.sql') ? [entryPath] : [];
  });
}

function validateModels() {
  const modelFiles = collectSqlFiles(path.join(dbtRoot, 'models'));
  const modelNames = new Set(modelFiles.map((filePath) => path.basename(filePath, '.sql')));
  const missing = requiredModels.filter((model) => !modelNames.has(model));
  if (missing.length > 0) fail(`modelos dbt ausentes: ${missing.join(', ')}`);
  else pass(`${requiredModels.length} modelos dbt esperados encontrados`);
  const sql = modelFiles.map(read).join('\n');
  for (const [label, fragment] of [
    ['is_test_data', 'is_test_data'], ['origem de mercado', 'market_source'],
    ['observed_at', 'observed_at'], ['retrieved_at', 'retrieved_at'],
    ['marcador SCD2', 'is_current'], ['pseudonimização', 'user_pseudo_id'],
  ]) {
    if (sql.includes(fragment)) pass(`modelos preservam ${label}`); else fail(`modelos sem evidência de ${label}`);
  }
  for (const filePath of modelFiles) {
    const content = read(filePath);
    for (const [kind, pattern] of piiPatterns) if (pattern.test(content)) fail(`modelo ${path.basename(filePath)}: padrão de ${kind} encontrado`);
  }
  const userModel = path.join(dbtRoot, 'models', 'dimensions', 'dim_usuario.sql');
  if (exists(userModel)) for (const fragment of ['md5(', 'valid_from', 'valid_to', 'is_current']) if (!read(userModel).includes(fragment)) fail(`dim_usuario sem marcador SCD2: ${fragment}`);
  else fail('dim_usuario.sql ausente');
}

function validateSchema() {
  const schemaPath = path.join(dbtRoot, 'models', 'schema.yml');
  if (!exists(schemaPath)) { fail(`schema.yml ausente: ${schemaPath}`); return; }
  const schema = read(schemaPath);
  const missing = requiredModels.filter((model) => !schema.includes(`name: ${model}`));
  if (missing.length > 0) fail(`schema.yml sem modelos: ${missing.join(', ')}`); else pass('schema.yml documenta os modelos do contrato');
  for (const column of ['is_test_data', 'observed_at', 'retrieved_at', 'user_pseudo_id', 'is_current']) if (!schema.includes(column)) fail(`schema.yml sem contrato: ${column}`);
}

validateSeed();
validateModels();
validateSchema();
checks.forEach((message) => console.log(`PASS  ${message}`));
errors.forEach((message) => console.log(`FAIL  ${message}`));
console.log(`\nResultado: ${checks.length} validações aprovadas; ${errors.length} falhas.`);
if (errors.length > 0) {
  console.log('Ação: corrija o contrato e execute novamente. Este gate não acessa dbt, PostgreSQL ou rede.');
  process.exitCode = 1;
} else {
  console.log('Limite: dbt seed/run/test contra PostgreSQL ainda precisa ser executado em ambiente com profile fornecido.');
}
