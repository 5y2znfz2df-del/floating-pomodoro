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

        private static readonly string ProgramsDir =
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs");

        // 默认装到 %LOCALAPPDATA%\Programs\Pomodoro；
        // 设置了 POMODORO_INSTALL_DIR 就装到指定目录（绿色安装 / 测试用）。
        private static readonly string DestDir = ResolveDestDir();

        private static readonly string TargetExe = Path.Combine(DestDir, "Pomodoro.exe");

        /// <summary>zip 里的顶层目录是 Pomodoro，所以解压到它的父目录。</summary>
        private static readonly string InstallRoot =
            Path.GetDirectoryName(DestDir.TrimEnd(Path.DirectorySeparatorChar)) ?? DestDir;

        private static string ResolveDestDir()
        {
            string custom = Environment.GetEnvironmentVariable("POMODORO_INSTALL_DIR");
            if (!string.IsNullOrWhiteSpace(custom))
                return Path.GetFullPath(custom);
            return Path.Combine(ProgramsDir, "Pomodoro");
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
                    Console.WriteLine("安装完成：" + TargetExe);
                    TryLog("安装完成：" + TargetExe);
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
        /// <summary>安装主体：解压、建快捷方式、写卸载器、启动程序。</summary>
        private static void InstallCore(Action<string, int> report)
        {
            report("正在安装到 " + DestDir, 0);

            if (Directory.Exists(DestDir))
            {
                report("检测到旧版本，正在移除…", 2);
                try { Directory.Delete(DestDir, true); }
                catch (Exception) { /* 文件被占用就继续覆盖 */ }
            }

            Directory.CreateDirectory(InstallRoot);
            ExtractPayload(report);

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
            StartApp();
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
                        string relative = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                        string target = Path.Combine(InstallRoot, relative);

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
                                   5 + (int)(88.0 * done / Math.Max(1, total)));
                    }
                }
            }

            if (!File.Exists(TargetExe))
                throw new InvalidOperationException("解压后没有找到 Pomodoro.exe");
        }

        // ----------------------------------------------------------- shortcuts --
        private static void CreateShortcuts()
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null) return;
            object shell = Activator.CreateInstance(shellType);

            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
            MakeLink(shell, Path.Combine(desktop, AppName + ".lnk"), TargetExe, DestDir, TargetExe + ",0");

            string startMenu = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Programs), AppName);
            Directory.CreateDirectory(startMenu);
            MakeLink(shell, Path.Combine(startMenu, AppName + ".lnk"), TargetExe, DestDir, TargetExe + ",0");

            string uninstall = Path.Combine(DestDir, "uninstall.cmd");
            MakeLink(shell, Path.Combine(startMenu, "卸载.lnk"), uninstall, DestDir,
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
            string ps1 = Path.Combine(DestDir, "uninstall.ps1");
            File.WriteAllText(ps1,
                "$ErrorActionPreference = 'SilentlyContinue'\r\n" +
                "$dest = Join-Path $env:LOCALAPPDATA 'Programs\\Pomodoro'\r\n" +
                "$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) '" + AppName + ".lnk'\r\n" +
                "$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) '" + AppName + "'\r\n" +
                "Get-Process -Name Pomodoro | Stop-Process -Force\r\n" +
                "Start-Sleep -Milliseconds 400\r\n" +
                "Remove-Item $desktop -Force\r\n" +
                "Remove-Item $startMenu -Recurse -Force\r\n" +
                "Start-Sleep -Milliseconds 300\r\n" +
                "Remove-Item $dest -Recurse -Force\r\n",
                new System.Text.UTF8Encoding(true));

            string cmd = Path.Combine(DestDir, "uninstall.cmd");
            File.WriteAllText(cmd,
                "@echo off\r\n" +
                "powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0uninstall.ps1\"\r\n");
        }

        private static void StartApp()
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = TargetExe,
                WorkingDirectory = DestDir,
                UseShellExecute = true
            });
        }

        /// <summary>把详细异常写进日志，方便排查。</summary>
        private static void TryLog(string text)
        {
            try
            {
                string path = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Pomodoro-Setup.log");
                File.AppendAllText(path,
                    "[" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "]\r\n" + text + "\r\n\r\n");
            }
            catch (Exception)
            {
                // 日志都写不了就算了，别掩盖原始错误
            }
        }
    }
}
