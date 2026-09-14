# realesr-general-x4v3 → ncnn 转换（工单 03）
# 架构定义移植自 xinntao/Real-ESRGAN (BSD-3) srvgg_arch.py；
# base/wdn 按官方 DNI 插值生成 无/低/中/高 四个降噪变体，pnnx 逐个转 ncnn。
import os
import subprocess
import sys

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(HERE, "..", ".tmp-convert")
OUT = os.path.join(HERE, "..", "models", "realesr-general-x4v3")


class SRVGGNetCompact(nn.Module):
    """官方 SRVGGNetCompact（num_feat=64, num_conv=32, upscale=4, prelu）"""

    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4, act_type="prelu"):
        super().__init__()
        self.num_in_ch = num_in_ch
        self.num_out_ch = num_out_ch
        self.num_feat = num_feat
        self.num_conv = num_conv
        self.upscale = upscale
        self.act_type = act_type

        self.body = nn.ModuleList()
        self.body.append(nn.Conv2d(num_in_ch, num_feat, 3, 1, 1))
        self.body.append(self._act())
        for _ in range(num_conv):
            self.body.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
            self.body.append(self._act())
        self.body.append(nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1))
        self.upsampler = nn.PixelShuffle(upscale)

    def _act(self):
        if self.act_type == "relu":
            return nn.ReLU(inplace=True)
        if self.act_type == "leakyrelu":
            return nn.LeakyReLU(negative_slope=0.1, inplace=True)
        return nn.PReLU(num_parameters=self.num_feat)

    def forward(self, x):
        out = x
        for layer in self.body:
            out = layer(out)
        out = self.upsampler(out)
        base = F.interpolate(x, scale_factor=self.upscale, mode="bilinear")
        out += base
        return out


def load_state(path):
    sd = torch.load(path, map_location="cpu", weights_only=True)
    if "params_ema" in sd:
        sd = sd["params_ema"]
    elif "params" in sd:
        sd = sd["params"]
    return sd


def main():
    base = load_state(os.path.join(TMP, "realesr-general-x4v3.pth"))
    wdn = load_state(os.path.join(TMP, "realesr-general-wdn-x4v3.pth"))

    # 官方 DNI 插值：w = (1-s)*base + s*wdn；s=0 保留噪点（无），s=1 强降噪（高）
    levels = {"": 0.0, "-low": 0.33, "-mid": 0.66, "-high": 1.0}

    model = SRVGGNetCompact(num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4, act_type="prelu")
    dummy = torch.randn(1, 3, 64, 64)

    os.makedirs(OUT, exist_ok=True)
    pnnx = os.path.join(sys.prefix, "Scripts", "pnnx.exe")
    if not os.path.exists(pnnx):
        pnnx = "pnnx"  # PATH 兜底

    for suffix, s in levels.items():
        blended = {k: (1.0 - s) * base[k].float() + s * wdn[k].float() for k in base}
        model.load_state_dict(blended, strict=True)
        model.eval()
        pt_path = os.path.join(TMP, f"x4v3{suffix}.pt")
        scripted = torch.jit.trace(model, dummy)
        scripted.save(pt_path)

        run_dir = os.path.join(TMP, f"run{suffix}")
        os.makedirs(run_dir, exist_ok=True)
        pt_in = os.path.join(run_dir, f"x4v3{suffix}.pt")
        os.replace(pt_path, pt_in)
        r = subprocess.run(
            [pnnx, pt_in, "inputshape=[1,3,64,64]"],
            cwd=run_dir, capture_output=True, text=True,
        )
        param = os.path.join(run_dir, f"x4v3{suffix}.ncnn.param".replace('-', '_'))
        binn = os.path.join(run_dir, f"x4v3{suffix}.ncnn.bin".replace('-', '_'))
        if r.returncode != 0 or not os.path.exists(param):
            print(r.stdout[-2000:])
            print(r.stderr[-2000:])
            raise SystemExit(f"pnnx failed for s={s}")

        # blob 名规范化：pnnx 的 in0/out0 → 引擎约定 data/output
        with open(param, "r", encoding="utf-8") as f:
            text = f.read()
        text = text.replace(" in0", " data").replace(" out0", " output")
        with open(os.path.join(OUT, f"realesr-general-x4v3{suffix}.param"), "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(binn, os.path.join(OUT, f"realesr-general-x4v3{suffix}.bin"))
        print(f"converted s={s} -> realesr-general-x4v3{suffix}")

    print("all done ->", OUT)


if __name__ == "__main__":
    main()
