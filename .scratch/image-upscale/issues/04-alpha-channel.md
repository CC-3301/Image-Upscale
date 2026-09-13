# 04: alpha 透明通道

**Parent:** .scratch/image-upscale/spec.md

**What to build:** 用户处理带透明通道的图片（漫画素材、贴纸）时，透明信息被正确对待：输出 PNG/WebP 时 alpha 与 RGB 分离推理再合成、透明完整保留；输出 JPG 时与白色背景合成，不出现黑底。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 带 alpha 的输入 + PNG 输出：alpha 通道经超分后合成，透明/半透明区域正确
- [ ] 带 alpha 的输入 + WebP 输出：同上
- [ ] 带 alpha 的输入 + JPG 输出（默认格式）：与白色背景合成，无 alpha、无黑边
- [ ] 无 alpha 的普通图片行为与 01 完全一致（无回归）
- [ ] 测试含 alpha fixture（透明、半透明边缘两种）
