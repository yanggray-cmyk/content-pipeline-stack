'use strict';
const express = require('express');
const multer  = require('multer');
const sharp   = require('sharp');
const cors    = require('cors');
const fs      = require('fs');
const path    = require('path');
const crypto  = require('crypto');

// ── Asset modules ────────────────────────────────────────────────────────
const assetManager = require('./lib/asset-manager');
const assetsRelations = require('./lib/assets-relations');
const assetsRules = require('./lib/assets-rules');

const UPLOAD_DIR = process.env.UPLOAD_DIR || '/home/main/uploads';
const PORT      = process.env.PORT || 18098;

// v8.119.40+ dz (铁律 72-74): audit log 目录
const AUDIT_DIR = process.env.AUDIT_DIR || '/home/main/.openclaw/data/audit/file-service';
if (!fs.existsSync(AUDIT_DIR)) fs.mkdirSync(AUDIT_DIR, { recursive: true });

// 确保上传目录存在
if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const app = express();
app.use(cors());
// v8.118: /upload/chunk 需要接收 2MB+ binary stream，不被任何中间件 buffer
//  使用 conditional skip：仅跳过 /upload/chunk，其他路由仍走 express.json
app.use((req, res, next) => {
  // v8.118.6: /upload/merge 是 JSON body (merge params), /upload/chunk 是 binary stream
  // 只有 /upload/chunk 需要跳过 parser
  if (req.path === '/upload/chunk') {
    return next();  // 跳过 body parser，纯 stream
  }
  express.json({ limit: '10mb' })(req, res, next);
});
// 静态页面（v8.119.40+ ae: 用 fs.readFileSync 替代 res.sendFile，绕开 express 5.2.1 + send 1.2.1 NotFoundError bug）
function sendStaticFile(res, filename, contentType = 'text/html') {
  try {
    const data = fs.readFileSync(path.join(__dirname, filename));
    res.type(contentType).send(data);
  } catch (e) {
    console.error(`[static] ${filename} read error:`, e.message);
    res.status(500).send(`Error loading ${filename}: ${e.message}`);
  }
}
app.get('/', (_req, res) => sendStaticFile(res, 'index.html'));
app.get('/videos', (_req, res) => sendStaticFile(res, 'videos.html'));

// ── Multer 配置：磁盘存储，原文件名 + UUID ──────────────────────────────
const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, UPLOAD_DIR),
  filename: (req, file, cb) => {
    const ext   = path.extname(file.originalname);
    const uuid  = crypto.randomUUID();
    const date  = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    cb(null, `${date}-${uuid}${ext}`);
  }
});
const upload = multer({
  storage,
  limits: { fileSize: 500 * 1024 * 1024 }, // 500MB
  // v8.119.41: 中文 filename multipart header 走 UTF-8 (multer 2.1.1 默认 latin1 → 乱码)
  defParamCharset: 'utf8',
});

// ── 文件元数据存储（JSON 文件，够用且无额外依赖）────────────────────────
const META_DIR = path.join(UPLOAD_DIR, '.meta');
if (!fs.existsSync(META_DIR)) fs.mkdirSync(META_DIR, { recursive: true });
function metaPath(id) { return path.join(META_DIR, `${id}.json`); }
function saveMeta(file) {
  const meta = {
    id: file.id,
    originalName: file.originalName,
    filename: file.filename,
    size: file.size,
    mimeType: file.mimeType,
    uploadedAt: file.uploadedAt,
    tags: file.tags || [],
    description: file.description || '',
    category: file.category || 'default',
    customMeta: file.customMeta && typeof file.customMeta === 'object' ? file.customMeta : {},
  };
  fs.writeFileSync(metaPath(file.id), JSON.stringify(meta, null, 2));
  return meta;
}
function loadMeta(id) {
  const p = metaPath(id);
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
}
function listMeta() {
  if (!fs.existsSync(META_DIR)) return [];
  return fs.readdirSync(META_DIR)
    .filter(f => f.endsWith('.json'))
    .map(f => { try { return JSON.parse(fs.readFileSync(path.join(META_DIR, f), 'utf8')); } catch { return null; } })
    .filter(Boolean)
    .sort((a, b) => b.uploadedAt - a.uploadedAt);
}

// ── 文件类型判断 ────────────────────────────────────────────────────────
function isImage(mime) { return mime?.startsWith('image/'); }
function isVideo(mime) { return mime?.startsWith('video/'); }
function isPdf(mime)    { return mime === 'application/pdf'; }

// ── 自动打标签引擎 (v8.119.17) ──────────────────────────────────────────
// 规则驱动的标签推断：MIME 类型 + 文件名模式 + 分类 + 日期 + 房间名
function autoTag(file) {
  const tags = new Set();
  const name = file.originalName || file.filename || '';
  const mime = file.mimeType || '';
  const cat  = file.category || 'default';

  // 1. MIME 类型 → 基础类型标签
  if (mime.startsWith('video/'))       tags.add('video');
  if (mime.startsWith('image/'))       tags.add('image');
  if (mime.startsWith('audio/'))       tags.add('audio');
  if (mime === 'application/x-subrip') tags.add('subtitle');
  if (name.toLowerCase().endsWith('.srt')) tags.add('subtitle');
  if (mime === 'text/markdown' || name.toLowerCase().endsWith('.md')) {
    // 小于 200KB 的 .md 默认为转录文件 (大文件可能是文档)
    if (file.size < 200 * 1024) tags.add('transcript');
  }

  // 2. Category → 系统标签
  if (cat === 'douyin-transcribe') {
    tags.add('douyin');
    tags.add('transcribe');
  }
  if (cat === 'douyin-recorder') {
    tags.add('douyin');
    tags.add('recording');
  }
  if (cat === 'gif') tags.add('gif');

  // 3. 文件名模式 → 上下文标签
  if (/直播|live/i.test(name))                tags.add('douyin');
  if (/拍宝|拍卖|翰墨/i.test(name))           tags.add('auction');
  if (/培训|授课|课程|教学/i.test(name))      tags.add('training');
  if (/带货|主播|购物/i.test(name))           tags.add('sales');
  if (/楼盘|开盘|看房|地产/.test(name))       tags.add('realestate');

  // 4. 日期提取 → YYYY-MM-DD 日标签
  const dateMatch = name.match(/(\d{4}-\d{2}-\d{2})/);
  if (dateMatch) tags.add(dateMatch[1]);

  // 5. 直播/录制房间名识别
  if (/大雅|大雅说|大雅培训|大雅直播/.test(name))  tags.add('dayashuo');
  if (/嘉棠|嘉棠雅序/.test(name))                  tags.add('jiatang');
  if (/家琪|jiaqi/i.test(name))                   tags.add('jiaqi');
  if (/北京|beijing/i.test(name))                 tags.add('beijing');

  // 6. 同上传日期 tag (videos 里跨文件分组)
  if (file.uploadedAt) {
    const d = new Date(file.uploadedAt).toISOString().slice(0, 10);
    if (d) tags.add(d);
  }

  return Array.from(tags);
}

// 合并已有标签 + 自动推断标签 + customMeta.tags（保留 user-tagged）
// v8.119.40+ au-fix: 之前 customMeta.tags 只存 metadata，tags 字段没合并 → 上传时丢失
function mergedAutoTags(file) {
  const auto = autoTag(file);
  const existing = file.tags || [];
  const customTags = (file.customMeta && Array.isArray(file.customMeta.tags)) ? file.customMeta.tags : [];
  // 自动 tag 不覆盖 user tag；仅补充缺失的；customMeta.tags 也合并
  const set = new Set([...existing, ...customTags, ...auto]);
  return Array.from(set);
}

// ── 工具：获取文件流和 head 信息 ─────────────────────────────────────────
// v8.119.42: 修复下载文件名显示 — 旧版把整个 filename URL-encode 后放 filename="..."
//   → 浏览器看到 %E5%B0%8F%E4%BC%99... 当成字面字符串当文件名
//   修复: 用 RFC 5987 filename*=UTF-8''<urlencoded> (Chrome/Firefox/Edge/Safari 都支持)
//   + filename=ASCII fallback (旧 IE/curl)
//
// v8.119.43: Thunder (迅雷) 对 RFC 5987 filename* 支持不全, 仍优先用 filename="..."
//   而且它看到下划线串会截断到 .mp4 之前的部分 → 丢失 .mp4 后缀
//   修复: ASCII fallback 用 BVID + 平台 + .mp4 (稳定 100% ASCII + 明确 .mp4 结尾)
//         中文完整名走 filename* 给现代浏览器
function sendFile(res, filePath, filename, mimeType) {
  res.setHeader('Content-Type', mimeType || 'application/octet-stream');
  const utf8Encoded = encodeURIComponent(filename);
  // 抽取 BVID / 平台 ID 作为 ASCII fallback (B站: BV...  抖音: aweme_...)
  let asciiName = filename.replace(/[^\x20-\x7e]/g, '_');
  const bvidMatch = filename.match(/BV[0-9A-Za-z]+/);
  const awemeMatch = filename.match(/aweme_\d+/);
  if (bvidMatch) {
    asciiName = `${bvidMatch[0]}.mp4`;
  } else if (awemeMatch) {
    asciiName = `${awemeMatch[0]}.mp4`;
  } else {
    asciiName = `brand-video-${Date.now()}.mp4`;
  }
  res.setHeader('Content-Disposition',
    `attachment; filename="${asciiName}"; filename*=UTF-8''${utf8Encoded}`);
  fs.createReadStream(filePath).pipe(res);
}

// ════════════════════════════════════════════════════════════════════════
// 路由
// ════════════════════════════════════════════════════════════════════════

// GET /files — 列表
app.get('/files', (req, res) => {
  let files = listMeta();
  if (req.query.category) {
    files = files.filter(f => f.category === req.query.category);
  }
  // 按 mimeType 前缀过滤 (v8.119.16): ?type=video|audio|image|text|subtitle|transcript
  if (req.query.type) {
    const typePrefixMap = {
      video: ['video/'],
      audio: ['audio/'],
      image: ['image/'],
      text: ['text/'],
      subtitle: ['text/plain', 'application/x-subrip', 'text/srt'],
      transcript: ['text/markdown', 'text/x-markdown', 'text/plain'],  // .md / .srt / .txt
      gif: ['image/gif'],
    };
    const allowed = typePrefixMap[req.query.type];
    if (allowed) {
      files = files.filter(f =>
        allowed.some(prefix => (f.mimeType || '').startsWith(prefix))
      );
    } else {
      // 未知类型: 仅返回 exact match mimeType=...
      files = files.filter(f => (f.mimeType || '') === req.query.type);
    }
    // v8.119.40+ w: ?type=video 默认排除抖音直播录屏 (tag 含 douyin-live-record)
    // 边界: 直播录屏走 /douyin-files, 短视频素材走 /videos
    // 绕过: ?includeLive=true 或 ?excludeTags=
    if (req.query.type === 'video' && req.query.includeLive !== 'true' && !req.query.excludeTags) {
      const before = files.length;
      files = files.filter(f => !(f.tags || []).includes('douyin-live-record'));
      console.log(`[files] excluded ${before - files.length} live-record videos (v8.119.40+ w)`);
    }
  }
  // 按 tag 过滤 (支持多个, 用逗号分隔 — OR 语义)
  if (req.query.tags) {
    const wantTags = req.query.tags.split(',').map(t => t.trim()).filter(Boolean);
    if (wantTags.length) {
      files = files.filter(f => {
        const fTags = f.tags || [];
        return wantTags.some(t => fTags.includes(t));
      });
    }
  }
  // v8.119.40+ w: 自定义 excludeTags (逗号分隔, OR 排除 — 任一命中即排除)
  if (req.query.excludeTags) {
    const banTags = req.query.excludeTags.split(',').map(t => t.trim()).filter(Boolean);
    if (banTags.length) {
      files = files.filter(f => {
        const fTags = f.tags || [];
        return !banTags.some(t => fTags.includes(t));
      });
    }
  }
  res.json({ ok: true, files, count: files.length });
});

// GET /categories — 列出所有分类及文件数量
app.get('/categories', (req, res) => {
  const files = listMeta();
  const categories = {};
  for (const f of files) {
    const cat = f.category || 'default';
    if (!categories[cat]) categories[cat] = 0;
    categories[cat]++;
  }
  res.json({ ok: true, categories });
});

// PATCH /files/:id — 更新文件元数据（如移动分类）
// NAMING-CONVENTION §4.1: originalName 含文件扩展名后缀 → 400 拒绝
const FORBIDDEN_SUFFIX_RE = /\.(mp4|md|srt|json|jpg|jpeg|png|gif|pdf|txt|wav|mp3|m4a)$/i;

// v8.119.40+ dz (铁律 72): title 占位符检测常量
// 1. douyin_<id> / douyin-<id> — batch 上传脚本 fallback 占位符 (batch_v5_daya.py)
// 2. 抖音记录美好生活... — douyin API 返回的水印式 boilerplate
// 3. YYYY-MM-DD-{uuid8} — UUID 风格文件名 (videos.html 旧 fallback 浮现)
const PLACEHOLDER_TITLE_PATTERNS = [
  /^douyin[_-]\d+/,
  /抖音记录美好生活/,
  /^\d{4}-\d{2}-\d{2}-[a-f0-9]{8}/i,
];

// 检测 title 是不是 placeholder 模式
function isPlaceholderTitle(title) {
  if (!title || typeof title !== 'string') return true;
  return PLACEHOLDER_TITLE_PATTERNS.some(p => p.test(title));
}
// PATCH /files/:id — 更新文件元数据（如移动分类）
// NAMING-CONVENTION §4.1: originalName 含文件扩展名后缀 → 400 拒绝
// v8.119.40+ dz (铁律 72): PATCH 写入 placeholder title 必须 reject (一次性记录到 placeholder_audit.log)
// v8.119.40+ dz (铁律 73): PATCH 写入 author 变更必须 audit log (从玉之源 276 文件错配事件总结)
// v8.119.40+ dz (铁律 74): POST /upload 加 aweme_id 唯一性 check (出现重复返回 409 + 旧 file_id)
app.patch('/files/:id', (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  const updates = {};
  if (typeof req.body.category === 'string') updates.category = req.body.category;
  if (typeof req.body.name === 'string') {
    if (FORBIDDEN_SUFFIX_RE.test(req.body.name)) {
      return res.status(400).json({
        ok: false,
        error: 'originalName 含文件扩展名后缀，禁止（铁律 12 + NAMING-CONVENTION §4.1）'
      });
    }
    updates.originalName = req.body.name;
  }
  if (req.body.tags) updates.tags = req.body.tags;
  if (typeof req.body.description === 'string') updates.description = req.body.description;
  if (req.body.customMeta && typeof req.body.customMeta === 'object' && req.body.customMeta !== null) {
    // v8.119.40+ dz: 如果 customMeta 有 title, 检测是否 placeholder
    if (req.body.customMeta.title !== undefined && isPlaceholderTitle(req.body.customMeta.title)) {
      // 记录 placeholder 写入但仍 reject (上传脚本必须修)
      try {
        const auditLog = path.join(AUDIT_DIR, 'placeholder_audit.log');
        fs.appendFileSync(auditLog, JSON.stringify({
          ts: new Date().toISOString(),
          route: 'PATCH /files/:id',
          file_id: req.params.id,
          attempted_title: req.body.customMeta.title,
          ip: req.ip || req.headers['x-forwarded-for'] || 'unknown',
          ua: req.headers['user-agent'] || 'unknown',
          existing_title: meta.customMeta?.title || '',
        }) + '\n');
      } catch (e) {}
      return res.status(400).json({
        ok: false,
        error: `title 是 placeholder 模式: "${req.body.customMeta.title}"。禁止写入。铁律 72 + douyin API 真源 + 需调用方立即修(调用 scripts/backfill_placeholder_titles.py 从 dayi_all_v1 下载真源)`
      });
    }
    // v8.119.40+ dz (铁律 73): author 变更 audit log (玉之源错配事件总结)
    if (req.body.customMeta.author !== undefined && req.body.customMeta.author !== meta.customMeta?.author) {
      try {
        const auditLog = path.join(AUDIT_DIR, 'author_change_audit.log');
        fs.appendFileSync(auditLog, JSON.stringify({
          ts: new Date().toISOString(),
          route: 'PATCH /files/:id',
          file_id: req.params.id,
          old_author: meta.customMeta?.author || '',
          new_author: req.body.customMeta.author,
          ip: req.ip || req.headers['x-forwarded-for'] || 'unknown',
          ua: req.headers['user-agent'] || 'unknown',
          original_creator: meta.customMeta?.original_creator || '',
        }) + '\n');
      } catch (e) {}
    }
    updates.customMeta = { ...(meta.customMeta || {}), ...req.body.customMeta };
  }
  const merged = { ...meta, ...updates };
  saveMeta(merged);
  res.json({ ok: true, file: merged });
});

// GET /files/:id — 详情
app.get('/files/:id', (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  const category = meta.category || 'default';
  const filePath = path.join(UPLOAD_DIR, category, meta.filename);
  meta.exists = fs.existsSync(filePath);
  res.json({ ok: true, file: meta });
});

// ── Chunk Upload API (分片上传 + 断点续传) ──────────────────────────────
const CHUNK_DIR = path.join(UPLOAD_DIR, '.chunks');
if (!fs.existsSync(CHUNK_DIR)) fs.mkdirSync(CHUNK_DIR, { recursive: true });

// POST /upload/chunk — 上传单个分片（binary body，v8.118 改流式写入）
app.post('/upload/chunk', (req, res) => {
  const uploadId = req.query.uploadId;
  const chunkIndex = parseInt(req.query.chunkIndex);
  const totalChunks = parseInt(req.query.totalChunks);
  // v8.118: fileName 优先读 X-File-Name header (base64)，防 nginx 对中文 URL 返回 400
  //   fallback 到 query.fileName 供已 encodeURIComponent 的前端用
  let fileName = 'unknown';
  if (req.headers['x-file-name']) {
    try { fileName = Buffer.from(req.headers['x-file-name'], 'base64').toString('utf8'); } catch {}
  } else if (req.query.fileName) {
    fileName = req.query.fileName;
  }
  const category = (req.query.category || 'default').replace(/[^a-zA-Z0-9_-]/g, '');
  if (!uploadId || isNaN(chunkIndex)) return res.status(400).json({ ok: false, error: 'Missing uploadId or chunkIndex' });
  const chunkDir = path.join(CHUNK_DIR, uploadId);
  if (!fs.existsSync(chunkDir)) fs.mkdirSync(chunkDir, { recursive: true });
  const chunkPath = path.join(chunkDir, `chunk_${chunkIndex}`);
  // v8.118: 流式写入避免 writeFileSync 阻塞事件循环 + 内存爆冲
  const writeStream = fs.createWriteStream(chunkPath);
  let bytesWritten = 0;
  req.on('data', c => {
    bytesWritten += c.length;
    if (!writeStream.write(c)) {
      // backpressure: 暂停接收请求数据
      req.pause();
      writeStream.once('drain', () => req.resume());
    }
  });
  req.on('end', () => {
    writeStream.end(() => {
      res.json({ ok: true, uploadId, chunkIndex, bytes: bytesWritten });
    });
  });
  req.on('error', err => {
    writeStream.destroy();
    if (!res.headersSent) res.status(500).json({ ok: false, error: err.message });
  });
  writeStream.on('error', err => {
    if (!res.headersSent) res.status(500).json({ ok: false, error: err.message });
  });
});

// GET /upload/status/:uploadId — 查询已上传分片（断点续传）
app.get('/upload/status/:uploadId', (req, res) => {
  const { uploadId } = req.params;
  const chunkDir = path.join(CHUNK_DIR, uploadId);
  if (!fs.existsSync(chunkDir)) return res.json({ ok: true, uploadId, uploadedChunks: [] });
  const files = fs.readdirSync(chunkDir);
  const uploadedChunks = files
    .filter(f => f.startsWith('chunk_'))
    .map(f => parseInt(f.replace('chunk_', '')))
    .filter(n => !isNaN(n))
    .sort((a, b) => a - b);
  res.json({ ok: true, uploadId, uploadedChunks });
});

// POST /upload/merge — 合并分片为完整文件
app.post('/upload/merge', async (req, res) => {
  const { uploadId, fileName, totalChunks, category } = req.body;
  if (!uploadId || !fileName || totalChunks === undefined) return res.status(400).json({ ok: false, error: 'Missing required fields' });
  const cat = (category || 'default').replace(/[^a-zA-Z0-9_-]/g, '');
  const chunkDir = path.join(CHUNK_DIR, uploadId);
  const categoryDir = path.join(UPLOAD_DIR, cat);
  if (!fs.existsSync(categoryDir)) fs.mkdirSync(categoryDir, { recursive: true });
  const ext = path.extname(fileName);
  const uuid = crypto.randomUUID();
  const date = new Date().toISOString().slice(0, 10);
  const finalFilename = `${date}-${uuid}${ext}`;
  const finalPath = path.join(categoryDir, finalFilename);
  try {
    // v8.118.6: 先检查所有 chunks 都存在 (避免写了一半 reject 残留文件)
    for (let i = 0; i < totalChunks; i++) {
      const cp = path.join(chunkDir, `chunk_${i}`);
      if (!fs.existsSync(cp)) {
        // 清理临时 finalPath 文件 (避免残留)
        try { fs.unlinkSync(finalPath); } catch (e) {}
        return res.status(400).json({ ok: false, error: `Missing chunk ${i} (have ${[...Array(totalChunks).keys()].filter(j => fs.existsSync(path.join(chunkDir, `chunk_${j}`))).join(',')})` });
      }
    }
    // 使用 Promise 确保写入完成后再继续
    await new Promise((resolve, reject) => {
      const out = fs.createWriteStream(finalPath);
      out.on('finish', resolve);
      out.on('error', reject);
      for (let i = 0; i < totalChunks; i++) {
        const cp = path.join(chunkDir, `chunk_${i}`);
        out.write(fs.readFileSync(cp));
      }
      out.end();
    });
    // 清理分片
    fs.rmSync(chunkDir, { recursive: true, force: true });
    // 保存元数据
    const stats = fs.statSync(finalPath);
    const mimeType = 'application/octet-stream'; // fallback, could use mime-types
    const file = {
      id: path.basename(finalFilename, ext),
      originalName: fileName,
      filename: finalFilename,
      size: stats.size,
      mimeType,
      category: cat,
      customMeta: {},
      uploadedAt: Date.now(),
    };
    file.tags = mergedAutoTags(file); // v8.119.17: 自动打标签
    saveMeta(file);
    res.json({ ok: true, file: { id: file.id, originalName: file.originalName, size: file.size, mimeType: file.mimeType, category: file.category } });
  } catch (err) { res.status(500).json({ ok: false, error: err.message }); }
});

// POST /upload — 上传文件（按 category 分目录存储）
app.post('/upload', upload.single('file'), (req, res) => {
  if (!req.file) return res.status(400).json({ ok: false, error: 'No file received' });
  const category = (req.body.category || 'default').replace(/[^a-zA-Z0-9_-]/g, '');
  // 按 category 分目录：/home/main/uploads/{category}/filename
  const categoryDir = path.join(UPLOAD_DIR, category);
  if (!fs.existsSync(categoryDir)) fs.mkdirSync(categoryDir, { recursive: true });
  // 移动文件到子目录
  const oldPath = req.file.path;
  const newPath = path.join(categoryDir, req.file.filename);
  fs.renameSync(oldPath, newPath);
  // 解析 customMeta (form-data 字符串 → 对象)
  let customMeta = {};
  if (typeof req.body.customMeta === 'string' && req.body.customMeta.trim()) {
    try { customMeta = JSON.parse(req.body.customMeta); }
    catch (e) { console.warn(`[upload] customMeta JSON.parse 失败: ${e.message}, 忽略`); }
  } else if (typeof req.body.customMeta === 'object' && req.body.customMeta !== null) {
    customMeta = req.body.customMeta;
  }
  // v8.119.40+ dz (铁律 72): 上传时检测 title 是不是 placeholder, 是则 reject
  if (customMeta.title !== undefined && isPlaceholderTitle(customMeta.title)) {
    try {
      fs.unlinkSync(newPath); // 清理已移动的文件
    } catch (e) {}
    try {
      const auditLog = path.join(AUDIT_DIR, 'placeholder_audit.log');
      fs.appendFileSync(auditLog, JSON.stringify({
        ts: new Date().toISOString(),
        route: 'POST /upload',
        attempted_title: customMeta.title,
        ip: req.ip || req.headers['x-forwarded-for'] || 'unknown',
        ua: req.headers['user-agent'] || 'unknown',
      }) + '\n');
    } catch (e) {}
    return res.status(400).json({
      ok: false,
      error: `title 是 placeholder 模式: "${customMeta.title}"。禁止上传。铁律 72 — 必须传真 title (从 dowelved desc 清洗)，或调用 scripts/backfill_placeholder_titles.py 从真源回填`
    });
  }
  // v8.119.40+ dz (铁律 74): aweme_id 唯一性 check (出现在 customMeta.aweme_id)
  // 顺序：扫描 META_DIR (低开销)，如果存在则返回 409 + 旧 file_id
  // 例外：如果 client 传 ?force=true (手动 sync 调用)，则允许 (谨慎使用)
  if (customMeta.aweme_id && !req.query.force) {
    const awemeId = String(customMeta.aweme_id).trim();
    if (awemeId) {
      for (const f of fs.readdirSync(META_DIR).filter(x => x.endsWith('.json'))) {
        try {
          const other = JSON.parse(fs.readFileSync(path.join(META_DIR, f), 'utf8'));
          if (other.customMeta?.aweme_id === awemeId && other.id !== path.basename(req.file.filename, path.extname(req.file.filename))) {
            try {
              fs.unlinkSync(newPath); // 清理重复上传
            } catch (e) {}
            try {
              const auditLog = path.join(AUDIT_DIR, 'duplicate_upload_audit.log');
              fs.appendFileSync(auditLog, JSON.stringify({
                ts: new Date().toISOString(),
                new_file_id: path.basename(req.file.filename, path.extname(req.file.filename)),
                existing_file_id: other.id,
                aweme_id: awemeId,
                ip: req.ip || req.headers['x-forwarded-for'] || 'unknown',
                ua: req.headers['user-agent'] || 'unknown',
              }) + '\n');
            } catch (e) {}
            return res.status(409).json({
              ok: false,
              error: `aweme_id "${awemeId}" 已存在 (file_id=${other.id})。重复上传被拦截。铁律 74—如果需要手动 sync 请传 ?force=true (仅限手动调试)`
            });
          }
        } catch (e) {}
      }
    }
  }
  // v8.119.40+ cd: originalName 优先用 req.body.name (client-specified id/key)
  // 之前用 req.file.originalname (multer 的物理文件名)，导致 douyin-batch
  // 传 name="douyin_015" 但 originalName="douyin_015.mp4" → 幂等失效 → 重复上传
  const clientName = (req.body.name || '').trim();
  const finalOriginalName = clientName || req.file.originalname;
  const file = {
    id: path.basename(req.file.filename, path.extname(req.file.filename)),
    originalName: finalOriginalName,
    filename: req.file.filename,
    size: req.file.size,
    mimeType: req.file.mimetype,
    category: category,
    customMeta,
    uploadedAt: Date.now(),
  };
  file.tags = mergedAutoTags(file); // v8.119.17: 自动打标签
  const savedMeta = saveMeta(file);
  console.log(`[upload] ${file.originalName} → ${category}/${file.filename} (${(file.size/1024).toFixed(1)}KB) tags=[${savedMeta.tags.join(',')}] customMeta=${Object.keys(customMeta).length}字段`);
  res.json({ ok: true, file: { id: savedMeta.id, originalName: savedMeta.originalName, size: savedMeta.size, mimeType: savedMeta.mimeType, category: savedMeta.category, customMeta: savedMeta.customMeta } });
});

// DELETE /files/:id — 删除
app.delete('/files/:id', (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  const category = meta.category || 'default';
  const filePath = path.join(UPLOAD_DIR, category, meta.filename);
  if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
  fs.unlinkSync(metaPath(req.params.id));
  res.json({ ok: true, deleted: req.params.id });
});

// GET /download/:id — 下载
app.get('/download/:id', (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  const category = meta.category || 'default';
  const filePath = path.join(UPLOAD_DIR, category, meta.filename);
  if (!fs.existsSync(filePath)) return res.status(404).json({ ok: false, error: 'File missing from disk' });
  sendFile(res, filePath, meta.originalName, meta.mimeType);
});

// GET /thumb/:id — 视频缩略图 (uploads/.thumbnails/<id>.jpg)
app.get('/thumb/:id', (req, res) => {
  const id = req.params.id;
  // 防 path traversal: 只允许 uuid 格式 + .jpg 后缀
  if (!/^[a-zA-Z0-9\-]+\.jpg$/.test(id)) return res.status(400).json({ ok: false, error: 'Invalid thumb id' });
  const thumbPath = path.join(UPLOAD_DIR, '.thumbnails', id);
  if (!fs.existsSync(thumbPath)) return res.status(404).json({ ok: false, error: 'Thumb missing' });
  res.setHeader('Content-Type', 'image/jpeg');
  res.setHeader('Cache-Control', 'public, max-age=86400');
  // 用 createReadStream 不依赖 sendFile 的 root 检查
  fs.createReadStream(thumbPath).pipe(res);
});

// GET /preview/:id — 预览（图片压缩返回缩略图，PDF 返回 info）
app.get('/preview/:id', async (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  const category = meta.category || 'default';
  const filePath = path.join(UPLOAD_DIR, category, meta.filename);
  if (!fs.existsSync(filePath)) return res.status(404).json({ ok: false, error: 'File missing' });
  if (!isImage(meta.mimeType)) return res.status(400).json({ ok: false, error: 'Not an image' });
  // 图片压缩：缩略图 320px 以内，质量 80
  try {
    const thumbnail = await sharp(filePath)
      .resize(320, 320, { fit: 'inside', withoutEnlargement: true })
      .jpeg({ quality: 80 })
      .toBuffer();
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Cache-Control', 'public, max-age=86400');
    res.end(thumbnail);
  } catch (err) {
    console.error(`[preview] compress error for ${meta.id}:`, err.message);
    // fallback 原图
    sendFile(res, filePath, meta.filename, meta.mimeType);
  }
});

// POST /files/:id/tags — 更新标签
app.post('/files/:id/tags', (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  const { tags } = req.body;
  if (!Array.isArray(tags)) return res.status(400).json({ ok: false, error: 'tags must be array' });
  meta.tags = tags;
  fs.writeFileSync(metaPath(req.params.id), JSON.stringify(meta, null, 2));
  res.json({ ok: true, tags });
});

// POST /process/:id — 图片处理（sharp）
// body: { action: 'thumbnail' | 'resize' | 'rotate' | 'blur' | 'grayscale', options: {...} }
app.post('/process/:id', async (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  if (!isImage(meta.mimeType)) return res.status(400).json({ ok: false, error: 'Not an image' });
  const category = meta.category || 'default';
  const filePath = path.join(UPLOAD_DIR, category, meta.filename);
  const { action, options } = req.body;

  // 输出文件：加后缀
  const ext = path.extname(meta.filename);
  const base = meta.filename.replace(ext, '');
  const outName = `${base}-${action}${ext}`;
  const outPath = path.join(UPLOAD_DIR, category, outName);

  try {
    let pipe = sharp(filePath);
    switch (action) {
      case 'thumbnail': pipe = pipe.resize(200, 200, { fit: 'inside' }); break;
      case 'resize':    pipe = pipe.resize(options?.width, options?.height, { fit: options?.fit || 'inside' }); break;
      case 'rotate':    pipe = pipe.rotate(options?.degrees || 90); break;
      case 'blur':      pipe = pipe.blur(options?.sigma || 3); break;
      case 'grayscale': pipe = pipe.grayscale(); break;
      case 'sharp':     pipe = pipe.extend({ top: 20, bottom: 20, left: 20, right: 20, background: { r: 0, g: 0, b: 0, alpha: 0 } }); break;
      default: return res.status(400).json({ ok: false, error: `Unknown action: ${action}` });
    }
    await pipe.toFile(outPath);
    const stats = fs.statSync(outPath);
    const outMeta = {
      id: `${base}-${action}`.replace(ext, ''),
      originalName: `${path.basename(meta.originalName, ext)}-${action}${ext}`,
      filename: outName,
      size: stats.size,
      mimeType: meta.mimeType,
      uploadedAt: Date.now(),
      tags: [`processed:${action}`],
      description: `Processed from ${meta.originalName} via ${action}`,
      sourceId: meta.id,
      action,
    };
    outMeta.tags = mergedAutoTags(outMeta); // v8.119.17: 自动打标签 + 保留 processed:xxx
    saveMeta(outMeta);
    res.json({ ok: true, action, outputId: outMeta.id, size: stats.size, url: `/download/${outMeta.id}` });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /health
app.get('/health', (req, res) => {
  const files = listMeta();
  res.json({
    ok: true,
    uploadDir: UPLOAD_DIR,
    totalFiles: files.length,
    totalSize: files.reduce((s, f) => s + (f.size || 0), 0),
    timestamp: Date.now(),
  });
});

// ════════════════════════════════════════════════════════════════════════
// 工作区文件浏览
// ════════════════════════════════════════════════════════════════════════

const WORKSPACES = [
  { id: 'main', path: '/home/main/.openclaw/workspace', label: '🏢 统筹部' },
  { id: 'pm',          path: '/home/pm/.openclaw/workspace',          label: '📋 项目管理' },
  { id: 'laohuangniu', path: '/home/laohuangniu/.openclaw/workspace', label: '🐂 老黄牛' },
  { id: 'architecture',path: '/home/architecture/.openclaw/workspace',label: '🏗️  架构部' },
  { id: 'bapo',        path: '/home/bapo/.openclaw/workspace',        label: '🗂️  BAPO' },
];

// 递归获取文件列表（限制深度和数量）
function walkDir(dir, depth = 0, maxDepth = 3, maxFiles = 200) {
  const results = [];
  if (depth > maxDepth) return results;
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    let count = 0;
    for (const entry of entries) {
      if (count >= maxFiles) break;
      const fullPath = path.join(dir, entry.name);
      // 跳过隐藏目录和特殊目录
      if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === 'wal') continue;
        try {
          // 跳过 broken symlink
          if (entry.isSymbolicLink()) { try { fs.lstatSync(fullPath); } catch { continue; } }
          const stat = fs.statSync(fullPath);
        if (entry.isDirectory()) {
          results.push({ name: entry.name, path: fullPath, type: 'dir', size: 0, modified: stat.mtimeMs });
          if (depth < maxDepth) {
            results.push(...walkDir(fullPath, depth + 1, maxDepth, maxFiles - results.length).map(r => ({ ...r, name: entry.name + '/' + r.name })));
          }
        } else if (entry.isFile()) {
          // 只显示有意义的后缀名文件
          const ext = path.extname(entry.name);
          if (['.md','.txt','.json','.js','.ts','.py','.sh','.yaml','.yml','.log','.sql','.html','.css','.vue','.jsx','.tsx'].includes(ext)) {
            results.push({ name: entry.name, path: fullPath, type: 'file', size: stat.size, modified: stat.mtimeMs });
            count++;
          }
        }
      } catch {}
    }
  } catch {}
  return results;
}

// GET /workspaces — 所有工作区概览
app.get('/workspaces', (req, res) => {
  const workspaces = WORKSPACES.map(ws => {
    let fileCount = 0;
    let totalSize = 0;
    try {
      const files = walkDir(ws.path, 0, 3, 200);
      files.forEach(f => { if (f.type === 'file') { fileCount++; totalSize += f.size; } });
    } catch {}
    return { id: ws.id, label: ws.label, root: ws.path, fileCount, totalSize };
  });
  res.json({ ok: true, workspaces });
});

// GET /workspaces/:id/files — 浏览指定工作区文件
app.get('/workspaces/:id/files', (req, res) => {
  const ws = WORKSPACES.find(w => w.id === req.params.id);
  if (!ws) return res.status(404).json({ ok: false, error: 'Workspace not found' });
  const subPath = req.query.path || '';
  const fullPath = subPath ? path.join(ws.path, subPath) : ws.path;
  if (!fullPath.startsWith(ws.path)) return res.status(403).json({ ok: false, error: 'Path traversal blocked' });
  try {
    if (!fs.existsSync(fullPath)) return res.status(404).json({ ok: false, error: 'Path not found' });
    const stat = fs.statSync(fullPath);
    if (!stat.isDirectory()) return res.status(400).json({ ok: false, error: 'Not a directory' });
    const entries = fs.readdirSync(fullPath, { withFileTypes: true });
    const items = entries
      .filter(e => !e.name.startsWith('.') && e.name !== 'node_modules' && e.name !== 'wal')
      .map(e => {
        const p = path.join(fullPath, e.name);
        try {
          const s = fs.statSync(p);
          // 跳过 broken symlink
          return { name: e.name, type: e.isDirectory() ? 'dir' : 'file', size: e.isFile() ? s.size : 0, modified: s.mtimeMs };
        } catch { return null; }
      })
      .filter(Boolean)
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
    res.json({ ok: true, workspace: ws.id, path: subPath, items, parent: subPath ? path.dirname(subPath) : null });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /workspaces/:id/read — 读取文件内容
app.get('/workspaces/:id/read', (req, res) => {
  const ws = WORKSPACES.find(w => w.id === req.params.id);
  if (!ws) return res.status(404).json({ ok: false, error: 'Workspace not found' });
  const filePath = req.query.file || '';
  if (!filePath) return res.status(400).json({ ok: false, error: 'file param required' });
  const fullPath = path.join(ws.path, filePath);
  if (!fullPath.startsWith(ws.path)) return res.status(403).json({ ok: false, error: 'Path traversal blocked' });
  try {
    const stat = fs.statSync(fullPath);
    if (!stat.isFile()) return res.status(400).json({ ok: false, error: 'Not a file' });
    if (stat.size > 5 * 1024 * 1024) return res.status(400).json({ ok: false, error: 'File too large (>5MB)' });
    const content = fs.readFileSync(fullPath, 'utf8');
    res.json({ ok: true, workspace: ws.id, file: filePath, size: stat.size, content: content.slice(0, 50000) });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// ════════════════════════════════════════════════════════════════════════
// Phase 5: 资产路由（Asset Routes）
// 使用 asset-manager / assets-relations / assets-rules 模块
// ════════════════════════════════════════════════════════════════════════

// GET /assets/types — 列出所有资产类型定义
app.get('/assets/types', (req, res) => {
  try {
    const types = assetManager.getTypes();
    res.json({ ok: true, types });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /assets — 列出所有资产（可选 type/role/tags/search 过滤）
app.get('/assets', (req, res) => {
  try {
    const filters = {
      type: req.query.type,
      role: req.query.role,
      status: req.query.status,
      tags: req.query.tags ? req.query.tags.split(',') : undefined,
      search: req.query.search,
    };
    const assets = assetManager.listAssets(filters);
    res.json({ ok: true, assets, count: assets.length });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /assets — 创建新资产
app.post('/assets', (req, res) => {
  try {
    const result = assetManager.createAsset(req.body);
    if (!result.ok) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /assets/:id — 获取单个资产
app.get('/assets/:id', (req, res) => {
  try {
    const asset = assetManager.getAssetById(req.params.id);
    if (!asset) return res.status(404).json({ ok: false, error: 'Asset not found' });
    res.json({ ok: true, asset });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// PATCH /assets/:id — 更新资产
app.patch('/assets/:id', (req, res) => {
  try {
    const result = assetManager.updateAsset(req.params.id, req.body);
    if (!result.ok) return res.status(404).json(result);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// DELETE /assets/:id — 删除资产
app.delete('/assets/:id', (req, res) => {
  try {
    const result = assetManager.deleteAsset(req.params.id);
    if (!result.ok) return res.status(404).json(result);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /assets/characters/:id/outfit-for — 获取角色匹配服装（按场景关键词）
app.get('/assets/characters/:id/outfit-for', (req, res) => {
  try {
    const scene = req.query.scene || '';
    const outfit = assetsRules.getCharacterOutfit(req.params.id, scene);
    if (!outfit) return res.json({ ok: true, outfit: null, message: 'No matching outfit found' });
    res.json({ ok: true, outfit });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /assets/characters/:id/voice — 绑定音色到角色
app.post('/assets/characters/:id/voice', (req, res) => {
  try {
    const { voiceId } = req.body;
    if (!voiceId) return res.status(400).json({ ok: false, error: 'voiceId required' });
    const result = assetsRelations.linkAssets(req.params.id, voiceId, 'linkedVoices');
    if (!result.ok) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /assets/characters/:id/assemble — 组装角色参考包（角色+服装+音色）
app.post('/assets/characters/:id/assemble', (req, res) => {
  try {
    const scene = req.query.scene || req.body.scene || '';
    const pkg = assetsRules.assembleCharacterPackage(req.params.id, scene);
    if (!pkg) return res.status(404).json({ ok: false, error: 'Character not found or assembly failed' });
    res.json({ ok: true, package: pkg });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /assets/voices/:id/refresh — 刷新克隆音色有效期
app.post('/assets/voices/:id/refresh', (req, res) => {
  try {
    const result = assetsRules.refreshVoiceExpiry(req.params.id);
    if (!result) return res.status(400).json({ ok: false, error: 'Voice not found or cannot be refreshed' });
    if (!result.ok) return res.status(400).json(result);
    res.json({ ok: true, voice: result });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /assets/export — 导出所有资产（或指定 type）
app.get('/assets/export', (req, res) => {
  try {
    const result = assetManager.exportAssets(req.query.type);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /assets/import — 导入资产（mode: skip/update/overwrite）
app.post('/assets/import', (req, res) => {
  try {
    const { data, mode = 'skip' } = req.body;
    if (!data) return res.status(400).json({ ok: false, error: 'data required' });
    const result = assetManager.importAssets(data, mode);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /assets/:id/link — 建立资产关联
app.post('/assets/:id/link', (req, res) => {
  try {
    const { targetId, relationType } = req.body;
    if (!targetId || !relationType) return res.status(400).json({ ok: false, error: 'targetId and relationType required' });
    const result = assetsRelations.linkAssets(req.params.id, targetId, relationType);
    if (!result.ok) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// POST /assets/:id/unlink/:targetId — 解除资产关联
app.post('/assets/:id/unlink/:targetId', (req, res) => {
  try {
    const { relationType } = req.body;
    if (!relationType) return res.status(400).json({ ok: false, error: 'relationType required' });
    const result = assetsRelations.unlinkAssets(req.params.id, req.params.targetId, relationType);
    if (!result.ok) return res.status(400).json(result);
    res.json(result);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /assets/voices/status — 列出所有音色及其状态
app.get('/assets/voices/status', (req, res) => {
  try {
    const voices = assetManager.listAssets({ type: 'voice' });
    const status = voices.map(v => ({
      id: v.id,
      name: v.name,
      source: v.source,
      active: assetsRules.isVoiceActive(v),
      expiresAt: v.expiresAt,
      daysLeft: assetsRules.getDaysLeft(v),
    }));
    res.json({ ok: true, voices: status, count: status.length });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// GET /health

// POST /admin/auto-tag-all — 批量回填所有现有文件的自动标签 (v8.119.17)
app.post('/admin/auto-tag-all', (req, res) => {
  const files = listMeta();
  let updated = 0;
  let skipped = 0;
  const samples = [];
  for (const file of files) {
    const oldTags = (file.tags || []).slice();
    const newTags = mergedAutoTags(file);
    // 仅在补齐时写入
    const added = newTags.filter(t => !oldTags.includes(t));
    if (added.length > 0) {
      file.tags = newTags;
      saveMeta(file);
      updated++;
      if (samples.length < 5) samples.push({ id: file.id, originalName: file.originalName, added });
    } else {
      skipped++;
    }
  }
  console.log(`[auto-tag] 回填完成: ${updated} 个文件补齐, ${skipped} 个无变化 (总计 ${files.length})`);
  res.json({ ok: true, total: files.length, updated, skipped, samples });
});

// POST /admin/auto-tag/:id — 单个文件回填 (v8.119.17)
app.post('/admin/auto-tag/:id', (req, res) => {
  const meta = loadMeta(req.params.id);
  if (!meta) return res.status(404).json({ ok: false, error: 'Not found' });
  const oldTags = (meta.tags || []).slice();
  const newTags = mergedAutoTags(meta);
  const added = newTags.filter(t => !oldTags.includes(t));
  meta.tags = newTags;
  saveMeta(meta);
  console.log(`[auto-tag] ${meta.id} (${meta.originalName}): +[${added.join(',')}]`);
  res.json({ ok: true, file: meta, added });
});

app.listen(PORT, () => {
  console.log(`[file-service] 🚀 Upload service running on http://0.0.0.0:${PORT}`);
  console.log(`[file-service]    Upload dir: ${UPLOAD_DIR}`);
  console.log(`[file-service]    Max file size: 500MB`);
});
