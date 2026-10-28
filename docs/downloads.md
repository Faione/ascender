# 安装材料获取与保存

工具只消费本地文件；浏览器下载、上传到构建服务器以及基础镜像的 pull/load 均由用户执行。

## 基础镜像

在构建服务器手动准备 Ubuntu 22.04 amd64 镜像：

```bash
docker pull --platform linux/amd64 ubuntu:22.04
docker image inspect ubuntu:22.04
```

也可在其他机器准备镜像归档后，用 `docker load -i /path/to/ubuntu.tar` 导入。文件导入后的引用应与 `--base-image` 一致。工具不会自动拉取基础镜像；本地缺失直接失败。

## 首个参考组合

从参考仓库 README 整理以下文件名和直链。文件放到相应目录，不需要收集其他型号的 ops。直链未在本仓库执行下载验证，失效时从官方入口重新选择精确版本。

| 材料 | 下载入口或参考直链 | 保存目录（相对材料根） |
| --- | --- | --- |
| `Ascend-cann-toolkit_9.1.0_linux-x86_64.run` | [Toolkit](https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.0/Ascend-cann-toolkit_9.1.0_linux-x86_64.run) | `cann/9.1.0/linux-amd64/` |
| `Ascend-cann-950-ops_9.1.0_linux-x86_64.run` | [950 ops](https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.0/Ascend-cann-950-ops_9.1.0_linux-x86_64.run) | 同上 |
| `torch-2.10.0+cpu-cp310-cp310-manylinux_2_28_x86_64.whl` | [CPU wheel](https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp310-cp310-manylinux_2_28_x86_64.whl) | `torch/2.10.0/cp310/linux-amd64/` |
| `torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl` | [torch-npu wheel](https://gitcode.com/Ascend/pytorch/releases/download/v26.1.0-pytorch2.10.0/torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl) | 同上 |
| CAModel ZIP、`init.sh`、可选 `env.sh` / 自检脚本 | 从实际模型/仿真供应方获取，不推断公开地址 | 如 `camodel/950/9.1.0/` |

官方入口：[CANN](https://www.hiascend.com/developer/download/community/result?module=cann)、[PyTorch CPU wheels](https://download.pytorch.org/whl/cpu/torch/)、[torch-npu releases](https://gitcode.com/Ascend/pytorch/releases)。有官方校验和时应在准备材料时核对；本工具记录的是本地 SHA-256 指纹，不将其标为上游来源验证。

## 配套记录

核对日期：2026-10-28。软件组合来源：[Ascend/pytorch 官方版本配套](https://github.com/Ascend/pytorch/blob/master/COMPATIBILITY.md)。TorchNPU 产品发行版 26.1.0 对应此处安装包 `2.10.0.post4`，二者不能混用。

| CANN | Torch | torch-npu 安装包 | 容器 | 配套状态 | 真实镜像 / 设备 / 仿真验收 |
| --- | --- | --- | --- | --- | --- |
| 9.1.0 | 2.10.0+cpu | 2.10.0.post4 | Ubuntu 22.04、amd64、Python 3.10 | 软件版本 documented；CPU wheel 与系统为本工具首个候选输入 | 均未完成 |
| 9.1.0 | 不安装 | 不安装 | 同上 | CANN-only 首版候选 | 均未完成 |

SoC 型号由 ops 包和实际设备确定。`950` 是参考示例；接受其他 SoC 字符串不等于其驱动、编译和仿真已验证。未收录的软件组合需显式 `--allow-unverified`，CANN 命名/安装路径仍须落在工具支持范围内，不保证自动适配。

## 仿真脚本契约

- 每个 ZIP 解压到 `/opt/CAModel/<原文件名去掉.zip>/`，可执行文件的执行位会保留；不接受目录穿越、绝对路径或 ZIP 内符号链接。
- `init.sh` 的工作目录为 `/opt/CAModel`，已加载 CANN，`CAMODEL_HOME=/opt/CAModel`。负责本地目录整理、链接或其他安装步骤，不应在其中补做下载。
- `env.sh` 设置运行期变量和搜索路径；可能被加载到用户 Bash 中，应适合重复进入，不执行安装、不依赖 root、不固定写 `/root`。
- 可选自检脚本检查该 CAModel 的最小运行任务，不以 `torch.npu.is_available()` 作为仿真判据。
- 需要非 root 运行时，将日志/缓存/输出指向用户可写目录。特殊安装树写入需求需针对实际 CAModel 配置，不能通过将整个安装目录改为任意用户可写解决。

## 已有材料目录

旧布局 `cann-run/950/9.1.0/` 与 `cann-run/torch/2.10.0/` 可继续使用：

```bash
bash build-image.sh \
  --soc 950 --cann-version 9.1.0 \
  --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
  --cann-root /home/user/cann-run \
  --torch-root /home/user/cann-run/torch \
  --check --files-only
```

任意其他布局可用精确文件参数，不需要重命名或移动原文件；原始文件名仍须包含正确的版本、SoC 和平台信息。
