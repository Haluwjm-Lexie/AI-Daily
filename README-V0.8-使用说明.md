# AI Daily V0.8｜上线前修订版（尚未部署）

## 先做什么

建议你**先用本地修订版检查视觉和交互，再启用 GitHub Pages**。现有 `V0.5/AI-Daily` 才是你的真正项目，请先将它整个备份一份。

**只替换这些文件**：

- `server.py`
- `public/index.html`
- `public/app.js`
- `public/style.css`
- `public/wordmark.svg` 和 `public/wordmark-dark.svg`（新文件）
- `public/favicon.png`（新文件）

不要用新包覆盖你原来的 `.env`、`data` 或 `start.bat`。原有历史内容全部依赖旧 `data`；这个 ZIP **不包含你电脑上的数据库**。

重启原项目的 `start.bat`，在浏览器按 `Ctrl+F5`。打开日报和 GitHub Trending，确认“本期完”、前后期切换、置顶按钮和Logo。

## 改了什么

1. 品牌：保留确认过的轨道 A 图标作为浏览器 favicon／群头像；文字 AI Daily 改成独立设计的 SVG 字标。
2. 阅读：去掉多余外框感，保持宽屏三栏阅读，隐藏阅读区域的灰色滚动条但保留滚动，并在正文右下提供“返回顶部”。
3. 仪式感：日报及 GitHub 阅读正文增加“（本期完）”、上下期跳转；没有历史上下期时不虚构。
4. GitHub：导航使用日/周/月/季/年报，往期标题从实际热门仓库名称生成摘要，不再只显示日期快照。
5. 飞书：卡片有头条、摘要、重点资讯、简短推荐理由、原始报道链接。只有设置 `PUBLIC_URL` 后才出现“在 AI Daily 阅读”的网站链接。没有上线之前不会指向 AIHOT 假装是本站。

## GitHub Pages 专用版（准备好，尚未上线）

- `site/`：GitHub Pages 读取的静态网站；`site/data/export.json` 是可公开的**精简资讯摘录**，不会上传数据库文件。
- `export_pages.py`：将已有归档/新同步数据转换为可公开的精选报告，以及 GitHub 真实快照。仅导出新闻标题、有限摘要和原文链接；不是完整镜像。
- `.github/workflows/aidaily.yml`：GitHub Actions 自动更新 + 提交公开 JSON + Pages 发布；设有 `workflow_dispatch` 手动补跑。
- 浏览器里每个访客的收藏和偏好默认保存在其自己的浏览器中，不跨设备同步。
- 公开版 GitHub 空心星星按钮**只打开对应 GitHub 仓库**，访客登录自己的 GitHub 后决定是否 Star，不使用你的 Token。

**不要上传**：`.env`、`data/`、任何 SQLite 文件、个人 Token、飞书 Webhook、个人收藏数据库。`.gitignore` 已覆盖这些路径。

### 等你验收后才按下列顺序部署

1. 新建 GitHub 仓库；确认需要对外展示的页面和精选摘要没有侵犯上游使用条款。
2. 只提交项目程序与 `site/`，检查仓库里找不到密钥。不要把整个原本的个人数据文件夹拖到 GitHub。
3. 在仓库 Settings → Secrets and variables → Actions 中设置 Secret `FEISHU_WEBHOOK_URL`；Variable `PUBLIC_URL` 为最终 Pages 网址。可选 Secret `DEEPSEEK_API_KEY`（翻译）。
4. 在 Settings → Pages，选择 Source: **GitHub Actions**。确保 Actions 有 Contents 写入和 Pages 部署权限，若仓库分支保护禁止推送归档文件，需要另外适配。
5. 在 Actions → AI Daily - sync and publish 手动运行一次；检查同步、归档、Pages、飞书通知，最后用手机打开真实网址并验证关机后仍更新。

### 定时任务与可接受的限制

- 计划北京时间 08:30（UTC 00:30）同步并准备日报通知；另在北京时间 11:15（UTC 03:15）补充同步。
- GitHub Actions 定时**可能延迟或跳过**，不是精确时钟；可手动运行工作流补采。
- 首次运行由于还没有真实来源数据，公开版可能显示“暂无归档”；不填虚构新闻。
- Github 历史趋势仅由实际抓取并保存的日榜快照形成，无法凭空恢复过去一年的真实榜单。
- 当前预上线版还未实测 GitHub Actions 真实运行、Pages 上线与飞书正式跳转；完成在线验收后才升级为 V1.0。
- 日志仅记录版本变化；数据库需要独立备份。不要拿静态 `site/data` 当私人原始数据库备份。
