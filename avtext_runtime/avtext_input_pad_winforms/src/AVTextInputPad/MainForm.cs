using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace AVTextInputPad;

internal sealed class MainForm : Form
{
    public const string WindowTitle = "AV Text 専用入力エディタ";

    private const int DefaultWatchIntervalMs = 1200;
    private const int DefaultSaveDelayMs = 450;
    private const string SettingsFolderName = "AVTextInputPad";
    private const string SettingsFileName = "settings.json";
    private const string LogFileName = "avtext_input_pad_winforms.log";

    private readonly TextBox _runtimeDirTextBox;
    private readonly TextBox _titleTextBox;
    private readonly TextBox _actressTextBox;
    private readonly TextBox _noTextBox;
    private readonly TextBox _resultTextBox;
    private readonly Label _statusLabel;
    private readonly Label _detailLabel;
    private readonly Label _noticeLabel;
    private readonly ProgressBar _progressBar;
    private readonly Button _convertButton;
    private readonly Button _titleOnlyButton;
    private readonly Button _noTitleButton;
    private readonly Button _copyButton;
    private readonly Button _openButton;
    private readonly Button _browseButton;
    private readonly Button _reloadButton;
    private readonly TabControl _tabControl;
    private readonly System.Windows.Forms.Timer _watchTimer;
    private readonly System.Windows.Forms.Timer _saveTimer;
    private readonly ToolTip _toolTip;

    private readonly string _settingsPath;
    private readonly string _logPath;
    private readonly Dictionary<string, FileSignature> _signatures = new(StringComparer.Ordinal);
    private readonly HashSet<string> _dirtyKeys = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _pendingExternalTexts = new(StringComparer.Ordinal);

    private RuntimePaths _runtimePaths;
    private AppSettings _settings;
    private bool _isApplyingUi;
    private bool _isRunning;

    public MainForm()
    {
        _settingsPath = Path.Combine(GetSettingsDirectory(), SettingsFileName);
        _logPath = Path.Combine(GetSettingsDirectory(), "logs", LogFileName);
        _settings = LoadSettings();
        _runtimePaths = RuntimePaths.FromBaseDirectory(_settings.RuntimeDirectory);

        Text = WindowTitle;
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(940, 520);
        AutoScaleMode = AutoScaleMode.Dpi;

        var outer = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(8),
        };
        outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        outer.RowStyles.Add(new RowStyle(SizeType.Percent, 100f));
        Controls.Add(outer);

        var runtimePanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 4,
            AutoSize = true,
        };
        runtimePanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        runtimePanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
        runtimePanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        runtimePanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        outer.Controls.Add(runtimePanel, 0, 0);

        runtimePanel.Controls.Add(new Label { Text = "ランタイム", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 0);
        _runtimeDirTextBox = new TextBox { Dock = DockStyle.Fill };
        runtimePanel.Controls.Add(_runtimeDirTextBox, 1, 0);
        _browseButton = new Button { Text = "参照", AutoSize = true };
        _reloadButton = new Button { Text = "再読込", AutoSize = true };
        runtimePanel.Controls.Add(_browseButton, 2, 0);
        runtimePanel.Controls.Add(_reloadButton, 3, 0);

        var buttonPanel = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            AutoSize = true,
            WrapContents = false,
            Margin = new Padding(0, 6, 0, 0),
        };
        outer.Controls.Add(buttonPanel, 0, 1);

        _convertButton = new Button { Text = "変換", AutoSize = true };
        _titleOnlyButton = new Button { Text = "タイトルのみ変換", AutoSize = true };
        _noTitleButton = new Button { Text = "品番連番変換", AutoSize = true };
        _copyButton = new Button { Text = "結果をコピー", AutoSize = true };
        _openButton = new Button { Text = "出力ファイルを開く", AutoSize = true };

        buttonPanel.Controls.Add(_convertButton);
        buttonPanel.Controls.Add(_titleOnlyButton);
        buttonPanel.Controls.Add(_noTitleButton);
        buttonPanel.Controls.Add(_copyButton);
        buttonPanel.Controls.Add(_openButton);
        buttonPanel.Controls.Add(new Label { Text = "品番", AutoSize = true, Padding = new Padding(8, 8, 0, 0) });
        _noTextBox = new TextBox { Width = 110 };
        buttonPanel.Controls.Add(_noTextBox);

        var statusPanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 4,
            AutoSize = true,
            Margin = new Padding(0, 6, 0, 0),
        };
        statusPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        statusPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
        statusPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50f));
        statusPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        outer.Controls.Add(statusPanel, 0, 2);

        _statusLabel = new Label { Text = "待機中", AutoSize = true, Anchor = AnchorStyles.Left };
        _detailLabel = new Label { Text = "起動準備中", AutoSize = true, Anchor = AnchorStyles.Left };
        _noticeLabel = new Label { Text = "", AutoSize = true, Anchor = AnchorStyles.Left, ForeColor = Color.FromArgb(138, 43, 6) };
        _progressBar = new ProgressBar { Style = ProgressBarStyle.Marquee, Visible = false, Width = 140, MarqueeAnimationSpeed = 20 };
        statusPanel.Controls.Add(_statusLabel, 0, 0);
        statusPanel.Controls.Add(_detailLabel, 1, 0);
        statusPanel.Controls.Add(_noticeLabel, 2, 0);
        statusPanel.Controls.Add(_progressBar, 3, 0);

        _tabControl = new TabControl { Dock = DockStyle.Fill, Margin = new Padding(0, 6, 0, 0) };
        outer.Controls.Add(_tabControl, 0, 3);

        _actressTextBox = CreateEditorTextBox();
        _titleTextBox = CreateEditorTextBox();
        _resultTextBox = CreateEditorTextBox(readOnly: true);

        _tabControl.TabPages.Add(CreateTabPage("女優", _actressTextBox));
        _tabControl.TabPages.Add(CreateTabPage("タイトル", _titleTextBox));
        _tabControl.TabPages.Add(CreateTabPage("変換結果", _resultTextBox));

        _toolTip = new ToolTip();
        _toolTip.SetToolTip(_runtimeDirTextBox, "title.txt / actress.txt / no.txt / conv_converted.txt のあるフォルダ");
        _toolTip.SetToolTip(_copyButton, "変換結果をクリップボードへ送ります");

        _watchTimer = new System.Windows.Forms.Timer { Interval = _settings.WatchIntervalMs };
        _saveTimer = new System.Windows.Forms.Timer { Interval = _settings.SaveDelayMs };

        _browseButton.Click += (_, _) => ChooseRuntimeDirectory();
        _reloadButton.Click += (_, _) => ApplyRuntimeDirectory(forceReload: true);
        _convertButton.Click += async (_, _) => await RunConversionAsync(ConversionMode.TitleAndActress);
        _titleOnlyButton.Click += async (_, _) => await RunConversionAsync(ConversionMode.TitleOnly);
        _noTitleButton.Click += async (_, _) => await RunConversionAsync(ConversionMode.NoTitle);
        _copyButton.Click += (_, _) => CopyResult();
        _openButton.Click += (_, _) => OpenOutputFile();

        _titleTextBox.TextChanged += (_, _) => MarkDirty("title");
        _actressTextBox.TextChanged += (_, _) => MarkDirty("actress");
        _noTextBox.TextChanged += (_, _) => MarkDirty("no");
        _watchTimer.Tick += (_, _) => WatchFiles();
        _saveTimer.Tick += (_, _) => FlushPendingSaves();

        Load += (_, _) => OnFormLoaded();
        FormClosing += (_, _) => PersistSettings();
    }

    private void OnFormLoaded()
    {
        RestoreWindowBounds();
        _runtimeDirTextBox.Text = _runtimePaths.BaseDirectory;
        ApplyRuntimeDirectory(forceReload: true);
        _watchTimer.Start();
    }

    private static TextBox CreateEditorTextBox(bool readOnly = false)
    {
        return new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ScrollBars = ScrollBars.Both,
            AcceptsReturn = true,
            AcceptsTab = true,
            WordWrap = true,
            ReadOnly = readOnly,
            Font = new Font("Yu Gothic UI", 10F),
        };
    }

    private static TabPage CreateTabPage(string title, Control inner)
    {
        var page = new TabPage(title);
        inner.Dock = DockStyle.Fill;
        page.Controls.Add(inner);
        return page;
    }

    private void ChooseRuntimeDirectory()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "ランタイムフォルダを選択",
            ShowNewFolderButton = false,
            InitialDirectory = Directory.Exists(_runtimeDirTextBox.Text) ? _runtimeDirTextBox.Text : GetDefaultRuntimeDirectory(),
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }

        _runtimeDirTextBox.Text = dialog.SelectedPath;
        ApplyRuntimeDirectory(forceReload: true);
    }

    private void ApplyRuntimeDirectory(bool forceReload)
    {
        var requested = (_runtimeDirTextBox.Text ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(requested))
        {
            requested = GetDefaultRuntimeDirectory();
        }

        requested = Path.GetFullPath(requested);
        if (!forceReload && string.Equals(requested, _runtimePaths.BaseDirectory, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        FlushPendingSaves();
        _pendingExternalTexts.Clear();
        _dirtyKeys.Clear();
        _runtimePaths = RuntimePaths.FromBaseDirectory(requested);
        _runtimeDirTextBox.Text = requested;
        _settings.RuntimeDirectory = requested;

        LoadAllFromDisk("ランタイム読込");
        PersistSettings();
    }

    private void LoadAllFromDisk(string reason)
    {
        LoadEditorFromDisk("title", reason);
        LoadEditorFromDisk("actress", reason);
        LoadNoFromDisk(reason);
        LoadResultFromDisk(reason);
        ValidateBatches();
        SetStatus("待機中", $"{reason} 完了");
        SetNotice(string.Empty);
    }

    private void ValidateBatches()
    {
        var missing = _runtimePaths.GetMissingBatchPaths();
        if (missing.Count == 0)
        {
            return;
        }

        SetNotice("変換 BAT が見つかりません");
        WriteLog($"missing batch: {string.Join(", ", missing)}");
    }

    private void LoadEditorFromDisk(string key, string reason)
    {
        var path = key == "title" ? _runtimePaths.TitlePath : _runtimePaths.ActressPath;
        var text = TryReadNormalized(path, key, out var encodingName);
        ApplyTextToEditor(key, text);
        _signatures[key] = FileSignature.FromPath(path);
        WriteLog($"[LOAD] key={key} encoding={encodingName} path={path} reason={reason}");
    }

    private void LoadNoFromDisk(string reason)
    {
        var text = TryReadNormalized(_runtimePaths.NoPath, "no", out var encodingName);
        ApplyTextToNo(text);
        _signatures["no"] = FileSignature.FromPath(_runtimePaths.NoPath);
        WriteLog($"[LOAD] key=no encoding={encodingName} path={_runtimePaths.NoPath} reason={reason}");
    }

    private void LoadResultFromDisk(string reason)
    {
        var text = TryReadRaw(_runtimePaths.ResultPath, out var encodingName);
        ApplyTextToResult(text);
        _signatures["result"] = FileSignature.FromPath(_runtimePaths.ResultPath);
        WriteLog($"[LOAD] key=result encoding={encodingName} path={_runtimePaths.ResultPath} reason={reason}");
    }

    private void ApplyTextToEditor(string key, string text)
    {
        var target = key == "title" ? _titleTextBox : _actressTextBox;
        _isApplyingUi = true;
        try
        {
            if (!string.Equals(target.Text, text, StringComparison.Ordinal))
            {
                target.Text = text;
            }
        }
        finally
        {
            _isApplyingUi = false;
        }
    }

    private void ApplyTextToNo(string text)
    {
        _isApplyingUi = true;
        try
        {
            if (!string.Equals(_noTextBox.Text, text, StringComparison.Ordinal))
            {
                _noTextBox.Text = text;
            }
        }
        finally
        {
            _isApplyingUi = false;
        }
    }

    private void ApplyTextToResult(string text)
    {
        _isApplyingUi = true;
        try
        {
            if (!string.Equals(_resultTextBox.Text, text, StringComparison.Ordinal))
            {
                _resultTextBox.Text = text;
            }
        }
        finally
        {
            _isApplyingUi = false;
        }
    }

    private void MarkDirty(string key)
    {
        if (_isApplyingUi || _isRunning)
        {
            return;
        }

        _dirtyKeys.Add(key);
        _saveTimer.Stop();
        _saveTimer.Start();
        SetStatus("保存待ち", $"{GetFieldLabel(key)} を編集中");
    }

    private void FlushPendingSaves()
    {
        if (_dirtyKeys.Count == 0)
        {
            return;
        }

        _saveTimer.Stop();
        foreach (var key in _dirtyKeys.ToArray())
        {
            SaveField(key);
        }
        _dirtyKeys.Clear();
        PersistSettings();
        SetStatus("待機中", "保存完了");
    }

    private void SaveField(string key)
    {
        var path = _runtimePaths.GetPathForKey(key);
        var text = GetNormalizedUiText(key);
        Directory.CreateDirectory(_runtimePaths.BaseDirectory);
        File.WriteAllText(path, text + Environment.NewLine, new UTF8Encoding(false));
        _signatures[key] = FileSignature.FromPath(path);
        WriteLog($"[SAVE] field={key} path={path}");
    }

    private string GetNormalizedUiText(string key)
    {
        var raw = key switch
        {
            "title" => _titleTextBox.Text,
            "actress" => _actressTextBox.Text,
            "no" => _noTextBox.Text,
            _ => string.Empty,
        };
        return NormalizeText(key, raw);
    }

    private void WatchFiles()
    {
        if (_isRunning)
        {
            return;
        }

        CheckExternalField("title", _runtimePaths.TitlePath, applyToResult: false);
        CheckExternalField("actress", _runtimePaths.ActressPath, applyToResult: false);
        CheckExternalField("no", _runtimePaths.NoPath, applyToResult: false);
        CheckExternalField("result", _runtimePaths.ResultPath, applyToResult: true);
    }

    private void CheckExternalField(string key, string path, bool applyToResult)
    {
        var current = FileSignature.FromPath(path);
        if (_signatures.TryGetValue(key, out var previous) && previous.Equals(current))
        {
            return;
        }

        _signatures[key] = current;
        if (applyToResult)
        {
            var resultText = TryReadRaw(path, out var encodingName);
            ApplyTextToResult(resultText);
            WriteLog($"[LOAD] key=result encoding={encodingName} path={path}");
            return;
        }

        var normalized = TryReadNormalized(path, key, out var sourceEncoding);
        var currentUi = GetNormalizedUiText(key);
        if (string.Equals(normalized, currentUi, StringComparison.Ordinal))
        {
            return;
        }

        if (_dirtyKeys.Contains(key))
        {
            _pendingExternalTexts[key] = normalized;
            SetNotice($"{GetFieldLabel(key)} に外部更新があります");
            WriteLog($"[SKIP] external change pending key={key} encoding={sourceEncoding} path={path}");
            return;
        }

        if (key == "no")
        {
            ApplyTextToNo(normalized);
        }
        else
        {
            ApplyTextToEditor(key, normalized);
        }

        _pendingExternalTexts.Remove(key);
        SetNotice(string.Empty);
        WriteLog($"[LOAD] key={key} encoding={sourceEncoding} path={path}");
    }

    private async Task RunConversionAsync(ConversionMode mode)
    {
        if (_isRunning)
        {
            return;
        }

        FlushPendingSaves();
        _isRunning = true;
        SetBusy(true);
        var sw = Stopwatch.StartNew();
        var modeLabel = mode switch
        {
            ConversionMode.TitleAndActress => "変換中",
            ConversionMode.TitleOnly => "タイトルのみ変換中",
            ConversionMode.NoTitle => "品番連番変換中",
            _ => "変換中",
        };
        SetStatus(modeLabel, $"{Path.GetFileName(_runtimePaths.GetBatchPath(mode))} を実行しています");
        SetNotice(string.Empty);

        try
        {
            var batchPath = _runtimePaths.GetBatchPath(mode);
            if (!File.Exists(batchPath))
            {
                throw new FileNotFoundException("変換 BAT が見つかりません。", batchPath);
            }

            var psi = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = $"/c \"\"{batchPath}\"\"",
                WorkingDirectory = _runtimePaths.BaseDirectory,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };

            using var process = new Process { StartInfo = psi };
            process.Start();
            var stdoutTask = process.StandardOutput.ReadToEndAsync();
            var stderrTask = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            var stdout = await stdoutTask;
            var stderr = await stderrTask;
            sw.Stop();

            if (process.ExitCode != 0)
            {
                WriteLog($"[RUN] mode={mode} rc={process.ExitCode} elapsed_ms={sw.ElapsedMilliseconds} stdout={Shorten(stdout)} stderr={Shorten(stderr)}");
                SetStatus("エラー", $"終了コード {process.ExitCode}", isError: true);
                SetNotice(Shorten(string.IsNullOrWhiteSpace(stderr) ? stdout : stderr, 120));
                return;
            }

            LoadResultFromDisk(mode.ToString());
            WriteLog($"[RUN] mode={mode} rc=0 elapsed_ms={sw.ElapsedMilliseconds}");
            SetStatus("完了", $"{sw.ElapsedMilliseconds} ms");
            SetNotice(string.Empty);
            _tabControl.SelectedIndex = 2;
        }
        catch (Exception ex)
        {
            WriteLog($"[ERROR] conversion failed mode={mode}: {ex}");
            SetStatus("エラー", ex.Message, isError: true);
            SetNotice(Shorten(ex.ToString(), 120));
        }
        finally
        {
            _isRunning = false;
            SetBusy(false);
        }
    }

    private void CopyResult()
    {
        try
        {
            if (string.IsNullOrWhiteSpace(_resultTextBox.Text))
            {
                SetNotice("コピーできる結果がありません");
                return;
            }

            Clipboard.SetText(_resultTextBox.Text);
            SetStatus("完了", "変換結果をコピーしました");
            SetNotice(string.Empty);
        }
        catch (Exception ex)
        {
            WriteLog($"[ERROR] copy failed: {ex}");
            SetNotice("クリップボードへコピーできませんでした");
        }
    }

    private void OpenOutputFile()
    {
        try
        {
            if (!File.Exists(_runtimePaths.ResultPath))
            {
                SetNotice("出力ファイルがありません");
                return;
            }

            Process.Start(new ProcessStartInfo
            {
                FileName = _runtimePaths.ResultPath,
                UseShellExecute = true,
            });
        }
        catch (Exception ex)
        {
            WriteLog($"[ERROR] open output failed: {ex}");
            SetNotice("出力ファイルを開けませんでした");
        }
    }

    private void RestoreWindowBounds()
    {
        var requested = _settings.WindowBounds;
        if (requested.Width <= 0 || requested.Height <= 0)
        {
            CenterToScreen();
            return;
        }

        var area = Screen.FromPoint(Cursor.Position).WorkingArea;
        var width = Math.Min(Math.Max(requested.Width, 940), Math.Max(940, area.Width));
        var height = Math.Min(Math.Max(requested.Height, 520), Math.Max(520, area.Height));
        var x = requested.X;
        var y = requested.Y;
        var margin = 80;

        var fitsHorizontally = (x + margin) < area.Right && (x + width - margin) > area.Left;
        var fitsVertically = (y + margin) < area.Bottom && (y + height - margin) > area.Top;
        if (!fitsHorizontally || !fitsVertically)
        {
            x = area.Left + Math.Max(0, (area.Width - width) / 2);
            y = area.Top + Math.Max(0, (area.Height - height) / 2);
        }

        StartPosition = FormStartPosition.Manual;
        Bounds = new Rectangle(x, y, width, height);
    }

    private void PersistSettings()
    {
        if (WindowState == FormWindowState.Normal)
        {
            _settings.WindowBounds = Bounds;
        }
        _settings.RuntimeDirectory = _runtimeDirTextBox.Text.Trim();
        Directory.CreateDirectory(Path.GetDirectoryName(_settingsPath)!);
        var payload = JsonSerializer.Serialize(_settings, JsonOptions);
        File.WriteAllText(_settingsPath, payload, new UTF8Encoding(false));
    }

    private void SetBusy(bool busy)
    {
        _progressBar.Visible = busy;
        _convertButton.Enabled = !busy;
        _titleOnlyButton.Enabled = !busy;
        _noTitleButton.Enabled = !busy;
        _copyButton.Enabled = !busy;
        _openButton.Enabled = !busy;
        _browseButton.Enabled = !busy;
        _reloadButton.Enabled = !busy;
    }

    private void SetStatus(string status, string detail, bool isError = false)
    {
        _statusLabel.Text = status;
        _detailLabel.Text = detail;
        _statusLabel.ForeColor = isError ? Color.FromArgb(164, 0, 0) : SystemColors.ControlText;
    }

    private void SetNotice(string text)
    {
        _noticeLabel.Text = text;
    }

    private static string NormalizeText(string key, string raw)
    {
        raw ??= string.Empty;
        raw = raw.Replace("\r\n", "\n").Replace('\r', '\n');
        if (key is "title" or "no")
        {
            var parts = raw.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            return string.Join(" ", parts).Trim();
        }

        return raw.TrimEnd('\n');
    }

    private static string TryReadNormalized(string path, string key, out string encodingName)
    {
        var raw = TryReadRaw(path, out encodingName);
        return NormalizeText(key, raw);
    }

    private static string TryReadRaw(string path, out string encodingName)
    {
        if (!File.Exists(path))
        {
            encodingName = "missing";
            return string.Empty;
        }

        foreach (var encoding in new[] { new UTF8Encoding(false), Encoding.UTF8, Encoding.GetEncoding(932) })
        {
            try
            {
                using var reader = new StreamReader(path, encoding, detectEncodingFromByteOrderMarks: true);
                encodingName = encoding.WebName;
                return reader.ReadToEnd().Replace("\r\n", "\n").Replace('\r', '\n').TrimEnd('\n');
            }
            catch (DecoderFallbackException)
            {
            }
        }

        encodingName = "fallback";
        return File.ReadAllText(path);
    }

    private static string GetFieldLabel(string key) => key switch
    {
        "title" => "タイトル",
        "actress" => "女優",
        "no" => "品番",
        _ => key,
    };

    private static string Shorten(string text, int maxLength = 200)
    {
        text ??= string.Empty;
        text = string.Join(" ", text.Replace('\r', '\n').Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));
        if (text.Length <= maxLength)
        {
            return text;
        }
        return text[..(maxLength - 1)] + "…";
    }

    private static string GetDefaultRuntimeDirectory()
    {
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        return Path.Combine(appData, "sakura", "avtext");
    }

    private static string GetSettingsDirectory()
    {
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(localAppData, SettingsFolderName);
    }

    private AppSettings LoadSettings()
    {
        try
        {
            if (!File.Exists(_settingsPath))
            {
                return AppSettings.CreateDefault();
            }

            var payload = JsonSerializer.Deserialize<AppSettings>(File.ReadAllText(_settingsPath, Encoding.UTF8), JsonOptions);
            return payload ?? AppSettings.CreateDefault();
        }
        catch
        {
            return AppSettings.CreateDefault();
        }
    }

    private void WriteLog(string message)
    {
        try
        {
            var dir = Path.GetDirectoryName(_logPath)!;
            Directory.CreateDirectory(dir);
            File.AppendAllText(_logPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {message}{Environment.NewLine}", new UTF8Encoding(false));
        }
        catch
        {
        }
    }

    public static void WriteEmergencyLog(string message)
    {
        try
        {
            var settingsDir = GetSettingsDirectory();
            var logPath = Path.Combine(settingsDir, "logs", LogFileName);
            Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
            File.AppendAllText(logPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {message}{Environment.NewLine}", new UTF8Encoding(false));
        }
        catch
        {
        }
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };
}

internal enum ConversionMode
{
    TitleAndActress,
    TitleOnly,
    NoTitle,
}

internal readonly record struct FileSignature(bool Exists, long LastWriteTicks, long Length)
{
    public static FileSignature FromPath(string path)
    {
        var file = new FileInfo(path);
        if (!file.Exists)
        {
            return new FileSignature(false, 0, 0);
        }

        return new FileSignature(true, file.LastWriteTimeUtc.Ticks, file.Length);
    }
}

internal sealed class RuntimePaths
{
    public string BaseDirectory { get; }
    public string TitlePath => Path.Combine(BaseDirectory, "title.txt");
    public string ActressPath => Path.Combine(BaseDirectory, "actress.txt");
    public string NoPath => Path.Combine(BaseDirectory, "no.txt");
    public string ResultPath => Path.Combine(BaseDirectory, "conv_converted.txt");
    public string ConvertBat => Path.Combine(BaseDirectory, "run_av_text_convert.bat");
    public string TitleOnlyBat => Path.Combine(BaseDirectory, "run_av_title_convert.bat");
    public string NoTitleBat => Path.Combine(BaseDirectory, "run_no_title_to_conv.bat");

    private RuntimePaths(string baseDirectory)
    {
        BaseDirectory = baseDirectory;
    }

    public static RuntimePaths FromBaseDirectory(string baseDirectory) => new(Path.GetFullPath(baseDirectory));

    public string GetPathForKey(string key) => key switch
    {
        "title" => TitlePath,
        "actress" => ActressPath,
        "no" => NoPath,
        "result" => ResultPath,
        _ => throw new ArgumentOutOfRangeException(nameof(key)),
    };

    public string GetBatchPath(ConversionMode mode) => mode switch
    {
        ConversionMode.TitleAndActress => ConvertBat,
        ConversionMode.TitleOnly => TitleOnlyBat,
        ConversionMode.NoTitle => NoTitleBat,
        _ => throw new ArgumentOutOfRangeException(nameof(mode)),
    };

    public List<string> GetMissingBatchPaths()
    {
        var list = new List<string>();
        foreach (var path in new[] { ConvertBat, TitleOnlyBat, NoTitleBat })
        {
            if (!File.Exists(path))
            {
                list.Add(path);
            }
        }

        return list;
    }
}

internal sealed class AppSettings
{
    public string RuntimeDirectory { get; set; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "sakura",
        "avtext");

    public int WatchIntervalMs { get; set; } = 1200;

    public int SaveDelayMs { get; set; } = 450;

    public Rectangle WindowBounds { get; set; } = new Rectangle(0, 0, 1180, 760);

    public static AppSettings CreateDefault() => new();
}
