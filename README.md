# Ascend 开发镜像构建工具

使用本地材料构建 NPU 或 CAModel 仿真开发镜像。宿主机工具使用 Python 标准库，无第三方 Python 依赖；镜像使用单个多 target Dockerfile。镜像 tag 自动生成，不接受自定义。

工具不下载或上传材料，不安装宿主机驱动，不管理容器日常启停。APT/PIP 可在镜像构建过程中联网安装依赖；运行配置工具只生成 Compose 文件和账号副本。

## Quick Start

以下以 Ascend 950 仿真环境为例。在装有 Python 3.9+、Docker 和 Buildx 的机器上，进入本项目目录执行，无需 `pip install`。

**1. 准备材料和基础镜像。** 下载并按原名保存到以下目录，具体文件名及下载入口见[材料目录](#材料目录)和[下载说明](docs/downloads.md)：

```text
/data/ascend-materials/
├── cann/       # CANN 9.1.0 Toolkit、950 ops 的 .run 文件
├── torch/      # Torch 2.10.0+cpu、torch-npu 2.10.0.post4 的 cp310/x86_64 wheels
└── camodel/    # ESLMODEL 主包、同名 _config.zip、init.sh；可选 env.sh/check.sh
```

仿真包例如 `x86_64_ESLMODEL_Ascend950DT_123A1.zip` 及 `x86_64_ESLMODEL_Ascend950DT_123A1_config.zip`。无需提前解压；`init.sh` 按供应方要求准备，运行期环境变量放入可选的 `env.sh`。

```bash
docker pull --platform linux/amd64 ubuntu:22.04
```

**2. 构建镜像。** 工具自动选择配对的仿真包，解压到 `/opt/CAModel/` 并执行初始化：

```bash
python3 build.py \
  --target simulation --soc 950 --cann-version 9.1.0 \
  --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
  --materials-root /data/ascend-materials
```

首次使用可先在上述命令末尾追加 `--check --files-only` 仅检查材料，或追加 `--check` 同时检查 Docker；检查通过后移除这些选项进行构建。若已准备仿真自检脚本，可追加 `--camodel-check check.sh`。

构建 NPU 环境时，将 `--target simulation` 改为 `--target npu`，无需准备 `camodel/`。两个目标均不要求构建主机具有 NPU；运行 NPU 环境需要目标服务器的设备和驱动。

**3. 生成运行配置并进入容器。** 构建成功后打印 `Report: ...`，该目录中的 `image-ref.txt` 保存自动生成的镜像名。将下面的 `/path/to/report/image-ref.txt` 替换为实际文件，`/data/operator-project` 替换为已存在、可读写的待验证代码目录。在目标 Docker 服务器上以开发用户执行：

```bash
python3 prepare_runtime.py \
  --image-ref-file /path/to/report/image-ref.txt \
  --code-dir /data/operator-project \
  --output-dir /data/ascend-runtime

docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash
```

镜像需要已存在于目标服务器的本地 Docker 中。生成器不会启动容器；后面的 Compose 命令由用户执行。默认映射当前 UID/GID，用户名为 `developer`，源码挂载到 `/workspace/code`，可写 HOME 为 `/workspace/home`，无需 export 环境变量。

更多参数通过 `python3 build.py --help`、`python3 prepare_runtime.py --help` 查看；权限及 NPU 设备配置见[运行配置说明](docs/runtime.md)。

## 使用前准备

- 宿主机：Python 3.9+，支持 Linux/macOS；无需 pip 安装、虚拟环境、unzip、sha256sum、awk 或 sed。
- 实际构建：Docker 和 Buildx；当前本地 context 使用 Unix socket，Engine builder 使用 `docker` driver，基础镜像已在同一 Engine 中。跨架构执行能力由用户准备。
- 首个参考组合：Ubuntu 22.04 / linux/amd64 / 容器 Python 3.10 / CANN 9.1.0 / Torch 2.10.0+cpu / torch-npu 2.10.0.post4。
- 构建主机无需 NPU。运行 NPU 容器时才需要目标服务器的设备和驱动。

软件版本有官方配套记录；真实镜像、NPU 和 CAModel 功能仍待目标服务器验收。`--allow-unverified` 仅放行未收录的软件组合，不能绕过文件、版本、ABI 和架构错误。

## 材料目录

每个材料根目录保存一套配套材料，直接放进三个固定子目录，不增加版本、SoC 或架构目录层级：

```text
/data/ascend-materials/
├── cann/
│   ├── Ascend-cann-toolkit_9.1.0_linux-x86_64.run
│   └── Ascend-cann-950-ops_9.1.0_linux-x86_64.run
├── torch/                          # --no-torch 时不需要
│   ├── torch-2.10.0+cpu-cp310-cp310-manylinux_2_28_x86_64.whl
│   └── torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl
└── camodel/                        # 仅仿真目标读取
    ├── x86_64_ESLMODEL_Ascend950DT_123A1.zip
    ├── x86_64_ESLMODEL_Ascend950DT_123A1_config.zip
    ├── init.sh                     # 必需：构建期初始化
    ├── env.sh                      # 可选：运行期环境
    └── check.sh                    # 可选：显式启用的仿真自检
```

根目录名称和位置不限，文件保持供应方原名，无需提前解压。不同版本组合使用不同材料根目录。默认根目录为调用目录下的 `./materials`，推荐大文件放在仓库外并显式指定 `--materials-root`。

下载入口、基础镜像准备和仿真脚本要求见 [安装材料获取与保存](docs/downloads.md)。基础镜像通过 Docker pull/load 手动准备，不放进材料目录。

## 构建

在项目目录执行 NPU 构建：

```bash
python3 build.py \
  --target npu --soc 950 --cann-version 9.1.0 \
  --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
  --materials-root /data/ascend-materials
```

仿真只需将 `--target` 改为 `simulation`，无需先构建 NPU 镜像：

```bash
python3 build.py \
  --target simulation --soc 950 --cann-version 9.1.0 \
  --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
  --materials-root /data/ascend-materials \
  --camodel-check check.sh
```

不需要自检时省略 `--camodel-check`，此时报告明确保留“仿真功能未验证”。只安装 CANN 时使用 `--no-torch`，同时省略所有 Torch 专用参数。查看完整参数：

```bash
python3 build.py --help
python3 prepare_runtime.py --help
```

仿真自动选择 `camodel/` 当前目录下的 `*ESLMODEL*.zip`，要求一对同名主包和 `_config.zip` 配置包。多个版本共存时必须通过重复的 `--camodel-archive FILE` 选定一对；文件名中的 `123A1` 不从 CANN 版本推导，也不推断它与 SoC 的兼容关系。

所有 ZIP 内容直接解压到 `/opt/CAModel/`，保留内部层级，不添加包名目录。同名目录合并，重复文件报错，保留可执行位；拒绝符号链接、路径穿越和文件/目录冲突。随后加载 CANN、在 `/opt/CAModel` 下执行 `init.sh`，再加载可选 `env.sh`、运行显式指定的 `check.sh`。供应方脚本应消费已准备的本地材料，不下载内容；运行期变量应写入 `env.sh`。

## 预览和检查

在完整构建命令后追加以下选项：

| 选项 | 行为 |
| --- | --- |
| `--materials` | 显示下载入口和材料位置；文件缺失时也可使用 |
| `--dry-run` | 展示参数和材料选择，不访问 Docker、不写文件；tag 暂不计算 |
| `--check` | 检查材料和 Docker，计算镜像名，不构建 |
| `--check --files-only` | 只检查材料，不访问 Docker |

三种模式互斥。正常构建自动执行完整检查。宿主机检查文件名、版本、ABI、架构、仿真包配对、ZIP 安全及 CRC，不执行安装器或供应方脚本；包内部及安装后检查在容器内执行。

## 参数规则

- 优先级：默认值 → 列出的 `ASCEND_DEV_*` 环境变量 → CLI；重复标量以最后一次为准，列表按顺序追加。
- 统一布局仅支持 `ROOT/cann/`、`ROOT/torch/`、`ROOT/camodel/`，不递归。旧的 `--cann-root`、`--torch-root`、`--camodel-dir` 已移除。
- `--toolkit`、`--ops`、`--torch-wheel`、`--torch-npu-wheel` 可精确指定文件，优先于固定目录查找；仍校验原始文件名。多个匹配文件时报错。
- 通用相对路径以调用目录为基准；`--camodel-archive`、`--camodel-init`、`--camodel-env`、`--camodel-check` 的相对路径以 `ROOT/camodel/` 为基准，均支持绝对路径。
- `--apt-mirror` 指定 Ubuntu 仓库基础 URL，`--pip-index` 指定 PIP 索引；不接受凭据、查询串或空白。
- PIP 源写入所有用户可读的 `/etc/pip.conf`，root、developer 和后续用户默认共享；不持久化 `PIP_INDEX_URL`，允许按 pip 的优先级覆盖。构建检查 root 和非 root 均可读取。
- `--apt-package vim --apt-package htop`、`--pip-package pytest --pip-package 'numpy<2'` 可重复。PIP 参数接受包名、extras 和版本约束，不接受直接 URL、VCS、markers 或选项；附加约束使用 `--pip-constraints`。
- `--post-install` 指定公共安装阶段执行的 Bash 脚本，先于 CAModel 初始化；执行后重新校验核心版本。
- `--network none` 仅禁用 RUN 网络，当前不是完整离线安装方案。`--no-cache` 不删除全局缓存。

支持的环境变量为 `ASCEND_DEV_TARGET`、`ASCEND_DEV_SOC`、`ASCEND_DEV_CANN_VERSION`、`ASCEND_DEV_TORCH_VERSION`、`ASCEND_DEV_TORCH_NPU_VERSION`、`ASCEND_DEV_BASE_IMAGE`、`ASCEND_DEV_MATERIALS_ROOT`。无 tag 配置变量。运行配置工具不依赖这些变量。

## 自动命名与报告

名称示意：

```text
ascend-dev:npu-cann9.1.0-950-torch2.10.0_cpu-npu2.10.0.post4-py310-amd64-<HASH12>
ascend-sim:sim-cann9.1.0-950-torch2.10.0_cpu-npu2.10.0.post4-py310-amd64-<HASH12>
```

没有 `--tag` 或 `latest` 别名。参数、材料、容器脚本、共享 ZIP 模块和基础镜像 ID 参与指纹。材料绝对路径、报告目录、缓存和显示选项不影响命名；相同基础镜像 ID 的引用别名得到同一个 tag。在线依赖源会变化，指纹不保证镜像逐字节可复现。

实际构建输出到 `build/<build-id>/`，可用 `--output-dir` 修改父目录：

- `manifest.txt`：参数、自动镜像名、输入指纹和验证状态。
- `materials.sha256`：按上下文逻辑路径记录的材料 SHA-256。
- `build.log`：Docker 构建输出。
- `result.txt`：退出码、失败阶段、镜像引用和 ID；材料检查失败也保留。
- 成功后生成 `image-ref.txt` 和 `installed-packages.txt`。`image-id.txt` 由 Docker 构建成功后写入，后续报告阶段仍可能失败；`image-ref.txt` 才是完整流程成功的标志。

输入复制到临时上下文后再次核对哈希，变化则失败。原始安装包通过只读 RUN mount 使用，不 COPY 进最终镜像。临时目录在成功、失败或中断时清理。镜像内包清单通过未启动的临时容器读取，不访问设备。

## 外部代码验证

在目标 Docker 服务器上以开发用户生成运行配置：

```bash
python3 prepare_runtime.py \
  --image-ref-file /data/build/run-001/image-ref.txt \
  --code-dir /data/operator-project \
  --output-dir /data/ascend-runtime

docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash
```

UID/GID 默认来自当前用户，用户名默认为 `developer`。脚本准备可写 HOME 和容器账号副本，避免 `I have no name!`。生成的 Compose 使用具体值，无需 export、`.env` 或 `--env-file`。NPU 自动读取设备 GID 并加入只读驱动挂载；仿真不依赖设备和驱动。详见 [运行配置说明](docs/runtime.md)。

## 模块与开发检查

模块职责、依赖方向和替换方式见 [设计说明](DESIGN.md)。宿主机不再保留旧 Bash 入口；容器内 Bash 继续用于安装器和供应方环境脚本。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q ascender build.py prepare_runtime.py
for script in scripts/*.sh; do bash -n "$script" || exit; done
```

测试使用标准库、ZIP 样本和 Docker 替身，不下载、不安装真实组件。ShellCheck 可选。测试不能替代实际 Docker/NPU/CAModel 验收。
