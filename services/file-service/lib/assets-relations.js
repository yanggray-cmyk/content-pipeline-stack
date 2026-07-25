'use strict';
const assetManager = require('./asset-manager');

// ── Asset Relations ──────────────────────────────────────────────────────
// Manages relationships between assets:
// - character ↔ voice (linkedVoices)
// - character ↔ outfit (outfits list)
// - character ↔ reference (linkedReferences)
// - outfit ↔ character (linkedCharacterId)
// - reference ↔ character (linkedCharacterId)

const TYPE_TO_KEY = assetManager.TYPE_TO_KEY;

// Valid relation types and their reverse mappings
const RELATION_TYPES = {
  linkedVoices:      { assetType: 'voice',       reverseKey: 'linkedCharacters' },
  linkedCharacters:  { assetType: 'character',   reverseKey: 'linkedVoices' },
  linkedOutfits:     { assetType: 'outfit',      reverseKey: null },            // outfits stored in character
  linkedReferences:  { assetType: 'reference',   reverseKey: null },            // references stored in character
};

/**
 * Establish a relationship between two assets
 * @param {string} sourceId - Source asset ID
 * @param {string} targetId - Target asset ID
 * @param {string} relationType - Type of relationship
 */
function linkAssets(sourceId, targetId, relationType) {
  const index = assetManager.loadIndex();
  
  const source = assetManager.getAssetById(sourceId);
  const target = assetManager.getAssetById(targetId);
  
  if (!source) return { ok: false, error: 'Source asset not found', code: 'ASSET_NOT_FOUND' };
  if (!target) return { ok: false, error: 'Target asset not found', code: 'ASSET_NOT_FOUND' };
  
  const relDef = RELATION_TYPES[relationType];
  if (!relDef) return { ok: false, error: `Unknown relation type: ${relationType}`, code: 'VALIDATION_ERROR' };
  
  // Validate target type
  if (target.type !== relDef.assetType) {
    return { ok: false, error: `Target must be of type ${relDef.assetType}`, code: 'VALIDATION_ERROR' };
  }
  
  // Find source asset key
  let sourceKey = null;
  for (const [key, assets] of Object.entries(index.assets)) {
    if (assets[sourceId]) { sourceKey = key; break; }
  }
  if (!sourceKey) return { ok: false, error: 'Source asset not found in index', code: 'ASSET_NOT_FOUND' };
  
  // Add relation to source
  if (!index.assets[sourceKey][sourceId][relationType]) {
    index.assets[sourceKey][sourceId][relationType] = [];
  }
  if (!index.assets[sourceKey][sourceId][relationType].includes(targetId)) {
    index.assets[sourceKey][sourceId][relationType].push(targetId);
  }
  
  // Add reverse relation if defined
  if (relDef.reverseKey) {
    const targetKey = TYPE_TO_KEY[target.type];
    if (targetKey && index.assets[targetKey]) {
      if (!index.assets[targetKey][targetId][relDef.reverseKey]) {
        index.assets[targetKey][targetId][relDef.reverseKey] = [];
      }
      if (!index.assets[targetKey][targetId][relDef.reverseKey].includes(sourceId)) {
        index.assets[targetKey][targetId][relDef.reverseKey].push(sourceId);
      }
    }
  }
  
  // Special case: outfit → set linkedCharacterId on outfit
  if (relationType === 'linkedOutfits') {
    const outfitKey = TYPE_TO_KEY.outfit;
    if (outfitKey && index.assets[outfitKey] && index.assets[outfitKey][targetId]) {
      index.assets[outfitKey][targetId].linkedCharacterId = sourceId;
    }
  }
  
  // Special case: reference → set linkedCharacterId on reference
  if (relationType === 'linkedReferences') {
    const refKey = TYPE_TO_KEY.reference;
    if (refKey && index.assets[refKey] && index.assets[refKey][targetId]) {
      index.assets[refKey][targetId].linkedCharacterId = sourceId;
    }
  }
  
  index.assets[sourceKey][sourceId].updatedAt = new Date().toISOString();
  assetManager.saveIndex(index);
  
  return { ok: true, sourceId, targetId, relationType };
}

/**
 * Remove a relationship between two assets
 */
function unlinkAssets(sourceId, targetId, relationType) {
  const index = assetManager.loadIndex();
  
  const source = assetManager.getAssetById(sourceId);
  if (!source) return { ok: false, error: 'Source asset not found', code: 'ASSET_NOT_FOUND' };
  
  const relDef = RELATION_TYPES[relationType];
  if (!relDef) return { ok: false, error: `Unknown relation type: ${relationType}`, code: 'VALIDATION_ERROR' };
  
  // Find source
  let sourceKey = null;
  for (const [key, assets] of Object.entries(index.assets)) {
    if (assets[sourceId]) { sourceKey = key; break; }
  }
  if (!sourceKey) return { ok: false, error: 'Source not found', code: 'ASSET_NOT_FOUND' };
  
  // Remove from source
  if (index.assets[sourceKey][sourceId][relationType]) {
    index.assets[sourceKey][sourceId][relationType] = 
      index.assets[sourceKey][sourceId][relationType].filter(id => id !== targetId);
  }
  
  // Remove reverse relation
  if (relDef.reverseKey) {
    const targetKey = TYPE_TO_KEY[source.type === relDef.assetType ? source.type : 'character'];
    // Find target
    for (const [key, assets] of Object.entries(index.assets)) {
      if (assets[targetId] && key === (TYPE_TO_KEY[relDef.assetType] || key)) {
        if (assets[targetId][relDef.reverseKey]) {
          assets[targetId][relDef.reverseKey] = 
            assets[targetId][relDef.reverseKey].filter(id => id !== sourceId);
        }
        break;
      }
    }
  }
  
  index.assets[sourceKey][sourceId].updatedAt = new Date().toISOString();
  assetManager.saveIndex(index);
  
  return { ok: true, sourceId, targetId, relationType };
}

/**
 * Get all linked assets for a given asset
 */
function getLinkedAssets(assetId) {
  const asset = assetManager.getAssetById(assetId);
  if (!asset) return { ok: false, error: 'Asset not found', code: 'ASSET_NOT_FOUND' };
  
  const links = {};
  
  // Check all known relation fields
  const relationFields = ['linkedVoices', 'linkedCharacters', 'linkedOutfits', 'linkedReferences'];
  for (const field of relationFields) {
    if (asset[field] && asset[field].length > 0) {
      links[field] = asset[field].map(id => assetManager.getAssetById(id)).filter(Boolean);
    }
  }
  
  // Check linkedCharacterId (for outfits and references)
  if (asset.linkedCharacterId) {
    const char = assetManager.getAssetById(asset.linkedCharacterId);
    if (char) links.linkedCharacter = char;
  }
  
  return { ok: true, assetId, links };
}

/**
 * Clean up all references to a deleted asset
 * Called when an asset is deleted
 */
function cleanupReferences(assetId) {
  const index = assetManager.loadIndex();
  let cleaned = 0;
  
  for (const [key, assets] of Object.entries(index.assets)) {
    for (const [id, asset] of Object.entries(assets)) {
      let changed = false;
      
      // Remove from array fields
      for (const field of ['linkedVoices', 'linkedCharacters', 'linkedOutfits', 'linkedReferences']) {
        if (asset[field] && asset[field].includes(assetId)) {
          asset[field] = asset[field].filter(x => x !== assetId);
          changed = true;
        }
      }
      
      // Remove linkedCharacterId reference
      if (asset.linkedCharacterId === assetId) {
        asset.linkedCharacterId = null;
        changed = true;
      }
      
      if (changed) {
        cleaned++;
      }
    }
  }
  
  if (cleaned > 0) {
    assetManager.saveIndex(index);
  }
  
  return cleaned;
}

module.exports = {
  linkAssets,
  unlinkAssets,
  getLinkedAssets,
  cleanupReferences,
  RELATION_TYPES,
};
