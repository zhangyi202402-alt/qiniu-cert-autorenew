# 通用云凭证拆页 + 整站 Material Web（M3）重写

**日期**：2026-08-31  
**状态**：设计修订（由「纯 CSS 仿 M3」改为引入 **Material Web**）  
**范围**：`qiniu-cert-autorenew/web` 全部 Jinja 页面

## 1. 背景与目标

当前「通用云凭证」单页混排（列表 + 行内编辑 + 添加）；整站为自定义浅色皮肤。

目标：

1. 凭证 **列表 / 添加 / 编辑** 拆成独立路由与页面。
2. 引入官方 **Material Web**（`@material/web`）重写**所有**页面控件与壳层。
3. **不改变**凭证加密、兼容矩阵、CSRF、业务服务层语义。

## 2. 决策摘要

| 项 | 选择 |
|----|------|
| UI 库 | **A — Material Web**（Web Components，CDN + import map，无 bundler） |
| 列表组织 | 按云厂商分组（阿里云 / 腾讯云 / 七牛） |
| 改造范围 | 整站一次重写（登录/注册/证书/凭证/配置档） |
| 废弃决策 | ~~纯 CSS 仿 M3、不引入组件库~~ |

## 3. 技术接入

### 3.1 加载方式（base 模板）

- Google Fonts：`Roboto`（Material Web 文档推荐）+ `Noto Sans SC`（中文正文）。
- Import map 指向 CDN，例如 `https://esm.run/@material/web/`。
- `type="module"` 引入所需组件（优先按页按需 import；若体积可接受可用 `@material/web/all.js` 原型期）。
- 可选：`md-typescale-styles` 注入 `document.adoptedStyleSheets`。
- 主题：用 CSS 覆盖 `--md-sys-color-*`（主色深青绿 `#0F6B58` 方向），浅色 surface。

### 3.2 表单与后端兼容

- Material Web 控件支持原生表单关联（`name`、`required` 等），**继续**用 FastAPI `Form(...)` + CSRF hidden field。
- 提交仍用标准 `<form method="post">`；按钮用 `<md-filled-button type="submit">` 等。
- CSRF：保留 `<input type="hidden" name="csrf_token">`（无对应 md 控件时用原生 hidden）。

### 3.3 组件映射（全站）

| UI 需求 | Material Web |
|---------|----------------|
| 主操作 | `md-filled-button` |
| 次操作 / 取消 | `md-outlined-button` / `md-text-button` |
| 危险删除 | `md-text-button`（error 色 token）或确认用 `md-dialog` |
| 文本输入 | `md-outlined-text-field`（密码 `type="password"`） |
| 下拉 | `md-outlined-select` + `md-select-option` |
| 列表行 | `md-list` / `md-list-item` 或 outlined 卡片容器 + 内部 list |
| 厂商标识 | `md-assist-chip` / `md-filter-chip`（只读展示） |
| 提示 | 页顶自定义 Banner，或 `md-snackbar`（若引入） |
| 图标 | `md-icon` + Material Symbols 字体 |
| Top App Bar | Material Web **无完整官方 App Bar 时**：用 surface 容器 + typescale + 导航 `md-text-button` 手写壳，视觉对齐 M3 |

### 3.4 约束

- 不引入 React/Vue、不引入 npm 构建链（本版）。
- CDN 不可用时的降级：文档注明需可访问 `esm.run` / fonts；内网可改镜像 import map（实现时留注释位）。
- 遵守 `prefers-reduced-motion`（减弱非必要过渡）。

## 4. 信息架构与路由

### 4.1 凭证

| 页面 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 列表 | GET | `/settings/credentials` | 按厂商分组；编辑 / 删除 |
| 添加 | GET | `/settings/credentials/new` | 独立表单 |
| 添加提交 | POST | `/settings/credentials` | 成功 → 列表 `?ok=1`；失败 → `/new?err=` |
| 编辑 | GET | `/settings/credentials/{id}/edit` | 密钥留空 = 不改 |
| 更新 | POST | `/settings/credentials/{id}/update` | 成功 → 列表；失败 → edit `?err=` |
| 删除 | POST | `/settings/credentials/{id}/delete` | 列表触发；被引用 Banner 报错 |

### 4.2 其它页面（路由不变，模板重写）

- `/login`、`/register`
- `/certs`、添加 / 编辑 / 验证相关路径
- `/settings/profiles`（及现有 create/update/delete POST）

### 4.3 交互

- 列表主 CTA：「添加凭证」→ `/new`
- 编辑页不放删除；删除仅列表（可用 `md-dialog` 确认）
- 阿里云 CAS 地域：添加页用 select 切换显示（少量页面 JS）

## 5. 页面结构（凭证）

**列表**：Banner + 标题 + Filled「添加凭证」；三组厂商；`md-list-item` 展示名称与操作；底注链到配置档。

**添加**：返回；名称 / 厂商 / AK / SK / CAS；取消 Outlined + 保存 Filled。

**编辑**：返回；厂商只读 chip；名称 / AK / SK / CAS；取消 + 保存。

## 6. 模板与静态资源

- `base.html`：import map、字体、主题 token、App 壳、公共 Banner 宏/片段。
- 凭证模板：`settings/credentials_list.html`、`credentials_new.html`、`credentials_edit.html`（或 `settings/credentials/` 子目录）。
- 其余现有模板全部改为 md-* 控件。
- 可选 `web/static/` 放少量布局 CSS（间距、主列宽、Banner）；**交互组件以 Material Web 为准**。

## 7. 验收标准

1. 凭证三路由走通；旧单页混排消失。
2. 密钥留空更新不改密文；删除被引用时报错可见。
3. 全站页面使用 Material Web 控件（壳层允许手写 M3 布局）。
4. 表单 POST 字段名与现有后端一致；e2e / 相关测试更新后通过。
5. 无 React/Vue/bundler；依赖为 CDN Material Web + 字体。

## 8. 风险

- CDN / 外网字体在离线环境失败 → import map 可换镜像。
- Web Components 与渐进增强：无 JS 时控件可能不渲染 → 登录与关键表单需在 README 注明需现代浏览器。
- `web/` 与开源 CLI 边界：本任务仅 Web UI，提交策略另议。
- 迁移 `002` 破坏性清空与本 UI 无关，不在此任务修改。

## 9. 修订记录

- 2026-08-31：初版纯 CSS M3。
- 2026-08-31：用户要求引入 Material；改为 Material Web CDN 整站重写。
