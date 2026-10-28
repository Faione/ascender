# Ascend 开发镜像构建工具

使用本地安装材料构建 NPU 或 CAModel 仿真开发镜像。实现采用 Bash + 单个多 target Dockerfile，输出名称自动生成，不接受自定义 tag。

工具不下载、上传材料，不安装宿主机驱动，也不管理容器日常运行或算子验证。APT/PIP 可在镜像构建过程中联网安装附加依赖。

## 使用前准备

- 宿主机：Bash 3.2+、常见文件工具、`sha256sum` 或 `shasum`；检查仿真 ZIP 还需要 `unzip`。
- 实际构建：带 Buildx 的 Docker，当前本地 context 的 Engine builder 使用 `docker` driver；基础镜像已在该 Engine 中。Dockerfile 使用 Engine 自带 frontend，不声明远端 syntax 镜像。
- 首个组件组合：Ubuntu 22.04 / linux/amd64 / Python 3.10 / CANN 9.1.0 / Torch 2.10.0+cpu / torch-npu 2.10.0.post4。
- CANN、对应 SoC 的 ops、Torch wheels、CAModel 均由用户预先准备。构建主机无需 NPU；非 amd64 主机运行安装器需要用户已有跨架构执行能力。

软件版本组合有官方配套记录；真实 CANN 镜像、设备运行和 CAModel 功能尚未在本仓库验收。`--allow-unverified` 仅放行未收录的软件组合，不能绕过具体文件、版本和架构错误。

## 材料存放

推荐将大文件放在仓库外：

```text
/data/ascend-materials/
├── cann/9.1.0/linux-amd64/
│   ├── Ascend-cann-toolkit_9.1.0_linux-x86_64.run
│   └── Ascend-cann-950-ops_9.1.0_linux-x86_64.run
├── torch/2.10.0/cp310/linux-amd64/
│   ├── torch-2.10.0+cpu-cp310-cp310-manylinux_2_28_x86_64.whl
│   └── torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl
└── camodel/950/9.1.0/
    ├── model.zip
    ├── tools.zip
    ├── init.sh
    └── env.sh  # 可选
```

CAModel 文件名是示例，需按实际供应方材料修改。完整获取入口、参考直链、旧目录兼容及验证状态见 `docs/downloads.md`。

## 构建

在工具目录执行 NPU 构建：

```bash
bash build-image.sh \
  --target npu --soc 950 --cann-version 9.1.0 \
  --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
  --materials-root /data/ascend-materials
```

仿真构建复用公共阶段，不需要先构建 NPU 镜像：

```bash
bash build-image.sh \
  --target simulation --soc 950 --cann-version 9.1.0 \
  --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
  --materials-root /data/ascend-materials \
  --camodel-dir /data/ascend-materials/camodel/950/9.1.0 \
  --camodel-archive model.zip --camodel-archive tools.zip
```

ZIP 按清单解压到 `/opt/CAModel/<ZIP文件名去掉扩展名>/`，在 `/opt/CAModel` 下执行 `init.sh`；可用 `--camodel-init` 指定其他脚本。入口和 Bash 会加载可选 `env.sh`。构建时 `export` 的变量不会自动保留到运行时，应将其写入环境脚本。

`--camodel-check check.sh` 可增加构建时的无设备最小仿真测试；未提供时，安装成功也会明确标为功能未验证。init/check 不应依赖下载；需要的内容应先准备为本地材料。脚本按用户提供的受信任代码在构建容器内执行。

只需要 CANN 时使用 `--no-torch`，同时省略全部 Torch 专用参数。查看完整参数：

```bash
bash build-image.sh --help
```

`examples/build-npu.sh`、`examples/build-simulation.sh` 提供首个组合的简短调用，默认材料根为 `/data/ascend-materials`，可用 `ASCEND_DEV_MATERIALS_ROOT` 修改。仿真示例的 ZIP 名需按实际文件编辑。

## 预览和检查

在完整构建命令后追加以下选项：

| 选项 | 行为 |
| --- | --- |
| `--materials` | 展示下载入口和预期材料位置，即使文件未准备好也能使用 |
| `--dry-run` | 展示有效参数和材料选择，不访问 Docker、不写文件；最终 tag 暂不计算 |
| `--check` | 检查本地文件和 Docker，计算镜像名，不构建 |
| `--check --files-only` | 仅检查材料，不访问 Docker |

三种模式互斥，正常构建自动完整检查。宿主机只核对包名、版本、ABI、架构及 ZIP 完整性，不执行 `.run` 和用户脚本；包内部校验、Bash 语法检查、glibc/依赖条件和安装后元数据校验在容器内完成。

## 参数规则

- 优先级：默认值 → 文档列出的 `ASCEND_DEV_*` 环境变量 → CLI；重复标量以最后一次为准，列表按顺序追加。
- 材料选择：`--toolkit` / `--ops` / `--torch-wheel` / `--torch-npu-wheel` 精确路径优先；其次是组件根目录；最后是统一材料根目录。同一选定目录有多个候选时报错。
- 旧目录用 `--cann-root /home/user/cann-run` 和 `--torch-root /home/user/cann-run/torch`；分别读取 `<soc>/<CANN版本>/` 与 `<Torch基础版本>/`，不扫描上级目录。
- 通用相对文件路径以调用目录为基准；CAModel 的 archive/init/env/check 相对路径以 `--camodel-dir` 为基准。
- `--apt-mirror` 为 Ubuntu 仓库基础 URL（包括 `/ubuntu` 路径），`--pip-index` 为独立 PIP 索引；URL 不接受凭据/查询串。私有源认证未实现。
- `--apt-package vim --apt-package htop` 和 `--pip-package pytest --pip-package 'numpy<2'` 可以重复追加。Python 包支持名称、extras 和版本约束；直接 URL、VCS、markers 及 pip 选项不作为该参数输入。附加约束文件用 `--pip-constraints`。
- `--post-install` 在公共环境安装后执行 Bash 定制脚本，随后再次检查核心版本。它先于 CAModel 初始化；仿真特有的目录整理放在 `init.sh` 中。不要向它写宿主机安装逻辑。
- `--network none` 仅禁用 RUN 的网络；当前没有完整离线依赖管理。`--no-cache` 不删除现有缓存。

支持的环境变量为 `ASCEND_DEV_TARGET`、`ASCEND_DEV_SOC`、`ASCEND_DEV_CANN_VERSION`、`ASCEND_DEV_TORCH_VERSION`、`ASCEND_DEV_TORCH_NPU_VERSION`、`ASCEND_DEV_BASE_IMAGE`、`ASCEND_DEV_MATERIALS_ROOT`、`ASCEND_DEV_CAMODEL_DIR`。不读取 `ASCEND_DEV_TAG` 或其他输出命名变量。

## 自动命名与报告

名称示意（末尾为输入指纹的 SHA-256 前 12 位）：

```text
ascend-dev:npu-cann9.1.0-950-torch2.10.0_cpu-npu2.10.0.post4-py310-amd64-<HASH12>
ascend-sim:sim-cann9.1.0-950-torch2.10.0_cpu-npu2.10.0.post4-py310-amd64-<HASH12>
```

没有 `--tag`、时间戳 tag 或 `latest` 别名。参数、材料、容器脚本和基础镜像 ID 影响指纹；材料所在绝对路径、报告目录、显示格式和缓存开关不影响。相同基础镜像 ID 的不同引用别名也得到相同 tag。在线依赖源会变化，指纹代表输入意图，不保证每次镜像逐字节相同。

实际构建在 `build/<build-id>/`（可用 `--output-dir` 修改父目录）输出：

- `manifest.txt`：有效参数、自动镜像名和输入指纹。
- `materials.sha256`：按构建上下文逻辑路径记录的哈希，不含宿主机绝对路径。
- `build.log`：Docker 构建输出。
- `result.txt`：退出码、失败阶段、镜像引用和 ID；材料检查失败也保留结果。
- 成功后才生成 `image-ref.txt` 及 `installed-packages.txt`。

只收集当前目标所需材料；复制后再次检查哈希，发现材料变化即失败。原始 `.run`、wheel 和 ZIP 只读挂载到构建步骤，不通过 COPY 写入最终镜像。临时构建目录在成功、失败或信号退出时清理；不清除 Docker 的全局缓存。为读取镜像内包清单，成功构建后会临时 `docker create/cp/rm`，不会启动该容器或访问设备。

## 外部代码验证

使用 `examples/compose.yaml` 挂载代码与可写 HOME，通过宿主机 UID/GID 控制产物属主。启动前用 `examples/prepare-user.sh` 从目标镜像生成带对应用户的 passwd/group 副本，由 Compose 只读挂载，避免 `I have no name!` 和用户查询失败。NPU 叠加 `examples/compose.npu.yaml` 的设备、组和只读驱动挂载。

完整命令及权限前提见 `docs/runtime.md`。镜像入口也支持 `docker exec ... bash` / `bash -lc` 加载环境；直接 `docker exec ... python3` 时应显式使用 `/usr/local/bin/ascend-entrypoint` 包装。

## 开发检查

```bash
python3 -m unittest discover -s tests -v
```

测试使用 Python 标准库创建材料样本和 Docker 替身，不下载内容、不执行真实安装。Python 仅为开发测试依赖；实际宿主机构建脚本不依赖 Python。

另执行 `bash -n`，如已安装 ShellCheck 则运行 `shellcheck -x build-image.sh lib/common.sh scripts/*.sh examples/*.sh`。当前自动测试覆盖参数、材料失败场景、稳定命名、Docker 调用、失败清理、ZIP 解压安全及环境加载；不能代替真实镜像/NPU/CAModel 验收。
