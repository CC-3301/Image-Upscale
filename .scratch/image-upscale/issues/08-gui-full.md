# 08: GUI 完整功能

**Parent:** .scratch/image-upscale/spec.md

**What to build:** GUI 与 CLI 能力完全对齐：文件夹拖拽递归批处理、逐文件汇总列表、降噪选项随模型能力禁用并提示原因。至此 GUI 用户拥有 CLI 用户的一切能力，反之亦然。

**Blocked by:** 07, 05, 06

**Status:** ready-for-agent

- [ ] 拖入文件夹触发递归处理，展示逐文件进度与成功/失败汇总列表
- [ ] 选中不支持降噪的模型（digital-art-4x、导入模型）时降噪控件禁用并提示
- [ ] AUTO 档出现在降噪档位首位，手动选档后行为与 CLI 一致
- [ ] GUI 与 CLI 对同一输入产出完全一致的产物（命名、格式、内容）
- [ ] 手动验收清单通过
