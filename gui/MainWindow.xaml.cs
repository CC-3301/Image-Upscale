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
    public bool SupportsDenoise => DenoiseLevels.Any(l => l > 0);

    // 工单 49：四档齐备（无/低/中/高）= AUTO 的前提（引擎侧同样拒绝不连续档位，工单 44），
    // 也是降噪记忆分槽的判据：齐备档位的模型共用全局槽，不齐的各自独立槽。
    // 四档含「无」：清单只声明 低/中/高 的导入模型给「自动」会被引擎拒（退出码 1）
    public bool DenoiseComplete => Denoise.ContainsKey(0) && Denoise.ContainsKey(1)
        && Denoise.ContainsKey(2) && Denoise.ContainsKey(3);

    // 工单 49：「本模型有哪些降噪档位」的**单一定义来源**（升序，自动 = -1 在首位）——
    // 界面项构造、记忆值可用性校验、默认档三处都经它，规则只写在这里
    public IEnumerable<int> DenoiseLevels => Enumerable.Range(-1, 5).Where(IsDenoiseLevelAvailable);

    // 自动档要求四档齐备（与引擎侧同款）；「无」恒可用（不支持降噪的模型唯一项，工单 23）；
    // 低/中/高 按清单登记
    public bool IsDenoiseLevelAvailable(int level) => level switch
    {
        -1 => DenoiseComplete,
        0 => true,
        _ => Denoise.ContainsKey(level)
    };

    // 工单 49：无记忆/记忆不可用时的默认档（结果必在 DenoiseLevels 内）——
    // 不支持降噪 → 「无」；四档齐备 → 「自动」；不齐 → 最高可用档（realcugan-pro = 无/高 → 「高」）
    public int DefaultDenoiseLevel => !SupportsDenoise ? 0
        : DenoiseComplete ? -1 : DenoiseLevels.Where(l => l >= 0).Max();
}

public partial class MainWindow : Window
{
    private string _modelsDir;
    private List<ModelEntry> _models = new();
    // 并发保护就是 StartButton.IsEnabled（工单 27 后引擎在进程内同步跑，没有可等待的 Process 对象）

    // 工单 20：ETA 估算
    private readonly Stopwatch _etaStopwatch = new();
    private int _etaLastDone;

    // 工单 13：滑条 ↔ 输入框同步的重入保护
    private int _quality = 90;

    // 工单 41：降噪下拉项 ↔ 引擎档位的登记表（自动 = -1），与 DenoiseBox.Items 一一对应
    // （下拉项按模型能力动态增删，缺档位的模型上“序号”不再等于“档位”）
    private readonly List<int> _denoiseLevels = new();

    // 工单 49：降噪档位记忆（内存态，退出时随 OnClosing 一次性落盘）——
    // 档位齐备的模型共用 _denoiseGlobal，档位不齐的模型各自写 _denoiseByModel；
    // 程序化设置 SelectedIndex（恢复记忆/回退默认）由 _suppressDenoiseWrite 拦住，不写回记忆
    private int _denoiseGlobal = -1;
    private readonly Dictionary<string, int> _denoiseByModel = new();
    private bool _suppressDenoiseWrite;

    // 工单 42：降采样滤镜的 token ↔ 标签表已移到 SettingsStore（单一定义来源）——
    // 原先定义在此处、由 SettingsStore 反向引用 MainWindow，依赖方向是颠倒的

    // 工单 51：产物后缀段开关的用户选择（true = 开）。灰置状态下的显示值（「开」）不是用户选择，
    // 故另存一份记忆值；setting.ini 键 LastAddSuffix（1 = 开，与 v0.2.8 现状一致）
    private bool _addSuffix = true;
    // 程序化切换（灰置跟随 / 恢复记忆值）不写回 _addSuffix，否则文件夹输入时会把灰置值当成用户选择
    private bool _suppressAddSuffixWrite;

    public MainWindow()
    {
        InitializeComponent();
        // 工单 31：标题带版本号（唯一来源 csproj <Version>，发版只改一处）
        var ver = typeof(MainWindow).Assembly.GetName().Version;
        Title = $"ImageUpscale 图像超分工具 v{ver?.ToString(3) ?? "?"}";
        // 工单 32：窗口/任务栏图标（exe 文件图标见 csproj ApplicationIcon，同一资源）
        Icon = BitmapFrame.Create(new Uri("pack://application:,,,/assets/app.ico", UriKind.Absolute));
        // 工单 25/37：几何恢复必须在显示之前（Loaded 时窗口已渲染，先闪默认位再跳走）；
        // 引擎定位与其余设置恢复仍在 OnLoaded
        // 工单 42：降采样下拉（与模型无关的固定档位表；默认项 = Lanczos）
        foreach (var label in SettingsStore.DownFilterLabels)
            DownFilterBox.Items.Add(label);
        DownFilterBox.SelectedIndex = 0;
        // 工单 51：后缀开关（项由 SettingsStore.AddSuffixLabels 单一来源填充；与模型无关，
        // 故记忆值在构造函数这里读就定下来 —— OnLoaded/RestoreSettings 在 models 缺失时会早退，
        // 若只在那里赋值，“关闭时写回”会拿初值把用户存的「关」抹成「开」）
        foreach (var label in SettingsStore.AddSuffixLabels)
            AddSuffixBox.Items.Add(label);
        var s = SettingsStore.Load();
        _addSuffix = s.AddSuffix;
        // 工单 49：降噪记忆初值 —— 与后缀开关同理（RestoreSettings 在 models 缺失时早退，
        // 若只在那里读，“退出时写回”会拿初值把用户存的档位抹成默认）
        _denoiseGlobal = s.Denoise;
        foreach (var kv in s.DenoiseByModel)
            _denoiseByModel[kv.Key] = kv.Value;
        UpdateAddSuffixState(); // 输入框还是空 → 非文件输入，显示「开」并灰置
        RestoreWindowBounds(s);
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
        // 工单 37：窗口几何已改在构造函数显示前恢复，此处不再重复

        // 工单 33：启动完成后日志只此一条；工单 52：文案不带「引擎」二字，勿再「补齐」
        Log($"就绪，已加载 {_models.Count} 个模型");
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

        // 工单 42：降采样滤镜（未记录/非法值 → 默认 Lanczos）
        var dfIdx = Array.IndexOf(SettingsStore.DownFilterTokens, s.DownFilter);
        DownFilterBox.SelectedIndex = dfIdx >= 0 ? dfIdx : 0;

        // 质量：真源为输入框（v0.2.4 去滑条），非法存储值回退默认 90
        var q = (s.OutputQuality >= 0 && s.OutputQuality <= 100) ? s.OutputQuality : 90;
        _quality = q;
        QualityInput.Text = q.ToString();

        // 工单 51：后缀开关的记忆值已在构造函数读过（与模型可用性无关），此处不重复赋值
    }

    // 工单 18：日志区高度上限 = 窗口可用高度的 60%（下限由 XAML MinHeight 保证；
    //「开始」行的下限由 StartRow 的 MinHeight=42 保证，拖到极限不会把按钮挤掉）
    private void OnWindowSizeChanged(object sender, SizeChangedEventArgs e)
    {
        LogRow.MaxHeight = Math.Max(80, e.NewSize.Height * 0.6);
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

        // 位置：与虚拟屏幕有交集且未超出屏幕才采用（拔显示器/改分辨率防丢窗口）；
        // 否则回退为屏幕居中（工单 25 的「回退居中」，原先保持系统默认位）
        bool positionRestored = false;
        if (s.WindowLeft != int.MinValue && s.WindowTop != int.MinValue)
        {
            var vs = new Rect(SystemParameters.VirtualScreenLeft, SystemParameters.VirtualScreenTop,
                              SystemParameters.VirtualScreenWidth, SystemParameters.VirtualScreenHeight);
            var wr = new Rect(s.WindowLeft, s.WindowTop, Math.Max(Width, MinWidth), Math.Max(Height, MinHeight));
            if (wr.Left >= vs.Left && wr.Top >= vs.Top && wr.Right <= vs.Right && wr.Bottom <= vs.Bottom)
            {
                Left = s.WindowLeft;
                Top = s.WindowTop;
                positionRestored = true;
            }
        }
        if (!positionRestored)
            WindowStartupLocation = System.Windows.WindowStartupLocation.CenterScreen;

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

        // 降噪档位（工单 22 中文文案；工单 23 能力判据；工单 24 默认档；工单 49 默认档修订与记忆）
        // 工单 41：项与引擎档位同步登记，构造命令行时按登记值取，不能再用序号推档位
        // 工单 44：AUTO 需要 无/低/中/高 四档齐备（引擎侧同样拒绝不连续档位），
        //          故 realcugan-pro 这类只有 无/高 的模型不提供「自动」项
        // 工单 49：档位齐备 → 默认「自动」；不齐 → 默认最高可用档（pro = 无/高 → 「高」）；
        //          不支持降噪 → 固定「无」（工单 23 判据不变）
        _suppressDenoiseWrite = true;
        DenoiseBox.Items.Clear();
        _denoiseLevels.Clear();
        foreach (var lvl in m.DenoiseLevels)
        {
            DenoiseBox.Items.Add(SettingsStore.DenoiseLabelOfLevel(lvl));
            _denoiseLevels.Add(lvl);
        }
        DenoiseHint.Visibility = m.SupportsDenoise ? Visibility.Collapsed : Visibility.Visible;
        DenoiseBox.IsEnabled = m.SupportsDenoise;
        // 记忆值只在当前模型的可用集合内才采用（齐备读全局槽 / 不齐读自己的独立槽），
        // 否则回退本模型的默认档（例：全局记忆「低」→ 切到只有 无/高 的 pro 落「高」）
        var remembered = m.DenoiseComplete
            ? _denoiseGlobal
            : _denoiseByModel.TryGetValue(m.Id, out var saved) ? saved : m.DefaultDenoiseLevel;
        var denoiseIdx = _denoiseLevels.IndexOf(remembered);
        if (denoiseIdx < 0)
        {
            // 记忆不可用（清单档位变更 / 手改出的非法值）→ 回退默认档，并把**本模型正在用的那个槽**
            // 规范化为生效值，下次落盘即写回合法值（否则界面恒默认、ini 恒旧值）。只改本槽，
            // 其余槽（如齐备模型共用的全局槽）原样保留；此处仍被抑制标志包着，不走用户选择写回
            remembered = m.DefaultDenoiseLevel;
            denoiseIdx = _denoiseLevels.IndexOf(remembered);
            if (m.DenoiseComplete)
                _denoiseGlobal = remembered;
            else if (m.SupportsDenoise)
                _denoiseByModel[m.Id] = remembered;
        }
        DenoiseBox.SelectedIndex = denoiseIdx;
        _suppressDenoiseWrite = false;
    }

    // 工单 49：选档写回记忆槽（齐备档位 → 全局槽；不齐档位 → 各自独立槽），退出时随 OnClosing 落盘；
    // OnModelChanged 内部的程序化设置由 _suppressDenoiseWrite 拦掉，否则恢复记忆时的回退默认会改写记忆
    private void OnDenoiseChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressDenoiseWrite || _models.Count == 0 || ModelBox.SelectedIndex < 0)
            return;
        var dSel = DenoiseBox.SelectedIndex;
        if (dSel < 0 || dSel >= _denoiseLevels.Count)
            return;
        var m = _models[ModelBox.SelectedIndex];
        if (m.DenoiseComplete)
            _denoiseGlobal = _denoiseLevels[dSel];
        else if (m.SupportsDenoise)
            _denoiseByModel[m.Id] = _denoiseLevels[dSel];
    }

    // ---- 工单 13 → v0.2.4：质量去滑条，真源为 _quality，输入框失焦规整 ----
    private void OnQualityInputChanged(object sender, TextChangedEventArgs e)
    {
        if (int.TryParse(QualityInput.Text, out var q))
            _quality = Math.Clamp(q, 0, 100);
    }

    // 非法输入（非数字/超界残留文本）在失焦时回退为最后有效值
    private void OnQualityInputLostFocus(object sender, RoutedEventArgs e)
    {
        if (int.TryParse(QualityInput.Text, out var q))
        {
            _quality = Math.Clamp(q, 0, 100);
            QualityInput.Text = _quality.ToString(); // 规整（如 "007"→"7"）
        }
        else
        {
            QualityInput.Text = _quality.ToString();
        }
    }

    // ---- 工单 51：产物后缀段开关 ----
    // 只对文件输入有意义（工单 50 定案 1）：输入是文件 → 可点并显示记忆值；
    // 文件夹/空/无效路径 → 显示「开」并灰置（灰置值即实际生效值，不加提示文字）
    private void OnInputTextChanged(object sender, TextChangedEventArgs e) => UpdateAddSuffixState();

    private void UpdateAddSuffixState()
    {
        var isFile = File.Exists(InputBox.Text);
        // 显示值：文件输入 = 记忆值；文件夹/空/无效路径 = 「开」（灰置值即实际生效值）
        _suppressAddSuffixWrite = true;
        AddSuffixBox.SelectedIndex = SettingsStore.AddSuffixToIndex(isFile ? _addSuffix : true);
        _suppressAddSuffixWrite = false;
        AddSuffixBox.IsEnabled = isFile;
    }

    private void OnAddSuffixChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressAddSuffixWrite)
            return;
        _addSuffix = SettingsStore.AddSuffixFromIndex(AddSuffixBox.SelectedIndex);
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
        var m = _models[ModelBox.SelectedIndex];
        // 工单 27：参数走数组（P/Invoke wchar_t**），无需引号转义；--models-dir 由 GUI 显式传入
        var args = new List<string> { "-i", input, "-m", m.Id, "--models-dir", _modelsDir };
        // 工单 50：文件输入 + 「文件添加扩展名」关 → 产物用原文件名（不加后缀段）。
        // 文件夹输入忽略该开关；且灰置时的显示值「开」不代表记忆值，故按 File.Exists + _addSuffix 判断
        if (File.Exists(input) && !_addSuffix)
            args.Add("--no-rename");

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
        // 工单 41：按登记的档位取名（pro 只有 自动/无/高，序号 2 是“高”而非“低”）
        // 工单 49：档位 → token 走 SettingsStore 的单一定义来源表（与记忆槽、Load 校验同一份）
        var dSel = DenoiseBox.SelectedIndex;
        var dLvl = (dSel >= 0 && dSel < _denoiseLevels.Count) ? _denoiseLevels[dSel] : -1;
        args.Add("--denoise");
        args.Add(SettingsStore.DenoiseTokenOfLevel(dLvl));

        // 工单 42：降采样滤镜（只在缩小路径生效；倍率模式下引擎忽略该参数）
        args.Add("--down-filter");
        args.Add(SettingsStore.DownFilterTokenAt(DownFilterBox.SelectedIndex));

        var fmt = ((ComboBoxItem)FormatBox.SelectedItem).Content.ToString();
        args.Add("-f");
        args.Add(fmt.ToLower());
        if (fmt != "PNG")
        {
            args.Add("-q");
            args.Add(_quality.ToString());
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
                    if (line.StartsWith("refuse to overwrite input: "))
                        Log("✘ 拒绝覆盖输入文件（产物与输入同名，请把「文件添加扩展名」设为开）："
                            + Path.GetFileName(line[(line.IndexOf(':') + 2)..]));
                    else if (line.StartsWith("inference failed: ") || line.StartsWith("decode image failed: ")
                        || line.StartsWith("encode image failed: "))
                        Log("✘ 失败：" + line[(line.IndexOf(':') + 2)..]);
                    else
                        Log(line);
                });
            }));

        StartButton.IsEnabled = true;
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
            s.OutputQuality = _quality;
        }

        // 工单 42：降采样滤镜（与模型无关，引擎缺失时也照样记录）
        s.DownFilter = SettingsStore.DownFilterTokenAt(DownFilterBox.SelectedIndex);

        // 工单 51：后缀开关（同样与模型无关；写记忆值而非灰置时的显示值）
        s.AddSuffix = _addSuffix;

        // 工单 49：降噪记忆 —— 全局槽写当前值，独立槽按已加载模型清单生成（没被用户碰过的模型
        // 写其默认档，键因此在 setting.ini 里总是可见）；档位不齐但支持降噪的模型才建键，
        // 键名按 ini 语法回读（见 SettingsStore.IsDenoiseModelIdStorable）
        s.Denoise = _denoiseGlobal;
        foreach (var m in _models)
            if (m.SupportsDenoise && !m.DenoiseComplete && SettingsStore.IsDenoiseModelIdStorable(m.Id))
                s.DenoiseByModel[m.Id] = _denoiseByModel.TryGetValue(m.Id, out var lv) ? lv : m.DefaultDenoiseLevel;

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
    // 工单 42：降采样滤镜 token（lanczos/catmullrom/bicubic/box；界面 Bicubic 的核是 Mitchell-Netravali）
    public string DownFilter = "lanczos";
    // 工单 51：产物名是否带后缀段（true = 开，与 v0.2.8 现状一致；只对文件输入生效）
    public bool AddSuffix = true;
    // 工单 49：降噪档位记忆 —— Denoise 是档位齐备的模型共用的全局槽（LastDenoise；-1 = 自动）；
    // DenoiseByModel 是档位不齐的模型各自的独立槽（LastDenoise_<modelId>；无键 = 无记录 → 回退默认档）
    public int Denoise = -1;
    public Dictionary<string, int> DenoiseByModel = new();

    // 工单 42：降采样滤镜的 token ↔ 界面标签（**单一定义来源**；界面项与 setting.ini 校验共用）。
    // 注意：界面 Bicubic 的核是 Mitchell-Netravali，界面 Catmull-Rom 的核是 Catmull-Rom
    internal static readonly string[] DownFilterTokens = { "lanczos", "catmullrom", "bicubic", "box" };
    internal static readonly string[] DownFilterLabels = { "Lanczos", "Catmull-Rom", "Bicubic", "Box" };

    // 下拉当前选中项 → 引擎 token（未选中/越界回退第 0 项 Lanczos，与引擎侧以 0 为默认一致）
    internal static string DownFilterTokenAt(int selectedIndex)
        => DownFilterTokens[selectedIndex >= 0 && selectedIndex < DownFilterTokens.Length ? selectedIndex : 0];

    // 工单 51：后缀开关的项 ↔ 语义（**单一定义来源**，照 DownFilterTokens/Labels 模式；
    // 界面项由本表填充，序号 ↔ 布尔只经下面两个 helper，调项序不会静默反相）
    internal static readonly string[] AddSuffixLabels = { "开", "关" };

    // 下拉当前选中项 → 是否带后缀段（未选中/越界回退「开」= 现状，与 Load 的非法值回退一致）
    internal static bool AddSuffixFromIndex(int selectedIndex) => selectedIndex != 1;

    internal static int AddSuffixToIndex(bool addSuffix) => addSuffix ? 0 : 1;

    // 工单 49：降噪档位表（**单一定义来源**，照 DownFilterTokens/Labels 模式）——下标 = 档位 + 1
    // （0 = 自动 = -1 档 … 4 = 高 = 3 档）；界面标签、setting.ini token、引擎取值三处共用，调表不会静默错档
    internal static readonly string[] DenoiseLabels = { "自动", "无", "低", "中", "高" };
    internal static readonly string[] DenoiseTokens = { "auto", "none", "low", "mid", "high" };

    // 档位 → 下标（越界回退「自动」，与 Load 的缺键默认一致）
    private static int DenoiseIndex(int level) => level >= -1 && level <= 3 ? level + 1 : 0;

    internal static string DenoiseLabelOfLevel(int level) => DenoiseLabels[DenoiseIndex(level)];
    internal static string DenoiseTokenOfLevel(int level) => DenoiseTokens[DenoiseIndex(level)];

    // token → 档位；非法 token 返回 -2（不是合法档位，调用方据此回退默认档）
    internal static int DenoiseLevelOfToken(string token) => Array.IndexOf(DenoiseTokens, token) - 1;

    // 工单 49：独立槽的键前缀（LastDenoise_<modelId>）。键名按 ini 语法回读（行内第一个 '=' 切分、
    // 键名去首尾空白），故只在 modelId 能原样往返时才建键
    private const string DenoiseModelKeyPrefix = "LastDenoise_";

    // 工单 49：modelId 能否安全当独立槽键名（含 '=' / 换行 / 首尾空白 → 写得出读不回）。
    // Save 时跳过这类模型 → 它们的档位只在本次会话内记忆，下次启动回退默认档
    internal static bool IsDenoiseModelIdStorable(string modelId)
        => !string.IsNullOrEmpty(modelId) && modelId.Trim() == modelId
           && modelId.IndexOf('=') < 0 && modelId.IndexOf('\r') < 0 && modelId.IndexOf('\n') < 0;

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
            s.DownFilter = map.TryGetValue("LastDownFilter", out v) && Array.IndexOf(DownFilterTokens, v) >= 0 ? v : DownFilterTokens[0];
            // 工单 51：失缺/非法值静默回退默认「开」
            s.AddSuffix = map.TryGetValue("LastAddSuffix", out v) ? v != "0" : true;

            // 工单 49：降噪记忆（全局槽缺键/非法值 → 默认「自动」；独立槽的非法条目丢弃 → 该模型回退默认档）
            s.Denoise = map.TryGetValue("LastDenoise", out v) ? DenoiseLevelOfToken(v) : -1;
            if (s.Denoise < -1)
                s.Denoise = -1;
            foreach (var kv in map)
            {
                if (!kv.Key.StartsWith(DenoiseModelKeyPrefix, StringComparison.Ordinal)
                    || kv.Key.Length == DenoiseModelKeyPrefix.Length)
                    continue;
                var lvl = DenoiseLevelOfToken(kv.Value);
                if (lvl >= -1)
                    s.DenoiseByModel[kv.Key[DenoiseModelKeyPrefix.Length..]] = lvl;
            }

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
            sb.AppendLine($"LastDownFilter={s.DownFilter}");
            sb.AppendLine($"LastAddSuffix={(s.AddSuffix ? 1 : 0)}");
            // 工单 49：降噪记忆（全局槽 + 档位不齐模型各自的独立槽；键序稳定便于 diff/手改）
            sb.AppendLine($"LastDenoise={DenoiseTokenOfLevel(s.Denoise)}");
            foreach (var kv in s.DenoiseByModel.OrderBy(kv => kv.Key, StringComparer.Ordinal))
                sb.AppendLine($"{DenoiseModelKeyPrefix}{kv.Key}={DenoiseTokenOfLevel(kv.Value)}");
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
