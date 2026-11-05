# 72: LOGO 重制

**What to build:** 把现有的紫蓝渐变图标换成石墨黑圆角方底 + 白色几何 IU，字母占画布 55%；新图标同时作为 exe 文件图标与窗口/任务栏图标。

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `app.png` 为 512×512，底色纯色 `#24262B`、字形 `#FFFFFF`，无渐变
- [ ] 字母外接方框高度 = 画布边长 × 0.55
- [ ] `app.ico` 含 16/32/48/64/128/256 六档；16px 下 I 与 U 仍可分辨
- [ ] 构建后 exe 文件图标与窗口/任务栏图标均为新图标
- [ ] 生成脚本可重跑，产物与入库文件一致
