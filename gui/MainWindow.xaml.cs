using System.Diagnostics;
using System.IO;
using System.Media;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
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
        // 工单 31：标题带版本号（唯一来源 csproj <Version>，发版只改一处）
        var ver = typeof(MainWindow).Assembly.GetName().Version;
        Title = $"Image-Upscale 图像超分工具 v{ver?.ToString(3) ?? "?"}";
        // 工单 32：窗口/任务栏图标（exe 文件图标见 csproj ApplicationIcon，同一资源）
        Icon = BitmapFrame.Create(new Uri("pack://application:,,,/assets/app.ico", UriKind.Absolute));
        Loaded += OnLoaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        // 工单 27：引擎为进程内 iu_engine.dll；models 目录由 GUI 定位（单一定义来源），显式传参
        if (!LocateModels(out _modelsDir))
        {
            Log("错误：未找到 models 目录（应与 ImageUpscale.exe 同目录，开发布局在仓库根）");
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
        // 工单 25：恢复窗口几何（尺寸 → 位置 → 最大化）
        RestoreWindowBounds(s);

        Log($"引擎就绪，已加载 {_models.Count} 个模型");  // 工单 33：启动完成后日志只此一条
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

    // ---- 工单 25：恢复窗口几何（逐项校验，与 setting.ini 其余项同款静默回退语义）----
    private void RestoreWindowBounds(SettingsStore s)
    {
        // 尺寸：低于最小尺寸的记录不采用
        if (s.WindowWidth >= MinWidth && s.WindowHeight >= MinHeight)
        {
            Width = s.WindowWidth;
            Height = s.WindowHeight;
        }

        // 位置：与虚拟屏幕有交集且未超出屏幕才采用（拔显示器/改分辨率防丢窗口），否则保持系统默认位
        if (s.WindowLeft != int.MinValue && s.WindowTop != int.MinValue)
        {
            var vs = new Rect(SystemParameters.VirtualScreenLeft, SystemParameters.VirtualScreenTop,
                              SystemParameters.VirtualScreenWidth, SystemParameters.VirtualScreenHeight);
            var wr = new Rect(s.WindowLeft, s.WindowTop, Math.Max(Width, MinWidth), Math.Max(Height, MinHeight));
            if (wr.Left >= vs.Left && wr.Top >= vs.Top && wr.Right <= vs.Right && wr.Bottom <= vs.Bottom)
            {
                Left = s.WindowLeft;
                Top = s.WindowTop;
            }
        }

        // 最大化：恢复尺寸/位置后再置状态（最大化时 Left/Top 不可信，还原态坐标已先行设置）
        if (s.WindowMaximized == 1)
            WindowState = WindowState.Maximized;
    }

    // 工单 27：models 目录由 GUI 定位（单一定义来源，lessons §1.4），随后显式传 --models-dir 给引擎
    // dist 布局：models 与 ImageUpscale.exe 同目录；开发布局：从 bin 输出向上回溯至仓库根
    private static bool LocateModels(out string modelsDir)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (var i = 0; i < 8 && dir != null; i++, dir = dir.Parent)
        {
            var cand = Path.Combine(dir.FullName, "models");
            if (File.Exists(Path.Combine(cand, "manifest.conf")))
            {
                modelsDir = cand;
                return true;
            }
        }
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
        // 工单 27：参数走数组（P/Invoke wchar_t**），无需引号转义；--models-dir 由 GUI 显式传入
        var args = new List<string> { "-i", input, "-m", m.Id, "--models-dir", _modelsDir };

        if (ModeScale.IsChecked == true)
        {
            if (ScaleBox.SelectedItem == null) { MessageBox.Show("请选择倍率", "提示"); return; }
            args.Add("-s");
            args.Add(ScaleBox.SelectedItem.ToString());
        }
        else if (ModeWidth.IsChecked == true)
        {
            if (!int.TryParse(WidthBox.Text, out var w) || w <= 0) { MessageBox.Show("请输入有效的目标宽度", "提示"); return; }
            args.Add("--width");
            args.Add(w.ToString());
        }
        else
        {
            if (!int.TryParse(HeightBox.Text, out var h) || h <= 0) { MessageBox.Show("请输入有效的目标高度", "提示"); return; }
            args.Add("--height");
            args.Add(h.ToString());
        }

        // 降噪：自动 → auto；无 → none；低/中/高 → low/mid/high（工单 22/23/24）
        var dSel = DenoiseBox.SelectedIndex;
        args.Add("--denoise");
        if (dSel == 0) args.Add("auto");
        else if (dSel == 1) args.Add("none");
        else args.Add(dSel == 2 ? "low" : dSel == 3 ? "mid" : "high");

        var fmt = ((ComboBoxItem)FormatBox.SelectedItem).Content.ToString();
        args.Add("-f");
        args.Add(fmt.ToLower());
        if (fmt != "PNG")
        {
            args.Add("-q");
            args.Add(((int)QualitySlider.Value).ToString());
        }
        args.Add("-v"); // 逐文件明细（stderr）

        Log($"开始：{Path.GetFileName(input)}（{m.Display}）");

        StartButton.IsEnabled = false;
        Progress.Value = 0;
        ProgressText.Text = "";
        LogBox.Clear();
        _etaStopwatch.Restart();
        _etaLastDone = 0;

        var exitCode = await Task.Run(() => EngineClient.Run(
            args.ToArray(),
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
        // 工单 26：任务完成不弹窗，仅声音提示（成功 Asterisk / 失败 Exclamation）；汇总在日志区
        if (exitCode == 0)
            SystemSounds.Asterisk.Play();
        else
            SystemSounds.Exclamation.Play();
    }

    // 工单 17：日志为可复制、自动换行的只读文本
    private void Log(string text)
    {
        LogBox.AppendText(text + Environment.NewLine);
        LogBox.ScrollToEnd();
    }

    // ---- 工单 14 + 25：退出时保存设置（含窗口几何）----
    private void OnClosing(object sender, CancelEventArgs e)
    {
        // 从已存设置出发：引擎缺失等场景读不到模型项时，旧值不丢（逐项覆盖）
        var s = SettingsStore.Load();

        if (_models.Count > 0 && ModelBox.SelectedIndex >= 0)
        {
            var m = _models[ModelBox.SelectedIndex];
            s.ModelId = m.Id;
            s.ScaleMode = ModeWidth.IsChecked == true ? "width" : ModeHeight.IsChecked == true ? "height" : "ratio";
            // 仅写入合法值；非法值不写（恢复时按默认处理）
            s.Scale = double.TryParse(ScaleBox.SelectedItem?.ToString()?.TrimEnd('x'), out var sc) ? (int)Math.Round(sc) : 0;
            s.ScaleWidth = int.TryParse(WidthBox.Text, out var w) && w > 0 ? w : 0;
            s.ScaleHeight = int.TryParse(HeightBox.Text, out var h) && h > 0 ? h : 0;
            s.OutputExt = ((ComboBoxItem)FormatBox.SelectedItem).Content.ToString()?.ToLower() ?? "jpg";
            s.OutputQuality = (int)QualitySlider.Value;
        }

        // 工单 25：窗口几何 —— 最大化/最小化时记 RestoreBounds（还原态坐标），否则记当前值
        var wb = WindowState == WindowState.Maximized || WindowState == WindowState.Minimized
            ? RestoreBounds
            : new Rect(Left, Top, Width, Height);
        s.WindowLeft = double.IsNaN(wb.Left) ? int.MinValue : (int)Math.Round(wb.Left);
        s.WindowTop = double.IsNaN(wb.Top) ? int.MinValue : (int)Math.Round(wb.Top);
        s.WindowWidth = (int)Math.Round(wb.Width);
        s.WindowHeight = (int)Math.Round(wb.Height);
        s.WindowMaximized = WindowState == WindowState.Maximized ? 1 : 0;

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
    // 工单 25：窗口几何（MinValue/0 = 无记录）
    public int WindowLeft = int.MinValue;
    public int WindowTop = int.MinValue;
    public int WindowWidth;
    public int WindowHeight;
    public int WindowMaximized;        // 1 = 上次关闭时最大化

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

            // 工单 25：窗口几何
            s.WindowLeft = map.TryGetValue("LastWindowLeft", out v) && int.TryParse(v, out var nl) ? nl : int.MinValue;
            s.WindowTop = map.TryGetValue("LastWindowTop", out v) && int.TryParse(v, out var nt) ? nt : int.MinValue;
            s.WindowWidth = TryPositiveInt(map, "LastWindowWidth");
            s.WindowHeight = TryPositiveInt(map, "LastWindowHeight");
            s.WindowMaximized = map.TryGetValue("LastWindowMaximized", out v) && v == "1" ? 1 : 0;
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
            // 工单 25：窗口几何
            sb.AppendLine($"LastWindowLeft={s.WindowLeft}");
            sb.AppendLine($"LastWindowTop={s.WindowTop}");
            sb.AppendLine($"LastWindowWidth={s.WindowWidth}");
            sb.AppendLine($"LastWindowHeight={s.WindowHeight}");
            sb.AppendLine($"LastWindowMaximized={s.WindowMaximized}");
            File.WriteAllText(SettingsPath, sb.ToString(), new UTF8Encoding(false));
        }
        catch
        {
            // 目录只读等场景：静默放弃持久化（grilling Q1 决议）
        }
    }
}

// ---- 工单 27：iu_engine.dll 导入面（C API 见 engine/src/engine_api.h）----
// 单文件发布时该 DLL 由打包器收编，启动时自动解压至 %TEMP%\.net 后加载
internal static class EngineApi
{
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void LineCb(IntPtr lineUtf8, IntPtr user);

    [DllImport("iu_engine", CallingConvention = CallingConvention.Cdecl)]
    public static extern int iu_run(int argc,
        [MarshalAs(UnmanagedType.LPArray, ArraySubType = UnmanagedType.LPWStr)] string[] argv,
        LineCb outCb, LineCb errCb, IntPtr user);
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

    // ---- 工单 27：引擎 P/Invoke（进程内调用），行协议与进程版字节一致 ----
    public static int Run(string[] args, Action<string> onStdoutLine, Action<string> onStderrLine)
    {
        // 引擎回调行为 UTF-8 且带结尾换行；去尾后空行不透传。回调委托在同步调用期内由托管栈根持有，无 GC 风险
        var outCb = new EngineApi.LineCb((IntPtr p, IntPtr _) =>
        {
            var s = CleanLine(p);
            if (s.Length > 0) onStdoutLine(s);
        });
        var errCb = new EngineApi.LineCb((IntPtr p, IntPtr _) =>
        {
            var s = CleanLine(p);
            if (s.Length > 0) onStderrLine(s);
        });

        var argv = new string[args.Length + 1];
        argv[0] = "ImageUpscale"; // 占位，引擎解析从 argv[1] 开始
        Array.Copy(args, 0, argv, 1, args.Length);

        try
        {
            return EngineApi.iu_run(argv.Length, argv, outCb, errCb, IntPtr.Zero);
        }
        catch (DllNotFoundException)
        {
            onStderrLine("错误：未找到 iu_engine.dll（应与 ImageUpscale.exe 同目录分发）");
            return -1;
        }
        catch (EntryPointNotFoundException)
        {
            onStderrLine("错误：iu_engine.dll 版本不匹配（缺少 iu_run 导出）");
            return -1;
        }
    }

    private static string CleanLine(IntPtr p)
        => System.Runtime.InteropServices.Marshal.PtrToStringUTF8(p)?.TrimEnd('\r', '\n') ?? "";
}
