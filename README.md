# AI Daily

一个公开可读的 AI 情报阅读器，基于 AIHOT 资讯及 GitHub Trending 观察。静态发布使用 GitHub Pages；GitHub Actions 定时更新精选公开数据并发出飞书通知。

**上线前请阅读 `上线操作说明.md`。** 不要将本机 `.env`、`data/`、数据库或私人 Token 提交到公开仓库。

主要文件：`site/`（站点），`export_pages.py`（安全导出），`.github/workflows/aidaily.yml`（定时构建与 Pages 发布），`public/`、`server.py`、`start.bat`（本地管理版）。

公开版访客在 GitHub 点 Star 使用的是自己的 GitHub 登录，不会接触站长的密钥；个人收藏和偏好只保存在访客本机浏览器中。
