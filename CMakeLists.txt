cmake_minimum_required(VERSION 3.16)

# 静态 CRT（后续 portable 发布依赖此设置）
cmake_policy(SET CMP0091 NEW)
set(CMAKE_POLICY_DEFAULT_CMP0091 NEW)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

project(image-upscale)

set(CMAKE_CXX_STANDARD 17)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE release CACHE STRING "Choose the type of build" FORCE)
endif()

option(USE_SYSTEM_NCNN "build with system libncnn" OFF)

find_package(Threads)
find_package(Vulkan REQUIRED)

# shader 源码内嵌为头文件（ncnn 运行时编译 GLSL -> SPIRV）
macro(image_upscale_add_shader SHADER_SRC)
    get_filename_component(SHADER_SRC_NAME_WE ${SHADER_SRC} NAME_WE)
    set(SHADER_COMP_HEADER ${CMAKE_CURRENT_BINARY_DIR}/${SHADER_SRC_NAME_WE}.comp.hex.h)

    add_custom_command(
        OUTPUT ${SHADER_COMP_HEADER}
        COMMAND ${CMAKE_COMMAND} -DSHADER_SRC=${CMAKE_CURRENT_SOURCE_DIR}/${SHADER_SRC} -DSHADER_COMP_HEADER=${SHADER_COMP_HEADER} -P "${CMAKE_CURRENT_SOURCE_DIR}/engine/src/generate_shader_comp_header.cmake"
        DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/${SHADER_SRC}
        COMMENT "Preprocessing shader source ${SHADER_SRC_NAME_WE}.comp"
        VERBATIM
    )
    set_source_files_properties(${SHADER_COMP_HEADER} PROPERTIES GENERATED TRUE)

    list(APPEND SHADER_SPV_HEX_FILES ${SHADER_COMP_HEADER})
endmacro()

include_directories(${CMAKE_CURRENT_BINARY_DIR})

# 链接时间优化
cmake_policy(SET CMP0069 NEW)
set(CMAKE_POLICY_DEFAULT_CMP0069 NEW)
include(CheckIPOSupported)
check_ipo_supported(RESULT ipo_supported OUTPUT ipo_supported_output)
if(ipo_supported)
    set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
else()
    message(WARNING "IPO is not supported: ${ipo_supported_output}")
endif()

# ---- ncnn ----
if(NOT USE_SYSTEM_NCNN)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/engine/third_party/ncnn/CMakeLists.txt")
        message(FATAL_ERROR "ncnn submodule missing! run: git submodule update --init --recursive")
    endif()

    option(NCNN_INSTALL_SDK "" OFF)
    option(NCNN_PIXEL_ROTATE "" OFF)
    option(NCNN_PIXEL_AFFINE "" OFF)
    option(NCNN_PIXEL_DRAWING "" OFF)
    option(NCNN_VULKAN "" ON)
    option(NCNN_SIMPLEVK "" ON)
    option(NCNN_BUILD_BENCHMARK "" OFF)
    option(NCNN_BUILD_TESTS "" OFF)
    option(NCNN_BUILD_TOOLS "" OFF)
    option(NCNN_BUILD_EXAMPLES "" OFF)
    option(NCNN_DISABLE_RTTI "" ON)
    option(NCNN_DISABLE_EXCEPTION "" ON)
    option(NCNN_INT8 "" OFF)
    option(NCNN_BF16 "" OFF)

    # 仅启用 waifu2x/cunet 模型所需的层（大幅缩短编译时间）
    option(WITH_LAYER_absval "" OFF)
    option(WITH_LAYER_argmax "" OFF)
    option(WITH_LAYER_batchnorm "" OFF)
    option(WITH_LAYER_bias "" OFF)
    option(WITH_LAYER_bnll "" OFF)
    option(WITH_LAYER_concat "" OFF)
    option(WITH_LAYER_crop "" ON)
    option(WITH_LAYER_convolution "" ON)
    option(WITH_LAYER_deconvolution "" ON)
    option(WITH_LAYER_dropout "" OFF)
    option(WITH_LAYER_eltwise "" ON)
    option(WITH_LAYER_elu "" OFF)
    option(WITH_LAYER_embed "" OFF)
    option(WITH_LAYER_exp "" OFF)
    option(WITH_LAYER_flatten "" ON)
    option(WITH_LAYER_innerproduct "" ON)
    option(WITH_LAYER_input "" ON)
    option(WITH_LAYER_log "" OFF)
    option(WITH_LAYER_lrn "" OFF)
    option(WITH_LAYER_memorydata "" OFF)
    option(WITH_LAYER_mvn "" OFF)
    option(WITH_LAYER_pooling "" ON)
    option(WITH_LAYER_power "" OFF)
    option(WITH_LAYER_prelu "" OFF)
    option(WITH_LAYER_proposal "" OFF)
    option(WITH_LAYER_reduction "" OFF)
    option(WITH_LAYER_relu "" ON)
    option(WITH_LAYER_reshape "" OFF)
    option(WITH_LAYER_roipooling "" OFF)
    option(WITH_LAYER_scale "" ON)
    option(WITH_LAYER_sigmoid "" OFF)
    option(WITH_LAYER_slice "" OFF)
    option(WITH_LAYER_softmax "" OFF)
    option(WITH_LAYER_spp "" OFF)
    option(WITH_LAYER_tanh "" OFF)
    option(WITH_LAYER_threshold "" OFF)
    option(WITH_LAYER_tile "" OFF)
    option(WITH_LAYER_rnn "" OFF)
    option(WITH_LAYER_lstm "" OFF)
    option(WITH_LAYER_binaryop "" OFF)
    option(WITH_LAYER_unaryop "" OFF)
    option(WITH_LAYER_convolutiondepthwise "" OFF)
    option(WITH_LAYER_padding "" ON)
    option(WITH_LAYER_squeeze "" OFF)
    option(WITH_LAYER_expanddims "" OFF)
    option(WITH_LAYER_normalize "" OFF)
    option(WITH_LAYER_permute "" OFF)
    option(WITH_LAYER_priorbox "" OFF)
    option(WITH_LAYER_detectionoutput "" OFF)
    option(WITH_LAYER_interp "" ON) # waifu2x.cpp 的 alpha bicubic 用 Interp，关掉必崩
    option(WITH_LAYER_deconvolutiondepthwise "" OFF)
    option(WITH_LAYER_shufflechannel "" OFF)
    option(WITH_LAYER_instancenorm "" OFF)
    option(WITH_LAYER_clip "" OFF)
    option(WITH_LAYER_reorg "" OFF)
    option(WITH_LAYER_yolodetectionoutput "" OFF)
    option(WITH_LAYER_quantize "" OFF)
    option(WITH_LAYER_dequantize "" OFF)
    option(WITH_LAYER_yolov3detectionoutput "" OFF)
    option(WITH_LAYER_psroipooling "" OFF)
    option(WITH_LAYER_roialign "" OFF)
    option(WITH_LAYER_packing "" ON)
    option(WITH_LAYER_requantize "" OFF)
    option(WITH_LAYER_cast "" ON)
    option(WITH_LAYER_hardsigmoid "" OFF)
    option(WITH_LAYER_selu "" OFF)
    option(WITH_LAYER_hardswish "" OFF)
    option(WITH_LAYER_noop "" OFF)
    option(WITH_LAYER_pixelshuffle "" OFF)
    option(WITH_LAYER_deepcopy "" OFF)
    option(WITH_LAYER_mish "" OFF)
    option(WITH_LAYER_statisticspooling "" OFF)
    option(WITH_LAYER_swish "" OFF)
    option(WITH_LAYER_gemm "" OFF)
    option(WITH_LAYER_groupnorm "" OFF)
    option(WITH_LAYER_layernorm "" OFF)
    option(WITH_LAYER_softplus "" OFF)
    option(WITH_LAYER_gru "" OFF)
    option(WITH_LAYER_multiheadattention "" OFF)
    option(WITH_LAYER_gelu "" OFF)
    option(WITH_LAYER_convolution1d "" OFF)
    option(WITH_LAYER_pooling1d "" OFF)
    option(WITH_LAYER_convolutiondepthwise1d "" OFF)
    option(WITH_LAYER_convolutiondepthwise3d "" OFF)
    option(WITH_LAYER_pooling3d "" OFF)
    option(WITH_LAYER_matmul "" OFF)
    option(WITH_LAYER_deconvolution1d "" OFF)
    option(WITH_LAYER_deconvolutiondepthwise1d "" OFF)
    option(WITH_LAYER_deconvolutiondepthwise3d "" OFF)
    option(WITH_LAYER_einsum "" OFF)
    option(WITH_LAYER_deformableconv2d "" OFF)
    option(WITH_LAYER_glu "" OFF)
    option(WITH_LAYER_fold "" OFF)
    option(WITH_LAYER_unfold "" OFF)
    option(WITH_LAYER_gridsample "" OFF)
    option(WITH_LAYER_cumulativesum "" OFF)
    option(WITH_LAYER_copyto "" OFF)
    option(WITH_LAYER_erf "" OFF)
    option(WITH_LAYER_diag "" OFF)
    option(WITH_LAYER_celu "" OFF)
    option(WITH_LAYER_shrink "" OFF)
    option(WITH_LAYER_rmsnorm "" OFF)
    option(WITH_LAYER_spectrogram "" OFF)
    option(WITH_LAYER_inversespectrogram "" OFF)

    add_subdirectory(engine/third_party/ncnn)
endif()

# ---- libwebp（静态，仅解码/编码核心） ----
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/engine/third_party/libwebp/CMakeLists.txt")
    message(FATAL_ERROR "libwebp submodule missing! run: git submodule update --init --recursive")
endif()

option(BUILD_SHARED_LIBS "" OFF)
option(WEBP_ENABLE_SIMD "" ON)
option(WEBP_BUILD_ANIM_UTILS "" OFF)
option(WEBP_BUILD_CWEBP "" OFF)
option(WEBP_BUILD_DWEBP "" OFF)
option(WEBP_BUILD_GIF2WEBP "" OFF)
option(WEBP_BUILD_IMG2WEBP "" OFF)
option(WEBP_BUILD_VWEBP "" OFF)
option(WEBP_BUILD_WEBPINFO "" OFF)
option(WEBP_BUILD_WEBPMUX "" OFF)
option(WEBP_BUILD_EXTRAS "" OFF)
option(WEBP_BUILD_WEBP_JS "" OFF)
option(WEBP_NEAR_LOSSLESS "" OFF)
option(WEBP_ENABLE_SWAP_16BIT_CSP "" OFF)

add_subdirectory(engine/third_party/libwebp)

# ---- 引擎 exe ----
image_upscale_add_shader(engine/src/waifu2x_preproc.comp)
image_upscale_add_shader(engine/src/waifu2x_postproc.comp)
image_upscale_add_shader(engine/src/waifu2x_preproc_tta.comp)
image_upscale_add_shader(engine/src/waifu2x_postproc_tta.comp)
image_upscale_add_shader(engine/src/realcugan_preproc.comp)
image_upscale_add_shader(engine/src/realcugan_postproc.comp)
image_upscale_add_shader(engine/src/realcugan_4x_postproc.comp)
image_upscale_add_shader(engine/src/realcugan_preproc_tta.comp)
image_upscale_add_shader(engine/src/realcugan_postproc_tta.comp)
image_upscale_add_shader(engine/src/realcugan_4x_postproc_tta.comp)
image_upscale_add_shader(engine/src/realesrgan_preproc.comp)
image_upscale_add_shader(engine/src/realesrgan_postproc.comp)
image_upscale_add_shader(engine/src/realesrgan_preproc_tta.comp)
image_upscale_add_shader(engine/src/realesrgan_postproc_tta.comp)

# ---- 引擎核心（DLL，工单 27）：GUI 进程内 P/Invoke 调用；随发布分发 ----
add_library(iu_engine SHARED
    engine/src/engine_core.cpp
    engine/src/waifu2x.cpp
    engine/src/realcugan.cpp
    engine/src/realesrgan.cpp
    ${SHADER_SPV_HEX_FILES}
)

target_compile_definitions(iu_engine PRIVATE IU_ENGINE_BUILDING)

target_include_directories(iu_engine PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/engine/src
    ${CMAKE_CURRENT_SOURCE_DIR}/engine/third_party/libwebp/src
)

target_compile_options(iu_engine PRIVATE
    $<$<CXX_COMPILER_ID:MSVC>:/utf-8>
)

# ---- 测试缝 CLI 薄壳（工单 27）：仅自动化测试用，不随发布分发 ----
add_executable(image-upscale
    engine/src/main.cpp
)

target_include_directories(image-upscale PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/engine/src
)

target_compile_options(image-upscale PRIVATE
    $<$<CXX_COMPILER_ID:MSVC>:/utf-8>
)

option(IU_ENABLE_ASAN "对本项目两个目标启用 AddressSanitizer（不含 third_party）" OFF)
if(IU_ENABLE_ASAN)
    # 必须用 target_* 形式：add_compile_options / add_link_options 只影响其之后创建的目标，
    # 而 iu_engine 与 image-upscale 都在本块之前就已创建（原实现等于开关空转）
    # 注意：ASAN 与静态 CRT（/MT）不兼容，需要时另行调整
    foreach(_iu_tgt iu_engine image-upscale)
        target_compile_options(${_iu_tgt} PRIVATE $<$<CXX_COMPILER_ID:MSVC>:/fsanitize=address>)
        target_link_options(${_iu_tgt} PRIVATE $<$<CXX_COMPILER_ID:MSVC>:/fsanitize=address>)
    endforeach()
endif()

target_link_libraries(iu_engine PRIVATE
    ncnn
    webp
    sharpyuv
    Threads::Threads
)

target_link_libraries(image-upscale PRIVATE
    iu_engine
)
