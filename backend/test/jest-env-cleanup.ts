/**
 * Jest 全局环境净化（setupFiles 阶段执行，先于所有用例导入）。
 *
 * 后端按约定支持用环境变量覆盖运行时配置（LLM_MODEL 等），但这会让单测
 * 结果依赖宿主 shell 的导出值：本机若 export LLM_MODEL=xxx，
 * analysis.service.spec 的模型断言就会失败。这里在测试进程内剔除这些
 * 环境变量，保证用例只依赖代码内注入的配置。
 *
 * 注意：需要自定义环境的用例可在模块内自行设置 process.env——
 * setupFiles 先于用例代码运行，后设置者生效，不受此文件影响。
 */
const AMBIENT_ENV_KEYS = ['LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'DB_PATH'] as const;

for (const key of AMBIENT_ENV_KEYS) {
  delete process.env[key];
}
