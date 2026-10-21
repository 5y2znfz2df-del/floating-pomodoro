// 悬浮番茄钟 —— 安装程序
// 单文件：payload.zip 作为嵌入资源打包进 exe，运行时直接解压到目标目录，
// 不经过 %TEMP%，所以不会被安全软件拦「创建临时目录」。
//
// 用法：
//   Pomodoro-Setup.exe            图形界面安装（默认）
//   Pomodoro-Setup.exe --silent   命令行静默安装，进度打在控制台
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

        // 安装位置候选。某些机器上 %LOCALAPPDATA%\Programs 会被安全软件/组策略锁住，
        // 所以按顺序试，第一个能真正写进去的就用它。
        private static readonly string[] CandidateDirs = BuildCandidates();

        private static string _destDir = "";
        private static string _installRoot = "";
        private static string _targetExe = "";

        private static string[] BuildCandidates()
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

            // 最后再试「安装包所在的目录」：下载/桌面通常不会被锁
            try
            {
                string here = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                if (!string.IsNullOrEmpty(here))
                    list.Add(Path.Combine(here, "PomodoroApp"));
            }
            catch (Exception)
            {
                // 拿不到就算了
            }
            return list.ToArray();
        }

        private static Label _status;
        private static ProgressBar _bar;

        [STAThread]
        private static int Main(string[] args)
        {
            if (args.Length > 0 && string.Equals(args[0], "--silent", StringComparison.OrdinalIgnoreCase))
            {
                AttachConsole(-1);
                try
                {
                    InstallCore((text, percent) =>
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

            Application.EnableVisualStyles();
            var form = BuildWindow();
            form.Shown += (s, e) => RunInstallUi(form);
            Application.Run(form);
            return 0;
        }

        // ------------------------------------------------------------------ UI --
        private static Form BuildWindow()
        {
            var form = new Form
            {
                Text = AppName + " 安装程序",
                ClientSize = new Size(420, 150),
                FormBorderStyle = FormBorderStyle.FixedDialog,
                StartPosition = FormStartPosition.CenterScreen,
                MaximizeBox = false,
                MinimizeBox = false,
                BackColor = Color.FromArgb(28, 28, 30),
                ForeColor = Color.White,
                Font = new Font("Microsoft YaHei UI", 9f)
            };

            _status = new Label
            {
                Text = "正在准备…",
                AutoSize = false,
                Bounds = new Rectangle(20, 26, 380, 40),
                ForeColor = Color.White
            };

            _bar = new ProgressBar
            {
                Bounds = new Rectangle(20, 78, 380, 18),
                Minimum = 0,
                Maximum = 100
            };

            form.Controls.Add(_status);
            form.Controls.Add(_bar);
            return form;
        }

        private static void RunInstallUi(Form form)
        {
            try
            {
                InstallCore((text, percent) =>
                {
                    _status.Text = text;
                    _bar.Value = Math.Max(0, Math.Min(100, percent));
                    _status.Refresh();
                    _bar.Refresh();
                });
                form.Close();
            }
            catch (Exception ex)
            {
                TryLog(ex.ToString());
                MessageBox.Show(
                    "安装失败：\r\n" + ex.Message,
                    AppName + " 安装程序",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                form.Close();
            }
        }

        // -------------------------------------------------------------- install --
        /// <summary>安装主体：选目录、解压、建快捷方式、写卸载器、启动程序。</summary>
        private static void InstallCore(Action<string, int> report)
        {
            PickInstallDir(report);
            report("正在安装到 " + _destDir, 5);

            if (Directory.Exists(_destDir))
            {
                report("检测到旧版本，正在移除…", 6);
                try { Directory.Delete(_destDir, true); }
                catch (Exception) { /* 文件被占用就继续覆盖 */ }
            }

            try
            {
                Directory.CreateDirectory(_destDir);
                ExtractPayload(report);
            }
            catch (Exception)
            {
                // 当前目录写不进去（权限/安全软件），清掉痕迹换下一个候选目录
                try { if (Directory.Exists(_destDir)) Directory.Delete(_destDir, true); }
                catch (Exception) { }
                throw;
            }

            report("正在创建快捷方式…", 96);
            try
            {
                CreateShortcuts();
                WriteUninstaller();
            }
            catch (Exception ex)
            {
                // 快捷方式建不了不算致命，文件已经装好了
                TryLog("创建快捷方式失败（不影响程序本身）：" + ex.Message);
                report("快捷方式创建失败，但程序已安装", 96);
            }

            report("安装完成，正在启动…", 100);
            Thread.Sleep(300);

            // 启动失败不代表安装失败：文件已经就位了，只是自动拉起没成功
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

        /// <summary>
        /// 按候选顺序找一个真正能写入的目录。只判断「目录存在」不够，
        /// 必须实际写一个文件才算数：有些机器上 %LOCALAPPDATA%\Programs
        /// 会被安全软件或组策略锁住，建目录成功但写文件失败。
        /// </summary>
        private static void PickInstallDir(Action<string, int> report)
        {
            string custom = Environment.GetEnvironmentVariable("POMODORO_INSTALL_DIR");
            if (!string.IsNullOrWhiteSpace(custom))
            {
                string forced = Path.GetFullPath(custom);
                if (!CanWrite(forced))
                    throw new UnauthorizedAccessException(
                        "指定的安装目录不可写：" + forced);
                _destDir = forced;
                _installRoot = Path.GetDirectoryName(forced.TrimEnd(Path.DirectorySeparatorChar)) ?? forced;
                _targetExe = Path.Combine(forced, "Pomodoro.exe");
                return;
            }

            var failures = new System.Text.StringBuilder();
            foreach (string candidate in CandidateDirs)
            {
                if (CanWrite(candidate))
                {
                    _destDir = candidate;
                    _installRoot = Path.GetDirectoryName(candidate.TrimEnd(Path.DirectorySeparatorChar)) ?? candidate;
                    _targetExe = Path.Combine(candidate, "Pomodoro.exe");
                    if (failures.Length > 0)
                        TryLog("前面这些目录不可写，已跳过：\r\n" + failures);
                    return;
                }
                failures.AppendLine("  ✗ " + candidate);
                TryLog("目录不可写：" + candidate);
            }

            throw new UnauthorizedAccessException(
                "这些目录都写不进去：\r\n" + failures +
                "\r\n请检查安全软件的拦截记录，或右键以管理员身份运行。");
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

        private static void ExtractPayload(Action<string, int> report)
        {
            Assembly self = Assembly.GetExecutingAssembly();
            using (Stream stream = self.GetManifestResourceStream(ResourceName))
            {
                if (stream == null)
                    throw new InvalidOperationException("安装包损坏：找不到 " + ResourceName);

                using (var zip = new ZipArchive(stream, ZipArchiveMode.Read))
                {
                    int total = zip.Entries.Count;
                    int done = 0;

                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        // zip 的顶层是 Pomodoro/，这里把这一段剥掉，直接解到 _destDir，
                        // 这样目标目录叫什么名字都能装（Pomodoro / PomodoroApp / …）
                        string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                        int cut = relative.IndexOf(Path.DirectorySeparatorChar);
                        relative = cut >= 0 ? relative.Substring(cut + 1) : "";
                        if (relative.Length == 0)
                        {
                            done++;
                            continue;
                        }

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

        // ----------------------------------------------------------- shortcuts --
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
            string ps1 = Path.Combine(_destDir, "uninstall.ps1");
            // 卸载脚本里的目录必须和实际安装位置一致，不能写死
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
