# Third-party asset register

记录日期：2026-08-04。所有外部资产进入仓库、构建或正式策略前必须固定 upstream、commit、许可证和导入日期。

| 资产 | 当前用途 | 许可证/状态 | 处理规则 |
|---|---|---|---|
| `WordYeah/Sensitive-lexicon` | 文本 0.2 候选词库 | MIT；当前 fork 词库约 87,042 行，存在重复和单字词 | 只导入 candidate，去重、分类、来源标注、人工批准后生成 rule_set_version |
| `WordYeah/sensitive-word` | 文本 0.2 算法参考 | Apache-2.0 | 头像 MVP 不引入 Java runtime |
| `WordYeah/SensitiveWordsDetection` | 无言 UI 参考 | 未发现 LICENSE | 不复制代码或直接部署，先取得授权 |
| `WordYeah/sensitive-word-admin` | 无言词库后台参考 | MIT | 保留版权声明；不把旧 Java/Spring 栈带入头像 MVP |
| `qirtaiba/modtools` | 会语图片审核流程参考 | MIT | 不引入 HiveAI、PhotoDNA、NCMEC 或其数据库合同 |
| `SashiDo/content-moderation-application` | 图片网格交互参考 | 仓库 LICENSE 为 Apache-2.0；package metadata 仍写 MIT | 只参考交互，旧 Node/Parse 运行时不接入 |
| `muxinc/content-moderation-dashboard` | 会语视频时间轴/关键帧参考 | Apache-2.0 | 不引入 Mux、Convex、Vercel 或云端凭据 |
| `KOKOSde/localmod` | 本地模型/API 对照 | MIT | 现有 Falconsai 适配器已满足头像基线，不整套替换 |
| `tabler/tabler-icons` 3.46.0 | 审核台导航、指标、筛选、详情和操作图标 | MIT；固定 SVG 子集位于 `src/wy_api/icons.py`，许可证见 `third_party/tabler-icons/LICENSE` | 只从统一注册表输出；不加载 CDN，不混入其他图标族 |

WordYeah 组织内的 fork 不自动授予无许可证上游项目的再分发权。复制 Apache/MIT 代码时必须保留许可证和版权声明；模型权重与数据集另行记录，不能只看代码仓库许可证。
