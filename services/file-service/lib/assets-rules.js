'use strict';
const assetManager = require('./asset-manager');

// ── Asset Business Rules Engine ───────────────────────────────────────────
// Phase 5: Business logic for asset relationships and scene-aware matching
//
// Exported functions:
//   getCharacterOutfit(characterId, sceneKeywords) → outfit | null
//   getCharacterVoice(characterId) → voice | null
//   refreshVoiceExpiry(voiceId) → updated voice | null
//   assembleCharacterPackage(characterId, sceneKeywords) → package | null
//   isVoiceActive(voice) → boolean

/**
 * Normalize scene keywords: split by comma/punctuation, lowercase, trim
 */
function normalizeKeywords(scene) {
  if (!scene) return [];
  return scene
    .split(/[，,、。. ]+/)
    .map(k => k.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * Check if a voice is currently active (not expired)
 */
function isVoiceActive(voice) {
  if (!voice || voice.type !== 'voice') return false;
  if (!voice.expiresAt) return true; // No expiry = always active
  return new Date(voice.expiresAt) > new Date();
}

/**
 * Get days left until expiry (negative = expired)
 */
function getDaysLeft(voice) {
  if (!voice || !voice.expiresAt) return Infinity;
  return (new Date(voice.expiresAt) - new Date()) / (1000 * 60 * 60 * 24);
}

// ── TASK-5.1: 场景→服装匹配 ──────────────────────────────────────────────

/**
 * Find the best outfit for a character given a scene keyword.
 * Logic: outfit.sceneRules includes any of the scene keywords → match.
 * Returns the first matching outfit, or null if none match.
 *
 * @param {string} characterId - Character asset ID
 * @param {string} scene - Scene keyword(s), comma-separated
 * @returns {object|null} - Matching outfit asset, or null
 */
function getCharacterOutfit(characterId, scene) {
  const character = assetManager.getAssetById(characterId);
  if (!character || character.type !== 'character') return null;

  const sceneKeywords = normalizeKeywords(scene);
  if (sceneKeywords.length === 0) return null;

  // Get character's linked outfits (array of outfit IDs) - forward lookup
  let outfitIds = character.outfits || [];

  // If no outfits via forward lookup, try reverse lookup
  // (outfits with linkedCharacterId === characterId, set by linkAssets)
  if (outfitIds.length === 0) {
    const allOutfits = assetManager.listAssets({ type: 'outfit' });
    outfitIds = allOutfits
      .filter(o => o.linkedCharacterId === characterId)
      .map(o => o.id);
  }

  for (const outfitId of outfitIds) {
    const outfit = assetManager.getAssetById(outfitId);
    if (!outfit || outfit.type !== 'outfit') continue;

    const rules = outfit.sceneRules || [];
    const matched = sceneKeywords.some(keyword =>
      rules.some(rule => rule.toLowerCase().includes(keyword))
    );

    if (matched) {
      return outfit;
    }
  }

  return null; // No match
}

// ── TASK-5.2: 角色→音色绑定 ──────────────────────────────────────────────

/**
 * Get the first active (non-expired) voice linked to a character.
 * Logic: character.linkedVoices → first voice where isVoiceActive(voice) === true
 *
 * @param {string} characterId - Character asset ID
 * @returns {object|null} - First active voice asset, or null
 */
function getCharacterVoice(characterId) {
  const character = assetManager.getAssetById(characterId);
  if (!character || character.type !== 'character') return null;

  const voiceIds = character.linkedVoices || [];

  for (const voiceId of voiceIds) {
    const voice = assetManager.getAssetById(voiceId);
    if (voice && voice.type === 'voice' && isVoiceActive(voice)) {
      return voice;
    }
  }

  return null; // No active voice
}

// ── TASK-5.3: 克隆音色过期管理 ────────────────────────────────────────────

/**
 * Refresh a cloned voice's expiry to now + 7 days.
 * Only works on voice assets with source='cloned'.
 *
 * @param {string} voiceId - Voice asset ID
 * @returns {object|null} - Updated voice asset with new expiresAt, or null
 */
function refreshVoiceExpiry(voiceId) {
  const voice = assetManager.getAssetById(voiceId);
  if (!voice || voice.type !== 'voice') return null;

  // Only cloned voices can be refreshed
  if (voice.source !== 'cloned') {
    return { ok: false, error: 'Only cloned voices can be refreshed', code: 'INVALID_SOURCE' };
  }

  const newExpiresAt = new Date();
  newExpiresAt.setDate(newExpiresAt.getDate() + 7);

  const result = assetManager.updateAsset(voiceId, {
    expiresAt: newExpiresAt.toISOString(),
  });

  if (!result.ok) return null;

  const updated = assetManager.getAssetById(voiceId);
  return {
    ...updated,
    daysLeft: 7,
  };
}

// ── TASK-5.4: 角色参考包组装 ─────────────────────────────────────────────

/**
 * Assemble a complete reference package for a character.
 * Combines: character views + matched outfit + expressions + poses + active voice.
 *
 * @param {string} characterId - Character asset ID
 * @param {string} scene - Optional scene keyword for outfit matching
 * @returns {object|null} - Complete reference package
 */
function assembleCharacterPackage(characterId, scene) {
  const character = assetManager.getAssetById(characterId);
  if (!character || character.type !== 'character') return null;

  // 1. Character views (file IDs → URLs)
  const views = (character.views || {});
  const characterViews = {
    front: views.front || null,
    side: views.side || null,
    back: views.back || null,
  };

  // 2. Outfit (scene-aware matching)
  const outfit = scene ? getCharacterOutfit(characterId, scene) : null;
  const outfitData = outfit ? {
    id: outfit.id,
    name: outfit.name,
    sceneRules: outfit.sceneRules || [],
    views: outfit.views || {},
  } : null;

  // 3. Expressions
  const expressions = (character.expressions || []).map(expr => ({
    name: expr.name || '未命名表情',
    image: expr.fileId || null,
  }));

  // 4. Poses
  const poses = (character.poses || []).map(pose => ({
    name: pose.name || '未命名姿势',
    image: pose.fileId || null,
  }));

  // 5. Active voice
  const voice = getCharacterVoice(characterId);
  const voiceData = voice ? {
    id: voice.id,
    name: voice.name,
    voiceId: voice.voiceId,
    provider: voice.provider,
    source: voice.source,
    expiresAt: voice.expiresAt,
    daysLeft: voice.expiresAt ? Math.ceil(getDaysLeft(voice)) : null,
  } : null;

  return {
    characterId: character.id,
    characterName: character.name,
    characterViews,
    outfit: outfitData,
    expressions,
    poses,
    voice: voiceData,
    // scene used for matching
    sceneMatched: scene || null,
  };
}

// ── Exported API ─────────────────────────────────────────────────────────

module.exports = {
  isVoiceActive,
  getDaysLeft,
  normalizeKeywords,
  getCharacterOutfit,
  getCharacterVoice,
  refreshVoiceExpiry,
  assembleCharacterPackage,
};
