# 打包与分发

这份文档收纳了番茄钟 demo 打包成 exe、以及生成单文件安装程序的全部细节。
根 README 只保留组件用法，打包相关的内容都在这里。

> **迁移说明（v0.2.0）**
> 仓库定位已从「番茄钟成品」调整为「Flet Windows 窗口特效组件」。
> 原来的根目录 `win_effects.py` 已移入 `flet_win_effects/` 包，导入方式从
> `import win_effects` 改为 `import flet_win_effects as win_effects`（或直接
> `from flet_win_effects import apply_glass`）。函数签名与行为完全不变。

---

## 运行环境

- Windows 10 / 11
- 开发需要 Python 3.9+（本项目用 3.12.10）

### 最终用户不需要安装 Python

安装包是 PyInstaller `-D` 模式打出来的「冻结」程序，Python 解释器、标准库、
Flet/Flutter 运行时、VC++ 运行库全都打包在 `_internal\` 里（826 个文件 / 192 MB）：

| 文件 | 作用 |
| --- | --- |
| `_internal\python312.dll` | Python 解释器本体 |
| `_internal\base_library.zip` | Python 标准库 |
| `_internal\vcruntime140.dll`、`msvcp140.dll`、`ucrtbase.dll` | C++ 运行库 |
| `_internal\flet_desktop\app\flet\flet.exe` + `flutter_windows.dll` | 界面运行时 |

装完之后直接双击就能用，不需要联网、不需要 pip、不需要 Python 环境。
安装程序还会在解压后**逐个核对这些文件**，缺了会明确指出缺哪一个。

### 为什么锁 `flet==0.28.3`

Flet 从 1.0 开始，桌面客户端不在 wheel 里了，改成首次运行时从 GitHub Releases
下载。0.28.3 把 `flet.exe` 和 Flutter 运行时直接打进 wheel，真正做到装完即用、
全程不需要联网。这对本项目「完全本地运行」的要求是必需的。

---

## 打包成 exe

```powershell
flet pack app.py `
  --name Pomodoro `
  --icon assets/icon.ico `
  --product-name "悬浮番茄钟" `
  --company-name "XiangFu" `
  --product-version 1.0.2 `
  --file-version 1.0.2.0 `
  --copyright "MIT License" `
  -D
```

产物在 `dist\Pomodoro\Pomodoro.exe`，**整个 `Pomodoro` 文件夹一起分发**（双击文件夹里的 exe 即可）。

### 为什么默认用 `-D`（目录模式）而不是单文件

单文件模式（不加 `-D`）每次启动都要先把 192 MB 的自己解压到 `%TEMP%\_MEIxxxx`，
这一步在实际机器上踩过两个坑：

| 坑 | 现象 | 目录模式 |
| --- | --- | --- |
| 安全软件拦截建临时目录 | 弹窗 **Could not create temporary directory!** | 不受影响，启动时不解压 |
| 临时目录 ACL 受限 | 同上，或启动后立刻退出 | 不受影响 |
| 冷启动慢 | 每次 3–8 秒 | 接近秒开 |

所以除非必须单文件分发，一律建议 `-D`。

### 其它打包参数

- **看报错**：加 `--debug-console debug`，exe 会带一个控制台窗口，出问题能直接看到堆栈。
- **换输出目录**：`--distpath D:\apps`。
- **非交互环境**：打包会问一次「是否删除 build 目录」，脚本/CI 里加 `-y` 跳过。

### 关于产物的两个事实

| 项目 | 说明 |
| --- | --- |
| 体积 | 目录模式整体约 **203 MB**（exe 本体 10.7 MB + `_internal` 依赖） |
| 杀毒误报 | PyInstaller 产物被启发式引擎误判很常见，加白名单即可 |

打包生成的 `Pomodoro.spec`、`build\` 都可以删，重新打包会自动生成。

---

## 生成安装包（单个 exe）

```powershell
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
```

产物：`dist\Pomodoro-Setup.exe`（约 90 MB）——**就一个文件**，双击即装。

![安装程序](../docs/screenshot-setup.png)

它做的事：

1. **让你选安装位置**（默认自动挑一个能写的目录，也可以点「浏览…」自选）
2. 解压到目标目录，不需要管理员权限
3. **核对自带运行时**：检查 `python312.dll`、`base_library.zip`、`flet.exe` 等关键文件，
   缺了就明确报出缺哪一个（而不是装完闪退）
4. 在**桌面**和**开始菜单**建「悬浮番茄钟」快捷方式
5. 在开始菜单建「卸载」
6. 装完直接启动程序

> 覆盖安装时会先自动关掉正在运行的番茄钟（主程序 `Pomodoro` 和界面进程 `flet`），
> 否则文件被占用会导致安装失败。

### 为什么不用 Inno Setup / NSIS

这台机器访问不了 GitHub（Inno Setup 的下载全在 GitHub Releases 上），本机也没装 NSIS。
所以用 **Windows 自带的 C# 编译器**（`csc.exe`）编译了一个自解压安装程序：

- 应用目录压成 `payload.zip`（~90 MB），作为**嵌入资源**塞进 exe
- 运行时直接解压到目标目录，**不经过 `%TEMP%`** —— 正好绕开单文件模式那个
  `Could not create temporary directory!` 的坑
- 界面是一个小窗口 + 进度条，全程不联网

### 静默安装 / 自定义目录

```powershell
# 图形界面：可以自己选目录（点「浏览…」）
.\dist\Pomodoro-Setup.exe

# 无界面安装，自动挑一个可写的目录
.\dist\Pomodoro-Setup.exe --silent

# 无界面安装到指定目录（绿色安装）
.\dist\Pomodoro-Setup.exe --silent --dir "D:\Apps\Pomodoro"
```

安装失败时详细报错会写进 `%LOCALAPPDATA%\Pomodoro-Setup.log`（写不了会退到安装包所在目录或 `%TEMP%`）。

### 安装目录的自动回退

从 v1.0.2 起，如果默认目录写不进去，安装程序会依次尝试：

```
%LOCALAPPDATA%\Programs\Pomodoro
%LOCALAPPDATA%\Pomodoro
%APPDATA%\Pomodoro
%USERPROFILE%\Pomodoro
安装包所在目录\PomodoroApp
```

判定标准是「真的能建目录并写入文件」，所以哪怕 `Programs` 被锁住也会自动落到下一个。
快捷方式始终指向实际安装到的位置。

如果**全都**写不进去，会弹出完整清单。此时可以：

1. 打开安全软件的拦截记录，允许一次再装；
2. 用 `installer\portable-install.cmd`（或 dist 里的 `一键安装.cmd`）—— 走 cmd + PowerShell 复制文件；
3. 干脆不装：直接双击 `Pomodoro\Pomodoro.exe`，绿色版不需要任何写入。

---

## 排查

**双击 exe 弹出 `Could not create temporary directory!`**
这是**单文件模式**的典型故障：它启动时要往 `%TEMP%` 里解压自己，被安全软件（火绒、Defender 等）
或临时目录权限拦住了。解决办法：改用 `-D` 目录模式重新打包，或者把 exe 加进安全软件白名单。

**安装时报「访问被拒绝」（对路径 `%LOCALAPPDATA%\Programs\Pomodoro` 的访问被拒绝）**
先看上面的「安装目录的自动回退」——新版会自动换目录。如果全部失败，按那三条处理。

**双击 exe 闪一下就没了**
用 `flet pack ... --debug-console debug` 重新打包，看控制台输出。多数是杀毒软件拦截或缺少 VC 运行库。

**被杀毒软件报毒**
PyInstaller 打出来的单文件 exe 常被启发式引擎误判，这属于打包工具的普遍问题，不是代码行为。
加信任白名单，或改用 `-D` 目录模式分发。

---

## 关于 `tools/wheelinstall.py`

这个脚本是为了一台特殊机器写的：那台机器上 pip 装不了包（父目录有一条
`Everyone Deny DeleteSubdirectoriesAndFiles` 的 ACL，pip 无法重命名自己的临时文件）。
它自己解析依赖、用 zipfile 解包，只创建文件、不删除文件。

**正常机器不需要它**，直接 `pip install -r requirements.txt` 就行。

---

## 打包相关的验证记录

- `flet pack -D` 产出的 `dist\Pomodoro\Pomodoro.exe` 与安装程序装出来的程序都能正常启动，
  界面与源码运行一致
- 安装程序的**解压环节**已实测：841 个条目 → 826 个文件 / 203 MB，全部到位
- 程序运行中直接覆盖安装：自动关闭 `Pomodoro` + `flet` 两个进程后安装成功
- 安装程序的**快捷方式创建**没能在这台机器上完整验证：开发沙箱给 .NET 子进程套了受限令牌，
  连一个「建目录」的 20 行测试程序都会被拒绝；同样的操作从 PowerShell 里做是成功的。
  在正常桌面环境下双击运行不受此限制。
