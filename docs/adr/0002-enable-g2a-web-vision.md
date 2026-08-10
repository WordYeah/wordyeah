# ADR-0002：启用 G2A Web 作为高级视觉一审（运行时）

- 状态：**accepted**（决策已定；**运行时配置由专员执行，本 ADR 不代替 env 写入**）
- 记录日期：2026-08-10
- 记录人：毕方会话整理 / 产品确认
- 范围：WordYeah 头像高级视觉一审外呼；**不**授权 Cravatar `enforce` 或生产写回

## 背景

- 高级视觉链路与 `G2AVisionProvider`（`src/wy_media/g2a.py`）已实现；默认 `WORDYEAH_G2A_ENABLED=false`。
- 2026-08-10 本机 g2a Web 识图冒烟：`grok-chat-fast` / `g2a-web-fast` 对合法 PNG 返回 200，可描述内容。
- 同日 API 只读：`/health/ready` 仍报 `advanced_vision.enabled=false`，`external_model_calls=false`——**代码能用 ≠ 运行时已开**。
- Build 池 `grok-4.5` 可用账号仍极薄；审核不得改绑 Build。junsen / new-api 旁路用于对话产能，**不**作为 WordYeah 审核默认上游。

## 决策

| ID | 状态 | 决定 |
|---|---|---|
| D1 | accepted | **将本机 / 目标主机开发与 shadow 链路的 `WORDYEAH_G2A_ENABLED` 设为 `true`**，使高级视觉一审真实调用 G2A Web 号池。 |
| D2 | accepted | Endpoint 使用池化网关 OpenAI 兼容 chat 完成地址，推荐 `http://127.0.0.1:18000/v1/chat/completions`（本机 g2a 转发）。私网 IP 字面量 HTTP 须同时 `WORDYEAH_G2A_ALLOW_PRIVATE_HTTP=true`。 |
| D3 | accepted | 一审模型推荐 **`grok-chat-fast`**（与 `docs/MODELS.md`、既有 canary 一致）。可选同池别名 `g2a-web-fast`。**禁止**默认使用 `grok-4.5` / Build。 |
| D4 | accepted | 必须同时配置 `WORDYEAH_G2A_API_KEY`（仓库外 0600）、`WORDYEAH_G2A_MODEL`；建议保留 Ollama 兜底与独立二审（`WORDYEAH_OLLAMA_*` / `WORDYEAH_OLLAMA_SECONDARY_*`）。 |
| D5 | accepted | **`enforce` 仍为 false**；不写 WordPress / 头像状态 / Cavalcade / 生产库；不恢复腾讯云等第三方内容审核 API。 |
| D6 | accepted | 本决策只授权 **打开 G2A 外呼开关与核对健康**；质量放量、10k canary、生产处置仍受 `HANDOFF` P3–P6 与验收门槛约束。 |

## 专员执行清单（运行时，不进 Git secret）

在**仓库外** 0600 env（或目标主机 secret store）写入/确认，然后重启 API 与 vision worker：

```bash
WORDYEAH_G2A_ENABLED=true
WORDYEAH_G2A_ENDPOINT=http://127.0.0.1:18000/v1/chat/completions
WORDYEAH_G2A_MODEL=grok-chat-fast
WORDYEAH_G2A_API_KEY=  # 仅仓库外注入；与 g2a client key 同源策略由运维定
# 若 endpoint 为 10.211.x.x 等私网 IP 字面量 HTTP：
# WORDYEAH_G2A_ALLOW_PRIVATE_HTTP=true
# 建议：
WORDYEAH_OLLAMA_ENABLED=true
WORDYEAH_OLLAMA_SECONDARY_ENABLED=true
```

验收（secret-free）：

```bash
curl -fsS http://127.0.0.1:18767/health/live
# 期望：external_model_calls 反映配置策略；advanced_vision 侧 enabled 为 true（以 ready 为准）
curl -fsS http://127.0.0.1:18767/health/ready
# 期望：advanced_vision.enabled == true

# 可选单图 canary（需已 export 上述 env）
# .venv/bin/python scripts/run_vision_canary.py /path/to.png --output /path/out.json
```

失败路径：G2A 超时/429/无效 JSON → 不得变 `allow`；应走 Ollama 兜底或 `error`/`held`（既有合同）。

## 非目标

- 不把 junsen / new-api `junsen-grok` 配成 WordYeah 默认一审。
- 不因本决策开启 `enforce` 或黑名单自动执行。
- 不在文档、工单、截图中粘贴 API key。

## 回退

```bash
WORDYEAH_G2A_ENABLED=false
# 重启 API 与 vision worker
```

回退后一审不再外呼 G2A；若 Ollama 仍启用可本机兜底，否则高级视觉保持关闭/留置语义（以当时 env 为准）。

## 相关

- 实现：`src/wy_media/g2a.py`、`failover.py`、`vision_worker.py`
- 合同：`docs/G2A_INTEGRATION_DRAFT.md`、`docs/MODELS.md`
- 样例：`deploy/systemd/wordyeah.env.example`（样例默认仍可为 false；**运行时**按本 ADR 打开）
- 交接执行入口：`docs/HANDOFF.md` §G2A 运行时启用
