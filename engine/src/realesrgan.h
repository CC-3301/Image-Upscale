// realesrgan implemented with ncnn library

#ifndef REALESRGAN_H
#define REALESRGAN_H

#include <string>

// ncnn
#include "net.h"
#include "gpu.h"
#include "layer.h"

class RealESRGAN
{
public:
    RealESRGAN(int gpuid, int num_threads, bool tta_mode = false);
    ~RealESRGAN();

#if _WIN32
    int load(const std::wstring& parampath, const std::wstring& modelpath);
#else
    int load(const std::string& parampath, const std::string& modelpath);
#endif

    int process(const ncnn::Mat& inimage, ncnn::Mat& outimage) const;


    int process_cpu(const ncnn::Mat& inimage, ncnn::Mat& outimage) const;

public:
    // realesrgan parameters
    int scale;
    int tilesize;
    int prepadding;

private:
    ncnn::Net net;
    ncnn::Pipeline* realesrgan_preproc;
    ncnn::Pipeline* realesrgan_postproc;
    ncnn::Layer* bicubic_2x;
    ncnn::Layer* bicubic_3x;
    ncnn::Layer* bicubic_4x;
    bool tta_mode;

    // 释放当前已加载的权重与全部管线（load() 开头与析构共用）
    void release();
};

#endif // REALESRGAN_H
