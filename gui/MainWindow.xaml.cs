using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.ComponentModel;
using Microsoft.Win32;

namespace ImageUpscaleGui;

public class ModelEntry
{
    public string Id = "";
    public string Display = "";
    public string Group = "";
    public string Arch = "";
    public string Dir = "";
    public List<int> Scales = new();
    public Dictionary<int, int> Prepad = new();
    public string InBlob = "";
    public string OutBlob = "";
    public string TileAuto = "";
    public Dictionary<int, string> Denoise = new();

    // 工单 23：支持降噪 = 存在 none 以外的档位（低/中/高任一）
    public bool SupportsDenoise => Denoise.Keys.Any(k => k != 0);
}

public partial class MainWindow : Window
{
    private string _enginePath;
    private string _modelsDir;
    private List<ModelEntry> _models = new();
    private Process _running;

    // 工单 20：ETA 估算
    private readonly Stopwatch _etaStopwatch = new();
    private int _etaLastDone;

    // 工单 13：滑条 ↔ 输入框同步的重入保护
    private bool _qualitySyncing;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += OnLoaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (!LocateEngine(out _enginePath, out _modelsDir))
        {
            Log("错误：未找到引擎 image-upscale.exe 或 models 目录（请确认目录布局）");
            StartButton.IsEnabled = false;
            return;
        }

        _models = EngineClient.ParseManifest(Path.Combine(_modelsDir, "manifest.conf"));
        if (_models.Count == 0)
        {
            Log("错误：models/manifest.conf 解析失败或为空");
            StartButton.IsEnabled = false;
            return;
        }

        // 工单 21：显示名 A-Z 排序（不区分大小写），清单顺序不影响展示
        _models.Sort((a, b) => string.Compare(a.Display, b.Display, StringComparison.OrdinalIgnoreCase));
        foreach (var m in _models)
            ModelBox.Items.Add(m.Display);

        // 工单 14：恢复上次设置（先选模型触发能力钳制，再恢复其余项）
        var s = SettingsStore.Load();
        var modelIdx = _models.FindIndex(m => m.Id == s.ModelId);
        ModelBox.SelectedIndex = modelIdx >= 0 ? modelIdx : 0;
        RestoreSettings(s);

        Log($"引擎就绪：{_enginePath}");
        Log($"已加载 {_models.Count} 个模型");
    }

    // 恢复尺寸模式 / 倍率 / 宽高 / 格式 / 质量（模型选择已完成，OnModelChanged 已跑过）
    private void RestoreSettings(SettingsStore s)
    {
        if (_models.Count == 0 || ModelBox.SelectedIndex < 0)
            return;
        var m = _models[ModelBox.SelectedIndex];

        // 尺寸模式 + 各模式数值
        ModeScale.IsChecked = s.ScaleMode != "width" && s.ScaleMode != "height";
        ModeWidth.IsChecked = s.ScaleMode == "width";
        ModeHeight.IsChecked = s.ScaleMode == "height";
        var scaleIdx = m.Scales.IndexOf(s.Scale);
        ScaleBox.SelectedIndex = scaleIdx >= 0 ? scaleIdx : 0;
        if (s.ScaleWidth > 0) WidthBox.Text = s.ScaleWidth.ToString();
        if (s.ScaleHeight > 0) HeightBox.Text = s.ScaleHeight.ToString();

        // 输出格式
        var fmtIdx = s.OutputExt switch { "jpg" => 0, "png" => 1, "webp" => 2, _ => 0 };
        FormatBox.SelectedIndex = fmtIdx;

        // 质量
        if (s.OutputQuality >= 0 && s.OutputQuality <= 100)
            QualitySlider.Value = s.OutputQuality;
        else
            OnQualitySliderChanged(null, null); // 确保输入框与滑条初始一致
    }

    private static bool LocateEngine(out string enginePath, out string modelsDir)
    {
        var exeDir = AppContext.BaseDirectory;
        // 工单 16：分发布局引擎在 engine/ 子目录；开发布局仍从 bld 查找
        foreach (var cand in new[]
                 {
                     exeDir,
                     Path.Combine(exeDir, "engine"),
                     Path.Combine(exeDir, "..", "bld"),
                     Path.Combine(exeDir, "..", "engine"),
                     Path.Combine(exeDir, "..", "..", "bld"),
                     Path.Combine(exeDir, "..", "..", "engine"),
                     Path.Combine(exeDir, "..", "..", "..", "bld"),
                     Path.Combine(exeDir, "..", "..", "..", "engine"),
                     Path.Combine(exeDir, "..", "..", "..", "..", "bld"),
                     Path.Combine(exeDir, "..", "..", "..", "..", "engine"),
                 })
        {
            var full = Path.GetFullPath(cand);
            var exe = Path.Combine(full, "image-upscale.exe");
            if (File.Exists(exe))
            {
                enginePath = exe;
                // 模型目录：优先引擎同级的 models，其次仓库根（开发布局）
                var m1 = Path.Combine(full, "models");
                if (Directory.Exists(m1)) { modelsDir = m1; return true; }
                var m2 = Path.GetFullPath(Path.Combine(full, "..", "models"));
                if (Directory.Exists(m2)) { modelsDir = m2; return true; }
                modelsDir = m1;
                return true;
            }
        }
        enginePath = null;
        modelsDir = null;
        return false;
    }

    private void OnModelChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ModelBox.SelectedIndex < 0 || _models.Count == 0)
            return;
        var m = _models[ModelBox.SelectedIndex];

        // 倍率选项随模型原生倍数
        ScaleBox.Items.Clear();
        foreach (var sc in m.Scales)
            ScaleBox.Items.Add($"{sc}.0x");
        ScaleBox.SelectedIndex = 0;

        // 降噪档位（工单 22 中文文案；工单 23 能力判据；工单 24 默认自动、不支持固定无）
        DenoiseBox.Items.Clear();
        DenoiseBox.Items.Add("自动");
        DenoiseBox.Items.Add("无");
        if (m.Denoise.ContainsKey(1)) DenoiseBox.Items.Add("低");
        if (m.Denoise.ContainsKey(2)) DenoiseBox.Items.Add("中");
        if (m.Denoise.ContainsKey(3)) DenoiseBox.Items.Add("高");
        if (m.SupportsDenoise)
        {
            DenoiseHint.Visibility = Visibility.Collapsed;
            DenoiseBox.IsEnabled = true;
            DenoiseBox.SelectedIndex = 0; // 自动
        }
        else
        {
            DenoiseHint.Visibility = Visibility.Visible;
            DenoiseBox.IsEnabled = false;
            DenoiseBox.SelectedIndex = 1; // 无
        }
    }

    // ---- 工单 13：质量滑条 ↔ 输入框双向同步 ----
    private void OnQualitySliderChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (QualityInput == null || _qualitySyncing) return;
        _qualitySyncing = true;
        QualityInput.Text = ((int)QualitySlider.Value).ToString();
        _qualitySyncing = false;
    }

    private void OnQualityInputChanged(object sender, TextChangedEventArgs e)
    {
        if (QualitySlider == null || _qualitySyncing) return;
        if (int.TryParse(QualityInput.Text, out var q))
        {
            q = Math.Clamp(q, 0, 100);
            _qualitySyncing = true;
            QualitySlider.Value = q;
            _qualitySyncing = false;
        }
    }

    // 非法输入（非数字/超界残留文本）在失焦时回退为滑条当前值
    private void OnQualityInputLostFocus(object sender, RoutedEventArgs e)
    {
        if (!int.TryParse(QualityInput.Text, out var q) || q != (int)QualitySlider.Value)
        {
            _qualitySyncing = true;
            QualityInput.Text = ((int)QualitySlider.Value).ToString();
            _qualitySyncing = false;
        }
    }

    private void OnBrowse(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog
        {
            Filter = "图片 (jpg/jpeg/png/webp)|*.jpg;*.jpeg;*.png;*.webp|所有文件|*.*"
        };
        if (dlg.ShowDialog() == true)
            InputBox.Text = dlg.FileName;
    }

    private void OnDragOver(object sender, DragEventArgs e) => HandleDragOver(e);

    private void OnDrop(object sender, DragEventArgs e) => HandleDrop(e);

    // 工单 11：输入框自身接受拖放（TextBox 内建处理会吞掉冒泡事件，用隧道事件拦截）
    private void OnInputPreviewDragOver(object sender, DragEventArgs e) => HandleDragOver(e);

    private void OnInputPreviewDrop(object sender, DragEventArgs e) => HandleDrop(e);

    private static void HandleDragOver(DragEventArgs e)
    {
        e.Effects = e.Data.GetDataPresent(DataFormats.FileDrop) ? DragDropEffects.Copy : DragDropEffects.None;
        e.Handled = true;
    }

    private void HandleDrop(DragEventArgs e)
    {
        if (e.Data.GetData(DataFormats.FileDrop) is string[] files && files.Length > 0)
            InputBox.Text = files[0];
        e.Handled = true;
    }

    private async void OnStart(object sender, RoutedEventArgs e)
    {
        var input = InputBox.Text;
        if (string.IsNullOrWhiteSpace(input) || !File.Exists(input) && !Directory.Exists(input))
        {
            MessageBox.Show("请先选择有效的输入文件或文件夹", "提示");
            return;
        }
        if (_running != null)
        {
            MessageBox.Show("已有任务在运行", "提示");
            return;
        }

        var m = _models[ModelBox.SelectedIndex];
        var args = new StringBuilder();
        args.Append("-i \"").Append(input).Append("\"");
        args.Append(" -m ").Append(m.Id);

        if (ModeScale.IsChecked == true)
        {
            if (ScaleBox.SelectedItem == null) { MessageBox.Show("请选择倍率", "提示"); return; }
            args.Append(" -s ").Append(ScaleBox.SelectedItem);
        }
        else if (ModeWidth.IsChecked == true)
        {
            if (!int.TryParse(WidthBox.Text, out var w) || w <= 0) { MessageBox.Show("请输入有效的目标宽度", "提示"); return; }
            args.Append(" --width ").Append(w);
        }
        else
        {
            if (!int.TryParse(HeightBox.Text, out var h) || h <= 0) { MessageBox.Show("请输入有效的目标高度", "提示"); return; }
            args.Append(" --height ").Append(h);
        }

        // 降噪：自动 → --denoise auto；无 → none；低/中/高 → low/mid/high（工单 22/23/24）
        var dSel = DenoiseBox.SelectedIndex;
        if (dSel == 0) args.Append(" --denoise auto");
        else if (dSel == 1) args.Append(" --denoise none");
        else args.Append(" --denoise ").Append(dSel == 2 ? "low" : dSel == 3 ? "mid" : "high");

        var fmt = ((ComboBoxItem)FormatBox.SelectedItem).Content.ToString();
        args.Append(" -f ").Append(fmt.ToLower());
        if (fmt != "PNG")
            args.Append(" -q ").Append((int)QualitySlider.Value);
        args.Append(" -v"); // 逐文件明细（stderr）

        Log($"开始：{Path.GetFileName(input)}（{m.Display}）");

        StartButton.IsEnabled = false;
        Progress.Value = 0;
        ProgressText.Text = "";
        LogBox.Clear();
        _etaStopwatch.Restart();
        _etaLastDone = 0;

        var exitCode = await Task.Run(() => EngineClient.Run(
            _enginePath, Path.GetDirectoryName(_enginePath), args.ToString(),
            line =>
            {
                Dispatcher.Invoke(() =>
                {
                    if (line.StartsWith("progress "))
                    {
                        var parts = line.Split(' ');
                        if (parts.Length == 2 && int.TryParse(parts[1].Split('/')[0], out var d)
                            && int.TryParse(parts[1].Split('/')[1], out var t))
                        {
                            Progress.Value = 100.0 * d / Math.Max(1, t);
                            // 工单 20：预计剩余时间（已完成文件滑动平均 × 剩余数）
                            if (d > _etaLastDone)
                            {
                                if (t <= 1)
                                {
                                    ProgressText.Text = $"{d}/{t}";
                                }
                                else
                                {
                                    var avgSec = _etaStopwatch.Elapsed.TotalSeconds / d;
                                    var remain = TimeSpan.FromSeconds(avgSec * (t - d));
                                    var eta = d >= 2
                                        ? $" · 预计剩余 {(remain.TotalHours >= 1 ? remain.ToString(@"h\:mm\:ss") : remain.ToString(@"mm\:ss"))}"
                                        : " · 预计剩余 估算中…";
                                    ProgressText.Text = $"{d}/{t}{eta}";
                                }
                                _etaLastDone = d;
                            }
                        }
                    }
                    else if (line == "done")
                    {
                        Progress.Value = 100;
                        ProgressText.Text = "完成";
                    }
                    else if (line.EndsWith(" done"))
                    {
                        // 引擎成功行："<输入路径> -> <输出路径> done"（工单 17 起在 stdout，UTF-8）
                        var body = line[..^5];
                        var outPath = body.Split(" -> ")[^1];
                        Log("✔ 成功：" + Path.GetFileName(outPath.Trim()));
                    }
                    else
                    {
                        Log(line);
                    }
                });
            },
            line =>
            {
                Dispatcher.Invoke(() =>
                {
                    if (line.StartsWith("inference failed: ") || line.StartsWith("decode image failed: ")
                        || line.StartsWith("encode image failed: "))
                        Log("✘ 失败：" + line[(line.IndexOf(':') + 2)..]);
                    else
                        Log(line);
                });
            }));

        StartButton.IsEnabled = true;
        _running = null;
        _etaStopwatch.Stop();

        // 工单 15：异常退出码（如 0xC0000005）翻译为崩溃提示
        var summary = exitCode switch
        {
            0 => "处理完成",
            1 => "失败：参数错误",
            2 => "失败：模型或推理错误",
            3 => "失败：文件读取/写入错误",
            _ => $"失败：引擎异常崩溃（退出码 {exitCode}）"
        };
        Log($"引擎退出码 {exitCode} —— {summary}");
        MessageBox.Show(summary, exitCode == 0 ? "完成" : "出错");
    }

    // 工单 17：日志为可复制、自动换行的只读文本
    private void Log(string text)
    {
        LogBox.AppendText(text + Environment.NewLine);
        LogBox.ScrollToEnd();
    }

    // ---- 工单 14：退出时保存设置 ----
    private void OnClosing(object sender, CancelEventArgs e)
    {
        if (_models.Count == 0 || ModelBox.SelectedIndex < 0)
            return;
        var m = _models[ModelBox.SelectedIndex];

        var s = new SettingsStore
        {
            ModelId = m.Id,
            ScaleMode = ModeWidth.IsChecked == true ? "width" : ModeHeight.IsChecked == true ? "height" : "ratio",
            // 仅写入合法值；非法值不写（恢复时按默认处理）
            Scale = double.TryParse(ScaleBox.SelectedItem?.ToString()?.TrimEnd('x'), out var sc) ? (int)Math.Round(sc) : 0,
            ScaleWidth = int.TryParse(WidthBox.Text, out var w) && w > 0 ? w : 0,
            ScaleHeight = int.TryParse(HeightBox.Text, out var h) && h > 0 ? h : 0,
            OutputExt = ((ComboBoxItem)FormatBox.SelectedItem).Content.ToString()?.ToLower() ?? "jpg",
            OutputQuality = (int)QualitySlider.Value,
        };
        SettingsStore.Save(s);
    }
}

// ---- 工单 14：setting.ini 读写（exe 同目录，Windows ini 风格，对齐 waifu2x-caffe） ----
public class SettingsStore
{
    public string ModelId = "";
    public string ScaleMode = "ratio"; // ratio | width | height
    public int Scale;                  // 倍率模式的倍数值（如 2）；0 = 无记录
    public int ScaleWidth;             // 指定宽值；0 = 无记录
    public int ScaleHeight;
    public string OutputExt = "jpg";
    public int OutputQuality = -1;     // -1 = 无记录

    private static string SettingsPath => Path.Combine(AppContext.BaseDirectory, "setting.ini");

    public static SettingsStore Load()
    {
        var s = new SettingsStore();
        try
        {
            if (!File.Exists(SettingsPath))
                return s;
            var map = new Dictionary<string, string>();
            foreach (var raw in File.ReadLines(SettingsPath))
            {
                var line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("[") || line.StartsWith("#") || line.StartsWith(";"))
                    continue;
                var eq = line.IndexOf('=');
                if (eq <= 0) continue;
                map[line[..eq].Trim()] = line[(eq + 1)..].Trim();
            }

            // 逐项校验，非法值静默回退默认（grilling Q5 决议）
            s.ModelId = map.TryGetValue("LastModel", out var v) ? v : "";
            s.ScaleMode = map.TryGetValue("LastScaleMode", out v) && v is "ratio" or "width" or "height" ? v : "ratio";
            s.Scale = TryPositiveInt(map, "LastScale");
            s.ScaleWidth = TryPositiveInt(map, "LastScaleWidth");
            s.ScaleHeight = TryPositiveInt(map, "LastScaleHeight");
            s.OutputExt = map.TryGetValue("LastOutputExt", out v) && v is "jpg" or "png" or "webp" ? v : "jpg";
            s.OutputQuality = map.TryGetValue("LastOutputQuality", out v) && int.TryParse(v, out var q) ? q : -1;
        }
        catch
        {
            // 文件损坏/不可读 → 等同首次运行（grilling Q5 决议：静默回退）
        }
        return s;
    }

    private static int TryPositiveInt(Dictionary<string, string> map, string key)
        => map.TryGetValue(key, out var v) && int.TryParse(v, out var n) && n > 0 ? n : 0;

    public static void Save(SettingsStore s)
    {
        try
        {
            var sb = new StringBuilder("[Setting]").AppendLine();
            sb.AppendLine($"LastModel={s.ModelId}");
            sb.AppendLine($"LastScaleMode={s.ScaleMode}");
            sb.AppendLine($"LastScale={s.Scale}");
            sb.AppendLine($"LastScaleWidth={s.ScaleWidth}");
            sb.AppendLine($"LastScaleHeight={s.ScaleHeight}");
            sb.AppendLine($"LastOutputExt={s.OutputExt}");
            sb.AppendLine($"LastOutputQuality={s.OutputQuality}");
            File.WriteAllText(SettingsPath, sb.ToString(), new UTF8Encoding(false));
        }
        catch
        {
            // 目录只读等场景：静默放弃持久化（grilling Q1 决议）
        }
    }
}

public static class EngineClient
{
    public static List<ModelEntry> ParseManifest(string path)
    {
        var list = new List<ModelEntry>();
        if (!File.Exists(path)) return list;

        ModelEntry cur = null;
        foreach (var raw in File.ReadLines(path))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line.StartsWith("#")) continue;
            var sp = line.IndexOf(' ');
            if (sp <= 0) continue;
            var key = line[..sp];
            var val = line[(sp + 1)..].Trim();

            switch (key)
            {
                case "model":
                    cur = new ModelEntry { Id = val };
                    list.Add(cur);
                    break;
                case "display" when cur != null: cur.Display = val; break;
                case "group" when cur != null: cur.Group = val; break;
                case "arch" when cur != null: cur.Arch = val; break;
                case "dir" when cur != null: cur.Dir = val; break;
                case "in" when cur != null: cur.InBlob = val; break;
                case "out" when cur != null: cur.OutBlob = val; break;
                case "tileauto" when cur != null: cur.TileAuto = val; break;
                case "scale" when cur != null:
                    if (int.TryParse(val, out var s)) cur.Scales.Add(s);
                    break;
                case "prepad" when cur != null:
                {
                    var sp2 = val.IndexOf(' ');
                    if (sp2 <= 0) break;
                    var sc = int.Parse(val[..sp2]);
                    var pp = int.Parse(val[(sp2 + 1)..]);
                    cur.Prepad[sc] = pp;
                    break;
                }
                case "denoise" when cur != null:
                {
                    var sp2 = val.IndexOf(' ');
                    if (sp2 <= 0) break;
                    var lvl = val[..sp2] switch
                    {
                        "none" => 0, "low" => 1, "mid" => 2, "high" => 3, _ => -1
                    };
                    if (lvl >= 0) cur.Denoise[lvl] = val[(sp2 + 1)..];
                    break;
                }
            }
        }
        return list;
    }

    public static int Run(string enginePath, string workDir, string args,
                          Action<string> onStdoutLine, Action<string> onStderrLine)
    {
        var psi = new ProcessStartInfo
        {
            FileName = enginePath,
            Arguments = args,
            WorkingDirectory = workDir,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };

        using var process = new Process { StartInfo = psi };
        process.OutputDataReceived += (_, e) => { if (e.Data != null) onStdoutLine(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data != null) onStderrLine(e.Data); };

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        process.WaitForExit();

        return process.ExitCode;
    }
}
