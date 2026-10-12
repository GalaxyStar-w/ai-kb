#!/usr/bin/env node
// vault_encrypt.mjs —— 把看板的明文静态站整体加密成「只有口令能打开」的密文站。
//
// 设计目标：部署到公开托管（如 Cloudflare Pages 的 *.pages.dev）后，即使网址泄露，
// 服务器上也只有密文，没有口令谁都读不了。不依赖域名、不依赖 Worker、不依赖服务端配置。
//
// 用法（一般由 build_dashboard.py 调用，口令只通过环境变量 KB_DASH_PASS 传入，绝不走命令行参数）：
//   KB_DASH_PASS=... node vault_encrypt.mjs build  --src <明文目录> --out <输出目录> --shell <shell.html> --salt-file <盐文件>
//   KB_DASH_PASS=... node vault_encrypt.mjs verify --out <输出目录>      # 用口令解开全部文件，核对完整性
//
// 密码学（全部是 Node/浏览器内置，无第三方依赖）：
//   密钥派生  PBKDF2-HMAC-SHA256，600000 次迭代，随机盐（公开存放在 vault/params.json）
//   加密      AES-256-GCM（认证加密：口令错误或密文被篡改都会解密失败）
//   文件名    HMAC(密钥, 路径) 的前 32 位十六进制 —— 服务器上看不出项目名/文件名
//   IV        HMAC(密钥, 编号+明文哈希) 的前 12 字节（确定性：内容不变则密文逐字节不变，增量部署只传改动文件；
//             同一密钥下不同明文必得不同 IV，不会发生 IV 复用）
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const ITER = 600000;
const die = (m) => { console.error('✘ ' + m); process.exit(1); };
const hmac = (key, msg) => crypto.createHmac('sha256', key).update(msg).digest();
const sha = (buf) => crypto.createHash('sha256').update(buf).digest();

function parseArgs(argv) {
  const a = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) a[argv[i].slice(2)] = argv[++i];
    else a._.push(argv[i]);
  }
  return a;
}

function passphrase() {
  const p = process.env.KB_DASH_PASS || '';
  if (p.length < 12) die('口令太短（至少 12 个字符）。请用 build_dashboard.py --gen-pass 生成强口令。');
  return p;
}

function* walk(dir, base = dir) {
  for (const name of fs.readdirSync(dir).sort()) {
    const full = path.join(dir, name);
    const st = fs.statSync(full);
    if (st.isDirectory()) yield* walk(full, base);
    else yield [path.relative(base, full).split(path.sep).join('/'), full];
  }
}

function seal(master, ivKey, id, plain) {
  const iv = hmac(ivKey, Buffer.concat([Buffer.from(id), sha(plain)])).subarray(0, 12);
  const c = crypto.createCipheriv('aes-256-gcm', master, iv);
  const ct = Buffer.concat([c.update(plain), c.final()]);
  return Buffer.concat([iv, ct, c.getAuthTag()]);   // 浏览器 WebCrypto 约定：密文末尾带 16 字节 tag
}

function open(master, blob) {
  const iv = blob.subarray(0, 12), tag = blob.subarray(blob.length - 16), ct = blob.subarray(12, blob.length - 16);
  const d = crypto.createDecipheriv('aes-256-gcm', master, iv);
  d.setAuthTag(tag);
  return Buffer.concat([d.update(ct), d.final()]);
}

function loadSalt(saltFile) {
  if (fs.existsSync(saltFile)) return Buffer.from(fs.readFileSync(saltFile, 'utf8').trim(), 'base64');
  const salt = crypto.randomBytes(16);
  fs.mkdirSync(path.dirname(saltFile), { recursive: true });
  fs.writeFileSync(saltFile, salt.toString('base64') + '\n', { mode: 0o600 });
  return salt;   // 盐持久化：重建时盐不变，密文才能保持确定性（盐本身不是秘密）
}

function build(a) {
  for (const k of ['src', 'out', 'shell', 'salt-file']) if (!a[k]) die('缺少参数 --' + k);
  const pass = passphrase();
  const salt = loadSalt(a['salt-file']);
  const master = crypto.pbkdf2Sync(pass, salt, ITER, 32, 'sha256');
  const idKey = hmac(master, 'kb-id'), ivKey = hmac(master, 'kb-iv');
  const vault = path.join(a.out, 'vault');
  fs.mkdirSync(vault, { recursive: true });

  const files = {};
  let n = 0, bytes = 0;
  for (const [rel, full] of walk(a.src)) {
    const plain = fs.readFileSync(full);
    const id = hmac(idKey, rel).toString('hex').slice(0, 32);
    const blob = seal(master, ivKey, id, plain);
    fs.writeFileSync(path.join(vault, id + '.enc'), blob);
    files[rel] = id; n++; bytes += blob.length;
  }
  // 清单本身也加密：服务器上看不到有哪些项目/文件。清单能解开=口令正确（GCM 校验）。
  const manifest = Buffer.from(JSON.stringify({ v: 1, built: new Date().toISOString(), files }));
  fs.writeFileSync(path.join(vault, 'manifest.enc'), seal(master, ivKey, 'manifest', manifest));
  fs.writeFileSync(path.join(vault, 'params.json'),
    JSON.stringify({ v: 1, kdf: 'PBKDF2-SHA256', iter: ITER, salt: salt.toString('base64') }) + '\n');

  // 外壳：同一个文件放在 index/project/view 三个入口（不依赖托管方的 SPA 回退行为）
  const shell = fs.readFileSync(a.shell);
  for (const name of ['index.html', 'project.html', 'view.html']) fs.writeFileSync(path.join(a.out, name), shell);
  fs.writeFileSync(path.join(a.out, 'robots.txt'), 'User-agent: *\nDisallow: /\n');
  fs.writeFileSync(path.join(a.out, '_headers'),
    '/*\n  X-Robots-Tag: noindex, nofollow, noarchive\n  Referrer-Policy: no-referrer\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY\n  Cache-Control: no-store\n' +
    '/vault/*\n  Cache-Control: public, max-age=0, must-revalidate\n');
  console.log(`加密完成：${n} 个文件，密文共 ${(bytes / 1024).toFixed(0)} KB → ${a.out}`);
}

function verify(a) {
  if (!a.out) die('缺少参数 --out');
  const pass = passphrase();
  const p = JSON.parse(fs.readFileSync(path.join(a.out, 'vault', 'params.json'), 'utf8'));
  const master = crypto.pbkdf2Sync(pass, Buffer.from(p.salt, 'base64'), p.iter, 32, 'sha256');
  let manifest;
  try { manifest = JSON.parse(open(master, fs.readFileSync(path.join(a.out, 'vault', 'manifest.enc'))).toString()); }
  catch { die('口令不对，或清单已损坏'); }
  let ok = 0;
  for (const [rel, id] of Object.entries(manifest.files)) {
    try { open(master, fs.readFileSync(path.join(a.out, 'vault', id + '.enc'))); ok++; }
    catch { die('文件解密失败：' + id); }
  }
  console.log(`校验通过：清单与 ${ok} 个文件全部可用口令解开`);
}

const args = parseArgs(process.argv.slice(2));
const cmd = args._[0];
if (cmd === 'build') build(args);
else if (cmd === 'verify') verify(args);
else die('用法：vault_encrypt.mjs build|verify ...');
