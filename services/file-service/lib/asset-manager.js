'use strict';
const fs     = require('fs');
const path   = require('path');
const crypto = require('crypto');

// ── Asset Manager ────────────────────────────────────────────────────────
// Manages asset-index.json: type registry + asset instances
// No database dependency, pure JSON file operations

const UPLOAD_DIR = process.env.UPLOAD_DIR || '/home/main/uploads';
const META_DIR   = path.join(UPLOAD_DIR, '.meta');
const INDEX_PATH = path.join(META_DIR, 'asset-index.json');
const BACKUP_PATH = INDEX_PATH + '.bak';

// ── Default type registry ───────────────────────────────────────────────

const DEFAULT_TYPES = {
  voice: {
    label: '音色',
    category: 'audio',
    fields: ['voiceId', 'source', 'provider', 'expiresAt', 'meta'],
    fileTypes: ['audio/wav', 'audio/mp3', 'audio/mpeg'],
  },
  character: {
    label: '角色',
    category: 'image',
    fields: ['alias', 'role', 'views', 'outfits', 'volc_asset_id', 'real_person', 'tags', 'meta'],
    fileTypes: ['image/png', 'image/jpeg', 'image/webp'],
  },
  reference: {
    label: '参考图',
    category: 'image',
    fields: ['refCategory', 'promptHint', 'styleTags'],
    fileTypes: ['image/png', 'image/jpeg', 'image/webp'],
  },
  outfit: {
    label: '服装',
    category: 'image',
    fields: ['sceneRules', 'views'],
    fileTypes: ['image/png', 'image/jpeg', 'image/webp'],
  },
  scene: {
    label: '场景',
    category: 'image',
    fields: ['sceneType', 'lighting', 'mood'],
    fileTypes: ['image/png', 'image/jpeg', 'image/webp'],
  },
};

const DEFAULT_ASSETS = {
  voices: {},
  characters: {},
  references: {},
  outfits: {},
  scenes: {},
};

// Type → assets key mapping
const TYPE_TO_KEY = {
  voice: 'voices',
  character: 'characters',
  reference: 'references',
  outfit: 'outfits',
  scene: 'scenes',
};

// ── Index operations ─────────────────────────────────────────────────────

let _cache = null;
let _cacheTime = 0;
const CACHE_TTL = 1000; // 1s cache to avoid excessive reads

/**
 * Load asset index from disk (with short cache)
 */
function loadIndex() {
  const now = Date.now();
  if (_cache && (now - _cacheTime) < CACHE_TTL) return _cache;

  if (!fs.existsSync(INDEX_PATH)) {
    // Create default index
    const defaultIndex = {
      version: '1.0',
      types: { ...DEFAULT_TYPES },
      assets: { ...DEFAULT_ASSETS },
    };
    saveIndex(defaultIndex, true);
    return defaultIndex;
  }

  try {
    const raw = fs.readFileSync(INDEX_PATH, 'utf8');
    _cache = JSON.parse(raw);
    _cacheTime = now;

    // Ensure structure integrity
    if (!_cache.types) _cache.types = { ...DEFAULT_TYPES };
    if (!_cache.assets) _cache.assets = { ...DEFAULT_ASSETS };
    for (const [key, def] of Object.entries(DEFAULT_ASSETS)) {
      if (!_cache.assets[key]) _cache.assets[key] = def;
    }

    return _cache;
  } catch (err) {
    console.error('[asset-manager] Failed to load index, using backup:', err.message);
    // Try backup
    if (fs.existsSync(BACKUP_PATH)) {
      try {
        const raw = fs.readFileSync(BACKUP_PATH, 'utf8');
        _cache = JSON.parse(raw);
        _cacheTime = now;
        return _cache;
      } catch {
        // Both failed, create fresh
        console.error('[asset-manager] Backup also failed, creating fresh index');
      }
    }
    const fresh = {
      version: '1.0',
      types: { ...DEFAULT_TYPES },
      assets: { ...DEFAULT_ASSETS },
    };
    saveIndex(fresh, true);
    return fresh;
  }
}

/**
 * Save asset index to disk (with backup)
 */
function saveIndex(index, skipCache = false) {
  if (!skipCache) {
    _cache = index;
    _cacheTime = Date.now();
  }
  // Backup first
  if (fs.existsSync(INDEX_PATH)) {
    try { fs.copyFileSync(INDEX_PATH, BACKUP_PATH); } catch {}
  }
  fs.writeFileSync(INDEX_PATH, JSON.stringify(index, null, 2));
}

/**
 * Get types registry
 */
function getTypes() {
  const index = loadIndex();
  return index.types;
}

/**
 * Register a new type
 */
function registerType(typeName, typeDef) {
  const index = loadIndex();
  if (index.types[typeName]) {
    return { ok: false, error: `Type ${typeName} already exists` };
  }
  index.types[typeName] = typeDef;
  index.assets[typeName + 's'] = {}; // Create empty asset store
  saveIndex(index);
  return { ok: true };
}

// ── Asset CRUD ───────────────────────────────────────────────────────────

/**
 * List assets, optionally filtered by type
 */
function listAssets(filters = {}) {
  const index = loadIndex();
  let results = [];

  if (filters.type) {
    const key = TYPE_TO_KEY[filters.type];
    if (key && index.assets[key]) {
      results = Object.values(index.assets[key]);
    }
  } else {
    // All types
    for (const [, assets] of Object.entries(index.assets)) {
      results.push(...Object.values(assets));
    }
  }

  // Apply filters
  if (filters.role) results = results.filter(a => a.role === filters.role);
  if (filters.status) results = applyStatusFilter(results, filters.status);
  if (filters.tags) results = results.filter(a =>
    (a.tags || []).some(t => filters.tags.includes(t))
  );
  if (filters.search) {
    const q = filters.search.toLowerCase();
    results = results.filter(a =>
      (a.name || '').toLowerCase().includes(q) ||
      (a.alias || []).some(x => x.toLowerCase().includes(q)) ||
      (a.tags || []).some(t => t.toLowerCase().includes(q)) ||
      (a.description || '').toLowerCase().includes(q)
    );
  }

  return results;
}

/**
 * Get asset by ID (searches all types)
 */
function getAssetById(id) {
  const index = loadIndex();
  for (const [, assets] of Object.entries(index.assets)) {
    if (assets[id]) return assets[id];
  }
  return null;
}

/**
 * Create a new asset
 */
function createAsset(data) {
  const index = loadIndex();

  // Validate type
  if (!data.type) return { ok: false, error: 'Asset type required', code: 'VALIDATION_ERROR' };
  if (!index.types[data.type]) {
    return { ok: false, error: `Unknown type: ${data.type}`, code: 'ASSET_TYPE_UNKNOWN' };
  }

  const key = TYPE_TO_KEY[data.type];
  if (!key) {
    return { ok: false, error: `No asset key for type: ${data.type}`, code: 'ASSET_TYPE_UNKNOWN' };
  }

  // Generate ID
  const id = data.id || `${data.type}_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
  if (index.assets[key][id]) {
    return { ok: false, error: 'Asset ID already exists', code: 'VALIDATION_ERROR' };
  }

  const now = new Date().toISOString();
  const asset = {
    id,
    type: data.type,
    name: data.name || 'Unnamed',
    createdAt: now,
    updatedAt: now,
    tags: data.tags || [],
    description: data.description || '',
    // Merge type-specific fields
    ...data,
  };

  index.assets[key][id] = asset;
  saveIndex(index);
  return { ok: true, data: asset };
}

/**
 * Update an asset (partial update)
 */
function updateAsset(id, updates) {
  const index = loadIndex();

  for (const [, assets] of Object.entries(index.assets)) {
    if (assets[id]) {
      // Don't allow changing id or type
      delete updates.id;
      delete updates.type;

      assets[id] = { ...assets[id], ...updates, updatedAt: new Date().toISOString() };
      saveIndex(index);
      return { ok: true, data: assets[id] };
    }
  }

  return { ok: false, error: 'Asset not found', code: 'ASSET_NOT_FOUND' };
}

/**
 * Delete an asset
 */
function deleteAsset(id) {
  const index = loadIndex();

  for (const [key, assets] of Object.entries(index.assets)) {
    if (assets[id]) {
      delete assets[id];
      saveIndex(index);
      return { ok: true, deleted: id };
    }
  }

  return { ok: false, error: 'Asset not found', code: 'ASSET_NOT_FOUND' };
}

// ── Import / Export ──────────────────────────────────────────────────────

/**
 * Export assets as JSON
 */
function exportAssets(type = null) {
  const index = loadIndex();
  if (type) {
    const key = TYPE_TO_KEY[type];
    return { ok: true, data: key ? index.assets[key] || {} : {} };
  }
  return { ok: true, data: index.assets };
}

/**
 * Import assets from JSON
 */
function importAssets(assetsData, mode = 'skip') {
  // mode: 'skip' | 'update' | 'overwrite'
  const index = loadIndex();
  let imported = 0;
  let skipped = 0;

  for (const asset of Array.isArray(assetsData) ? assetsData : []) {
    if (!asset.type || !asset.id) {
      skipped++;
      continue;
    }
    const key = TYPE_TO_KEY[asset.type];
    if (!key || !index.assets[key]) {
      skipped++;
      continue;
    }

    if (index.assets[key][asset.id]) {
      if (mode === 'skip') { skipped++; continue; }
      if (mode === 'update') {
        index.assets[key][asset.id] = { ...index.assets[key][asset.id], ...asset, updatedAt: new Date().toISOString() };
        imported++;
        continue;
      }
      if (mode === 'overwrite') {
        index.assets[key][asset.id] = asset;
        imported++;
        continue;
      }
    }

    // New asset
    index.assets[key][asset.id] = asset;
    imported++;
  }

  saveIndex(index);
  return { ok: true, imported, skipped };
}

// ── Helpers ──────────────────────────────────────────────────────────────

function applyStatusFilter(assets, status) {
  if (!status) return assets;
  const now = new Date();
  return assets.filter(a => {
    if (!a.expiresAt) {
      // No expiry = always active
      return status === 'active';
    }
    const expires = new Date(a.expiresAt);
    const remaining = (expires - now) / (1000 * 60 * 60 * 24); // days
    switch (status) {
      case 'active':   return remaining > 0;
      case 'expiring': return remaining > 0 && remaining <= 3;
      case 'expired':  return remaining <= 0;
      default:         return true;
    }
  });
}

module.exports = {
  loadIndex,
  saveIndex,
  getTypes,
  registerType,
  listAssets,
  getAssetById,
  createAsset,
  updateAsset,
  deleteAsset,
  exportAssets,
  importAssets,
  TYPE_TO_KEY,
};
