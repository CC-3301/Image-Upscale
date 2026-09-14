using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
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
}

public partial class MainWindow : Window
{
    private string _enginePath;
    private string _modelsDir;
    private List<ModelEntry> _models = new();
    private Process _running;

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

        foreach (var m in _models)
            ModelBox.Items.Add(m.Display);
        ModelBox.SelectedIndex = 0;
        Log($"引擎就绪：{_enginePath}");
        Log($"已加载 {_models.Count} 个模型");
    }

    private static bool LocateEngine(out string enginePath, out string modelsDir)
    {
        var exeDir = AppContext.BaseDirectory;
        foreach (var cand in new[]
                 {
                     exeDir,
                     Path.Combine(exeDir, "..", "bld"),
                     Path.Combine(exeDir, "..", "..", "bld"),
                     Path.Combine(exeDir, "..", "..", "..", "bld"),
                     Path.Combine(exeDir, "..", "..", "..", "..", "bld"),
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
        ModelGroupText.Text = $"类型：{m.Group}　架构：{m.Arch}";

        // 倍率选项随模型原生倍数
        ScaleBox.Items.Clear();
        foreach (var s in m.Scales)
            ScaleBox.Items.Add($"{s}.0x");
        ScaleBox.SelectedIndex = 0;

        // 降噪可用性随模型能力（工单 03/06）
        DenoiseBox.Items.Clear();
        DenoiseBox.Items.Add("AUTO");
        DenoiseBox.Items.Add("无");
        if (m.Denoise.ContainsKey(1)) DenoiseBox.Items.Add("低");
        if (m.Denoise.ContainsKey(2)) DenoiseBox.Items.Add("中");
        if (m.Denoise.ContainsKey(3)) DenoiseBox.Items.Add("高");
        DenoiseBox.SelectedIndex = 1; // 无
        DenoiseBox.IsEnabled = m.Denoise.Count > 1 || m.Denoise.ContainsKey(0);
    }

    private void OnQualityChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (QualityValue != null)
            QualityValue.Text = ((int)e.NewValue).ToString();
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

    private void OnDragOver(object sender, DragEventArgs e)
    {
        e.Effects = e.Data.GetDataPresent(DataFormats.FileDrop) ? DragDropEffects.Copy : DragDropEffects.None;
        e.Handled = true;
    }

    private void OnDrop(object sender, DragEventArgs e)
    {
        if (e.Data.GetData(DataFormats.FileDrop) is string[] files && files.Length > 0)
            InputBox.Text = files[0];
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

        // 降噪：AUTO 哨兵 → --denoise auto；无 → none；低/中/高 → low/mid/high
        var dSel = DenoiseBox.SelectedIndex;
        if (dSel == 0) args.Append(" --denoise auto");
        else if (dSel == 1) args.Append(" --denoise none");
        else args.Append(" --denoise ").Append(dSel == 2 ? "low" : dSel == 3 ? "mid" : "high");

        var fmt = ((ComboBoxItem)FormatBox.SelectedItem).Content.ToString();
        args.Append(" -f ").Append(fmt.ToLower());
        if (fmt != "PNG")
            args.Append(" -q ").Append((int)QualitySlider.Value);
        args.Append(" -v"); // 逐文件明细（工单 08 汇总）

        Log($"开始：{Path.GetFileName(input)}（{m.Display}）");

        StartButton.IsEnabled = false;
        Progress.Value = 0;
        ProgressText.Text = "";
        LogList.Items.Clear();

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
                            ProgressText.Text = $"{d}/{t}";
                        }
                    }
                    else if (line == "done")
                    {
                        Progress.Value = 100;
                        ProgressText.Text = "完成";
                    }
                    else if (line.EndsWith(" done"))
                    {
                        var src = line[..^5];
                        var name = Path.GetFileName(src.Trim());
                        Log("✔ 成功：" + name);
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

        var summary = exitCode switch
        {
            0 => "处理完成",
            1 => "失败：参数错误",
            2 => "失败：模型或推理错误",
            3 => "失败：文件读取/写入错误",
            _ => $"失败（退出码 {exitCode}）"
        };
        Log($"引擎退出码 {exitCode} —— {summary}");
        MessageBox.Show(summary, exitCode == 0 ? "完成" : "出错");
    }

    private void Log(string text)
    {
        LogList.Items.Add(text);
        if (LogList.Items.Count > 0)
            LogList.ScrollIntoView(LogList.Items[^1]);
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
