# 通用云凭证拆页 + 整站 Material 3 视觉重设计

**日期**：2026-08-31  
**状态**：设计已口头批准（§1–§3），待实现  
**范围**：`qiniu-cert-autorenew/web` 服务端渲染 UI（Jinja + 纯 CSS）

## 1. 背景与目标

当前「通用云凭证」集中在单页 `settings/credentials.html`：按厂商列表、行内编辑、底部添加混排，可读性与运维心智较差。整站仍为早期自定义浅色皮肤。

目标：

1. 将凭证的**列表 / 添加 / 编辑**拆成独立页面与路由。
2. 以**纯 CSS Material 3** 重做整站壳与控件外观（不引入 Material Web / npm）。
3. **不改变**凭证加密、兼容矩阵、CSRF、业务服务层语义。

## 2. 决策摘要

| 项 | 选择 |
|----|------|
| M3 实现 | A — 纯 CSS token + 手写组件外观 |
| 列表组织 | A — 按云厂商分组（阿里云 / 腾讯云 / 七牛） |
| 改造范围 | C / 方案 1 — 一次整站换肤 + 凭证拆页 |
| 组件库 | 不引入 |

## 3. 信息架构与路由

### 3.1 凭证

| 页面 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 列表 | GET | `/settings/credentials` | 按厂商分组；名称、厂商、编辑 / 删除 |
| 添加 | GET | `/settings/credentials/new` | 独立表单 |
| 添加提交 | POST | `/settings/credentials` | 成功 → 列表 `?ok=1`；失败 → 添加页带 `err`（或 query 回 new） |
| 编辑 | GET | `/settings/credentials/{id}/edit` | 独立表单；密钥留空 = 不改密文 |
| 更新 | POST | `/settings/credentials/{id}/update` | 成功 → 列表 |
| 删除 | POST | `/settings/credentials/{id}/delete` | 列表行内确认；被引用时 Banner 报错 |

### 3.2 整站壳

- Top App Bar：品牌 + 证书 / 凭证 / 配置档 / 退出（未登录：登录 / 注册）。
- 主内容区约 `max-width: 960px`，背景 `surface` / `surface-container`。
- 登录、注册、证书（列表 / 添加 / 编辑 / 验证）、配置档：路由与字段逻辑不变，仅换视觉 class。

### 3.3 交互约定

- 列表主 CTA：右上「添加凭证」→ `/settings/credentials/new`。
- 编辑入口：卡片「编辑」→ `/settings/credentials/{id}/edit`。
- 编辑页**不提供删除**（删除仅列表）。
- 成功 / 错误：页顶 M3 Banner。
- 添加 / 编辑页提供「返回列表」与「取消」（Outlined）。

### 3.4 错误回跳

- 创建失败：优先 `RedirectResponse("/settings/credentials/new?err=...")`，避免回到列表丢表单上下文。
- 更新失败：回 `/settings/credentials/{id}/edit?err=...`。
- CSRF / 删除失败：回列表带 `err`。

## 4. 视觉规范

### 4.1 气质

运维控制台 × Material 3：浅色 surface、克制主色、大圆角、清晰 elevation。禁止紫渐变、炫光、过度装饰。

### 4.2 色板（CSS 变量，示意）

- `--md-sys-color-primary`: `#0F6B58`
- `--md-sys-color-on-primary`, `--md-sys-color-primary-container`, `--md-sys-color-on-primary-container`
- `--md-sys-color-surface`: `#F7F9F8`
- `--md-sys-color-surface-container` / `-high`（卡片）
- `--md-sys-color-outline` / `outline-variant`
- `--md-sys-color-error` / `error-container`
- Tertiary 仅可选用于厂商小标识，保持克制

具体 hex 可在实现时微调，但须保持「深青绿主色 + 浅表面」方向。

### 4.3 字体

- 标题：`Noto Sans SC` / `Segoe UI Variable` / system-ui（不依赖 Google Sans 专有字体文件）
- 正文：同上
- 字阶：页标题 Display-small / Headline-small；分组 Title-large；正文 Body-large/medium；按钮 Label-large

### 4.4 组件映射

| 元素 | M3 形态 |
|------|---------|
| 顶栏 | Top App Bar（sticky，surface + 底边） |
| 列表项 | Outlined 或 Elevated card |
| 主按钮 | Filled（添加、保存） |
| 次按钮 | Outlined（取消、返回） |
| 危险 | Text / tonal error（删除） |
| 输入 / 下拉 | Outlined field 外观 |
| 提示 | Banner + supporting text |

### 4.5 动效

- 进页轻量 stagger fade（约 0.2s）
- 按钮 `:active` 轻微缩放；卡片 hover elevation
- 遵守 `prefers-reduced-motion: reduce`（关闭非必要动画）

## 5. 页面结构

### 5.1 列表

- Banner（ok/err）
- 标题「通用云凭证」+ 「添加凭证」Filled 按钮
- supporting：密钥加密入库，列表不回显 Secret
- 三组：阿里云 / 腾讯云 / 七牛；空组「暂无凭证」
- 卡片：名称、厂商标识、编辑、删除
- 底注：下一步 → 配置档

### 5.2 添加

- 返回列表
- 标题「添加凭证」
- 字段：名称、云厂商、AK、SK、CAS 地域（选阿里云时显示，可用简单 JS 切换）
- 取消（Outlined）+ 保存（Filled）

### 5.3 编辑

- 返回列表
- 标题「编辑凭证」+ 厂商只读 chip
- 字段：名称、AK/SK（placeholder 表明留空不改）、CAS（阿里云）
- 取消 + 保存更改；无删除按钮

### 5.4 其它页

同一 App bar 与 token；表单/表格改用 M3 class，业务字段与流程不变。

## 6. 实现约束

- 技术：现有 FastAPI + Jinja；样式以 `base.html` 内或抽 `static/m3.css` 均可，优先可维护的单一全局样式。
- 模板：将 `settings/credentials.html` 拆为 `settings/credentials_list.html`、`settings/credentials_new.html`、`settings/credentials_edit.html`（或同级 `settings/credentials/` 子目录，实现时二选一，路由不变）。
- 测试：更新 `test_http_e2e.py` 等对 `/settings/credentials` 的假设；保持「注册 → 凭证 → 配置档 → 域名」主路径通过。
- 非目标：Material Web、构建工具链、移动端原生 App、暗色主题（本版不做，除非后续单开）。

## 7. 验收标准

1. 凭证添加 / 编辑 / 列表三路由可走通；旧单页混排消失。
2. 密钥留空更新不改密文；删除被引用时 Banner 报错。
3. HTTP e2e 与相关单测通过（路径按新约定更新）。
4. 整站统一 M3 token；`prefers-reduced-motion` 下无强制动画。
5. 无外部 UI 组件库依赖。

## 8. 风险与备注

- `web/` 目录若尚未纳入 git 主仓发布策略，实现时注意与现有 CLI 开源范围的边界（本设计仅约束 Web UI）。
- 迁移 `002` 对旧 Web 证书仍为破坏性清空——与本 UI 改版无关，勿在本任务中 silently 改迁移语义。
