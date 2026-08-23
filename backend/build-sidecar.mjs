import { execSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const binDir = join(root, '..', 'desktop', 'binaries');

// 发货守卫：pkg 会把仓库根 .env（含 LLM 密钥）快照进 sidecar 二进制，
// 本地构建的 DMG 会携带本地 .env。发行请走 CI（全新 checkout），不要分发本地构建。
const repoEnv = join(root, '..', '.env');
if (existsSync(repoEnv)) {
  console.warn(
    [
      '======================================================================',
      'WARNING: 检测到仓库根 .env，pkg 将把其中的密钥（如 LLM_API_KEY）快照进',
      'sidecar 二进制，本地构建的 DMG 会携带本地 .env。',
      `  检测到: ${repoEnv}`,
      '发行请走 CI（全新 checkout），不要分发本地构建的产物。',
      '======================================================================',
    ].join('\n'),
  );
}

// 按 host 平台/架构选择 pkg target（原生模块无法交叉编译，只构建当前平台）
const targetMap = {
  darwin: { arm64: 'node22-macos-arm64', x64: 'node22-macos-x64' },
  win32: { x64: 'node22-win-x64' },
};
const target = targetMap[process.platform]?.[process.arch];
if (!target) throw new Error(`Unsupported host: ${process.platform}/${process.arch}`);

// 1) nest build -> dist/
execSync('npm run build', { cwd: root, stdio: 'inherit' });
// 2) pkg dist/main.js（backend/package.json 无 main/bin 字段，须显式指定入口）-> build/backend
execSync(`npx @yao-pkg/pkg dist/main.js --target ${target} --output build/backend`, {
  cwd: root,
  stdio: 'inherit',
});

// 3) 重命名为 Tauri 要求的 <name>-<target-triple>
const triple = execSync('rustc --print host-tuple').toString().trim();
const ext = process.platform === 'win32' ? '.exe' : '';
mkdirSync(binDir, { recursive: true });
cpSync(join(root, 'build', `backend${ext}`), join(binDir, `backend-${triple}${ext}`));
console.log(`sidecar -> desktop/binaries/backend-${triple}${ext}`);
