#ifndef WEBP_IMAGE_H
#define WEBP_IMAGE_H

// webp image decoder and encoder with libwebp
// 适配自 nihui/realcugan-ncnn-vulkan（MIT），改动：
//   1. 解码输出统一 RGB(A) 通道序（原 Windows 分支为 BGR(A)，配合 WIC；本引擎用 stb，全链路 RGB）
//   2. webp_save 增加有损质量参数（0-100，对应规格的 -q/--quality）
#include <stdio.h>
#include <stdlib.h>
#include "webp/decode.h"
#include "webp/encode.h"

unsigned char* webp_load(const unsigned char* buffer, int len, int* w, int* h, int* c)
{
    unsigned char* pixeldata = 0;

    WebPDecoderConfig config;
    WebPInitDecoderConfig(&config);

    if (WebPGetFeatures(buffer, len, &config.input) != VP8_STATUS_OK)
        return NULL;

    int width = config.input.width;
    int height = config.input.height;
    int channels = config.input.has_alpha ? 4 : 3;

    pixeldata = (unsigned char*)malloc(width * height * channels);

    config.output.colorspace = channels == 4 ? MODE_RGBA : MODE_RGB;

    config.output.u.RGBA.stride = width * channels;
    config.output.u.RGBA.size = width * height * channels;
    config.output.u.RGBA.rgba = pixeldata;
    config.output.is_external_memory = 1;

    if (WebPDecode(buffer, len, &config) != VP8_STATUS_OK)
    {
        free(pixeldata);
        return NULL;
    }

    *w = width;
    *h = height;
    *c = channels;

    return pixeldata;
}

#if _WIN32
int webp_save(const wchar_t* filepath, int w, int h, int c, const unsigned char* pixeldata, float quality)
#else
int webp_save(const char* filepath, int w, int h, int c, const unsigned char* pixeldata, float quality)
#endif
{
    int ret = 0;

    uint8_t* output = 0;
    size_t length = 0;

    FILE* fp = 0;

    if (c == 3)
    {
        // 有损编码，quality 0-100
        length = WebPEncodeRGB(pixeldata, w, h, w * 3, quality, &output);
    }
    else
    {
        // 本引擎推理链路固定输出 3 通道（01 阶段 alpha 已拍平），4 通道不支持
        return 0;
    }

    if (length == 0)
        goto RETURN;

#if _WIN32
    fp = _wfopen(filepath, L"wb");
#else
    fp = fopen(filepath, "wb");
#endif
    if (!fp)
        goto RETURN;

    fwrite(output, 1, length, fp);

    ret = 1;

RETURN:
    if (output) WebPFree(output);
    if (fp) fclose(fp);

    return ret;
}

#endif // WEBP_IMAGE_H
