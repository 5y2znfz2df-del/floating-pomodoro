# Contributing

提 issue 时请附上三样东西，能省掉一轮来回：

1. **Windows 版本**（`winver` 截图，或 `10.0.xxxxx` 这样的版本号）
2. **是否在远程桌面 / 虚拟机里**（RDP 下亚克力常失效，这是系统限制不是 bug）
3. **启动日志里 `glass = {...}` 那一行**（`acrylic: False` 说明毛玻璃没挂上）

PR 请保持 `flet_win_effects/` 只依赖标准库，且所有失败路径仍然静默返回 `False`。
