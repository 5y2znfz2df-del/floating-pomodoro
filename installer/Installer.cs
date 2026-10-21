// 悬浮番茄钟 —— 安装程序
//
// 单文件：payload.zip 作为嵌入资源被打进 exe，运行时直接解压到目标目录，
// 不经过 %TEMP%，所以不会被「创建临时目录」这类问题卡住。
//
// 用法：
//   Pomodoro-Setup.exe                          图形界面安装（可以选目录）
//   Pomodoro-Setup.exe --silent                 静默安装，自动挑一个可写目录
//   Pomodoro-Setup.exe --silent --dir D:\Apps   静默安装到指定目录
//
// 编译见 installer/build-installer.ps1

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace PomodoroSetup
{
    internal static class Program
    {
        // winexe 没有自己的控制台，--silent 时挂到父进程的控制台上才能看到输出
        [DllImport("kernel32.dll")]
        private static extern bool AttachConsole(int processId);

        private const string AppName = "悬浮番茄钟";
        private const string ResourceName = "payload.zip";

        private static string _destDir = "";
        private static string _targetExe = "";

        private static Label _status;
        private static ProgressBar _bar;
        private static TextBox _pathBox;
        private static Button _installButton;
        private static Button _browseButton;

        // ------------------------------------------------------------------ 入口 --
        [STAThread]
        private static int Main(string[] args)
        {
            bool silent = HasFlag(args, "--silent");
            string requested = GetOption(args, "--dir");

            if (silent)
            {
                AttachConsole(-1);
                return RunSilent(requested);
            }

            Application.EnableVisualStyles();
            Form form = BuildWindow(requested);
            Application.Run(form);
            return 0;
        }

        private static int RunSilent(string requested)
        {
            try
            {
                if (!string.IsNullOrWhiteSpace(requested))
                {
                    UseInstallDir(Path.GetFullPath(requested));
                    if (!CanWrite(_destDir))
                        throw new UnauthorizedAccessException("指定的目录写不进去：" + _destDir);
                }
                else
                {
                    UseInstallDir(PickWritableCandidate());
                }

                InstallCore(delegate (string text, int percent)
                {
                    string line = string.Format("[{0,3}%] {1}", percent, text);
                    Console.WriteLine(line);
                    TryLog(line);
                });

                Console.WriteLine("安装完成：" + _targetExe);
                TryLog("安装完成：" + _targetExe);
                return 0;
            }
            catch (Exception ex)
            {
                TryLog(ex.ToString());
                Console.Error.WriteLine("安装失败：" + ex.Message);
                return 1;
            }
        }

        // -------------------------------------------------------------- 界面 --
        private static Form BuildWindow(string requested)
        {
            var form = new Form
            {
                Text = AppName + " 安装程序",
                ClientSize = new Size(460, 232),
                FormBorderStyle = FormBorderStyle.FixedDialog,
                StartPosition = FormStartPosition.CenterScreen,
                MaximizeBox = false,
                MinimizeBox = false,
                BackColor = Color.FromArgb(28, 28, 30),
                ForeColor = Color.White,
                Font = new Font("Microsoft YaHei UI", 9f)
            };

            var title = new Label
            {
                Text = "选择安装位置",
                Bounds = new Rectangle(20, 16, 420, 22),
                ForeColor = Color.FromArgb(245, 245, 247),
                Font = new Font("Microsoft YaHei UI", 10.5f, FontStyle.Bold)
            };

            _pathBox = new TextBox
            {
                Bounds = new Rectangle(20, 46, 330, 24),
                Text = "",
                ReadOnly = true,
                BackColor = Color.FromArgb(44, 44, 46),
                ForeColor = Color.FromArgb(245, 245, 247),
                BorderStyle = BorderStyle.FixedSingle
            };

            _browseButton = new Button
            {
                Text = "浏览…",
                Bounds = new Rectangle(358, 45, 82, 26)
            };
            _browseButton.Click += OnBrowse;

            var hint = new Label
            {
                Text = "默认会挑一个当前能写入的目录；也可以自己选（比如 D:\\Apps\\Pomodoro）。",
                Bounds = new Rectangle(20, 78, 420, 34),
                ForeColor = Color.FromArgb(150, 150, 155)
            };

            _status = new Label
            {
                Text = "准备就绪",
                Bounds = new Rectangle(20, 116, 420, 20),
                ForeColor = Color.FromArgb(180, 180, 185)
            };

            _bar = new ProgressBar
            {
                Bounds = new Rectangle(20, 138, 420, 14),
                Minimum = 0,
                Maximum = 100,
                Visible = false
            };

            _installButton = new Button
            {
                Text = "安装",
                Bounds = new Rectangle(238, 176, 110, 32),
                DialogResult = DialogResult.None
            };
            _installButton.Click += OnInstall;

            var cancel = new Button
            {
                Text = "取消",
                Bounds = new Rectangle(358, 176, 82, 32)
            };
            cancel.Click += delegate { form.Close(); };

            form.Controls.AddRange(new Control[]
            {
                title, _pathBox, _browseButton, hint, _status, _bar, _installButton, cancel
            });

            // 首选指定目录，其次自动挑一个可写的
            string initial = !string.IsNullOrWhiteSpace(requested)
                ? Path.GetFullPath(requested)
                : SafePickWritable();

            _pathBox.Text = initial;
            form.AcceptButton = _installButton;
            return form;
        }

        private static string SafePickWritable()
        {
            try { return PickWritableCandidate(); }
            catch (Exception ex)
            {
                TryLog(ex.Message);
                return CandidateDirs().Length > 0 ? CandidateDirs()[0] : "";
            }
        }

        private static void OnBrowse(object sender, EventArgs e)
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "选择安装目录（建议用一个空文件夹，例如 D:\\Apps\\Pomodoro）";
                dialog.ShowNewFolderButton = true;
                string current = _pathBox.Text.Trim();
                if (current.Length > 0)
                    dialog.SelectedPath = current;

                if (dialog.ShowDialog() != DialogResult.OK)
                    return;

                // 用户可能选中了上级目录，自动补一个 Pomodoro 子目录，避免把文件倒进 D:\
                string picked = dialog.SelectedPath;
                if (string.Equals(Path.GetFileName(picked.TrimEnd('\\')), "Pomodoro",
                                  StringComparison.OrdinalIgnoreCase))
                {
                    _pathBox.Text = picked;
                }
                else
                {
                    _pathBox.Text = Path.Combine(picked, "Pomodoro");
                }
            }
        }

        private static void OnInstall(object sender, EventArgs e)
        {
            string target = _pathBox.Text.Trim();
            if (target.Length == 0)
            {
                MessageBox.Show("请先选择安装位置。", AppName, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            UseInstallDir(target);
            if (!CanWrite(_destDir))
            {
                MessageBox.Show(
                    "这个目录写不进去：\r\n" + _destDir +
                    "\r\n\r\n换一个目录试试（比如 D:\\Apps\\Pomodoro 或桌面上的文件夹）。",
                    AppName, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            _installButton.Enabled = false;
            _browseButton.Enabled = false;
            _pathBox.Enabled = false;
            _bar.Visible = true;

            try
            {
                InstallCore(delegate (string text, int percent)
                {
                    _status.Text = text;
                    _bar.Value = Math.Max(0, Math.Min(100, percent));
                    _status.Refresh();
                    _bar.Refresh();
                });

                _status.Text = "安装完成，正在启动…";
                _status.Refresh();
                Thread.Sleep(400);
                CloseOwner();
            }
            catch (Exception ex)
            {
                TryLog(ex.ToString());
                _bar.Visible = false;
                _installButton.Enabled = true;
                _browseButton.Enabled = true;
                _pathBox.Enabled = true;
                _status.Text = "安装失败";
                MessageBox.Show("安装失败：\r\n" + ex.Message, AppName + " 安装程序",
                                MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private static void CloseOwner()
        {
            foreach (Form form in Application.OpenForms)
            {
                form.Close();
                return;
            }
        }

        // ------------------------------------------------------------ 目录选择 --
        private static string[] CandidateDirs()
        {
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);

            var list = new System.Collections.Generic.List<string>
            {
                Path.Combine(local, "Programs", "Pomodoro"),
                Path.Combine(local, "Pomodoro"),
                Path.Combine(roaming, "Pomodoro"),
                Path.Combine(profile, "Pomodoro"),
            };

            try
            {
                string here = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                if (!string.IsNullOrEmpty(here))
                    list.Add(Path.Combine(here, "PomodoroApp"));
            }
            catch (Exception)
            {
                // 拿不到 exe 路径就算了
            }
            return list.ToArray();
        }

        /// <summary>按候选顺序找第一个真正能写入的目录。</summary>
        private static string PickWritableCandidate()
        {
            var failures = new System.Text.StringBuilder();
            foreach (string candidate in CandidateDirs())
            {
                if (CanWrite(candidate))
                {
                    if (failures.Length > 0)
                        TryLog("以下目录不可写，已跳过：\r\n" + failures);
                    return candidate;
                }
                failures.AppendLine("  ✗ " + candidate);
            }
            throw new UnauthorizedAccessException(
                "这些目录都写不进去：\r\n" + failures +
                "\r\n可以点「浏览…」换一个位置，或右键以管理员身份运行。");
        }

        private static void UseInstallDir(string dir)
        {
            _destDir = Path.GetFullPath(dir).TrimEnd(Path.DirectorySeparatorChar);
            _targetExe = Path.Combine(_destDir, "Pomodoro.exe");
        }

        /// <summary>真的建一次目录并写一个临时文件，确认有写权限。</summary>
        private static bool CanWrite(string dir)
        {
            try
            {
                Directory.CreateDirectory(dir);
                string probe = Path.Combine(dir, ".write-probe");
                File.WriteAllText(probe, "ok");
                File.Delete(probe);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // -------------------------------------------------------------- 安装 --
        /// <summary>安装主体：解压、建快捷方式、写卸载器、启动程序。</summary>
        private static void InstallCore(Action<string, int> report)
        {
            report("正在安装到 " + _destDir, 3);

            if (Directory.Exists(_destDir))
            {
                report("检测到旧版本，正在移除…", 5);
                try { Directory.Delete(_destDir, true); }
                catch (Exception) { /* 文件被占用就继续覆盖 */ }
            }

            Directory.CreateDirectory(_destDir);
            ExtractPayload(report);

            report("正在创建快捷方式…", 96);
            try
            {
                CreateShortcuts();
                WriteUninstaller();
            }
            catch (Exception ex)
            {
                TryLog("创建快捷方式失败（不影响程序本身）：" + ex.Message);
                report("快捷方式创建失败，但程序已安装", 96);
            }

            report("安装完成，正在启动…", 100);
            Thread.Sleep(300);

            // 启动失败不代表安装失败：文件已经就位了
            try
            {
                StartApp();
            }
            catch (Exception ex)
            {
                TryLog("自动启动失败（不影响安装）：" + ex.Message);
                report("已安装，但自动启动失败，请手动打开：" + _targetExe, 100);
                Thread.Sleep(1500);
            }
        }

        private static void ExtractPayload(Action<string, int> report)
        {
            using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(ResourceName))
            {
                if (stream == null)
                    throw new InvalidOperationException("安装包损坏：找不到 " + ResourceName);

                using (var zip = new ZipArchive(stream, ZipArchiveMode.Read))
                {
                    int total = zip.Entries.Count;
                    int done = 0;

                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        // zip 顶层是 Pomodoro/，剥掉这一段直接解到 _destDir，
                        // 这样目标目录叫什么名字都能装
                        string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                        int cut = relative.IndexOf(Path.DirectorySeparatorChar);
                        relative = cut >= 0 ? relative.Substring(cut + 1) : "";
                        if (relative.Length == 0) { done++; continue; }

                        string target = Path.Combine(_destDir, relative);

                        if (entry.Name.Length == 0)
                        {
                            Directory.CreateDirectory(target);
                        }
                        else
                        {
                            string dir = Path.GetDirectoryName(target);
                            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                            entry.ExtractToFile(target, true);
                        }

                        done++;
                        if (done % 50 == 0 || done == total)
                            report(string.Format("正在解压… {0}/{1}", done, total),
                                   8 + (int)(86.0 * done / Math.Max(1, total)));
                    }
                }
            }

            if (!File.Exists(_targetExe))
                throw new InvalidOperationException("解压后没有找到 Pomodoro.exe");
        }

        // ----------------------------------------------------------- 快捷方式 --
        private static void CreateShortcuts()
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null) return;
            object shell = Activator.CreateInstance(shellType);

            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
            MakeLink(shell, Path.Combine(desktop, AppName + ".lnk"), _targetExe, _destDir, _targetExe + ",0");

            string startMenu = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Programs), AppName);
            Directory.CreateDirectory(startMenu);
            MakeLink(shell, Path.Combine(startMenu, AppName + ".lnk"), _targetExe, _destDir, _targetExe + ",0");

            string uninstall = Path.Combine(_destDir, "uninstall.cmd");
            MakeLink(shell, Path.Combine(startMenu, "卸载.lnk"), uninstall, _destDir,
                     Path.Combine(Environment.SystemDirectory, "shell32.dll") + ",131");
        }

        private static void MakeLink(object shell, string linkPath, string target,
                                     string workDir, string iconLocation)
        {
            object shortcut = shell.GetType().InvokeMember(
                "CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { linkPath });
            Type type = shortcut.GetType();

            type.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { target });
            type.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workDir });
            type.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { iconLocation });
            type.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { AppName });
            type.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
        }

        private static void WriteUninstaller()
        {
            // 卸载脚本里的目录必须和实际安装位置一致
            string ps1 = Path.Combine(_destDir, "uninstall.ps1");
            File.WriteAllText(ps1,
                "$ErrorActionPreference = 'SilentlyContinue'\r\n" +
                "$dest = '" + _destDir.Replace("'", "''") + "'\r\n" +
                "$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) '" + AppName + ".lnk'\r\n" +
                "$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) '" + AppName + "'\r\n" +
                "Get-Process -Name Pomodoro | Stop-Process -Force\r\n" +
                "Start-Sleep -Milliseconds 400\r\n" +
                "Remove-Item $desktop -Force\r\n" +
                "Remove-Item $startMenu -Recurse -Force\r\n" +
                "Start-Sleep -Milliseconds 300\r\n" +
                "Remove-Item $dest -Recurse -Force\r\n",
                new System.Text.UTF8Encoding(true));

            string cmd = Path.Combine(_destDir, "uninstall.cmd");
            File.WriteAllText(cmd,
                "@echo off\r\n" +
                "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0uninstall.ps1\"\r\n");
        }

        private static void StartApp()
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = _targetExe,
                WorkingDirectory = _destDir,
                UseShellExecute = true
            });
        }

        // -------------------------------------------------------------- 杂项 --
        private static bool HasFlag(string[] args, string flag)
        {
            foreach (string a in args)
                if (string.Equals(a, flag, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        private static string GetOption(string[] args, string name)
        {
            for (int i = 0; i < args.Length - 1; i++)
                if (string.Equals(args[i], name, StringComparison.OrdinalIgnoreCase))
                    return args[i + 1];
            return null;
        }

        /// <summary>把详细异常写进日志。用户目录写不了就退到 exe 旁边、再退到 TEMP。</summary>
        private static void TryLog(string text)
        {
            string body = "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "]\r\n" + text + "\r\n\r\n";
            var targets = new System.Collections.Generic.List<string>();
            try
            {
                targets.Add(Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Pomodoro-Setup.log"));
            }
            catch (Exception) { }
            try
            {
                targets.Add(Path.Combine(
                    Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".",
                    "Pomodoro-Setup.log"));
            }
            catch (Exception) { }
            try { targets.Add(Path.Combine(Path.GetTempPath(), "Pomodoro-Setup.log")); }
            catch (Exception) { }

            foreach (string path in targets)
            {
                try
                {
                    File.AppendAllText(path, body);
                    return;
                }
                catch (Exception)
                {
                    // 这个位置写不了，试下一个
                }
            }
        }
    }
}
